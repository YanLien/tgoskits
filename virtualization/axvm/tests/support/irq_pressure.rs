//! Synthetic, separately owned GIC SGI load; critical IRQ ownership is unchanged.

use core::marker::PhantomData;
use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    thread::JoinHandle,
    time::{Duration, Instant},
    vec::Vec,
};

use anyhow::{Context, Result, ensure};
use ax_std::os::arceos::modules::ax_hal;

use super::{clock, platform::TimerPlatform};

const INTID: u32 = 15;
const LIMIT: u64 = 4096;
const ROUNDS: u64 = 64;

#[derive(Clone, Copy)]
pub struct Config {
    period_ticks: u64,
    burst: u64,
}

impl Config {
    pub fn from_resource(resource: &toml::Value) -> Result<Option<Self>> {
        let mode = resource
            .get("irq_pressure")
            .and_then(toml::Value::as_str)
            .context("missing IRQ pressure selection")?;
        ensure!(
            matches!(mode, "off" | "sgi"),
            "invalid IRQ pressure selection"
        );
        let read = |name| -> Result<u64> {
            u64::try_from(
                resource
                    .get(name)
                    .and_then(toml::Value::as_integer)
                    .context("missing IRQ pressure setting")?,
            )
            .context("negative IRQ pressure setting")
        };
        let period = read("irq_pressure_period_us")?;
        let burst = read("irq_pressure_burst")?;
        ensure!(
            (100..=1_000_000).contains(&period) && (1..=8).contains(&burst),
            "IRQ pressure setting out of range"
        );
        let frequency = ax_cpu::timer::counter_frequency();
        let period_ticks = frequency
            .checked_mul(period)
            .context("IRQ period overflow")?
            / 1_000_000;
        ensure!(period_ticks != 0, "IRQ period below counter resolution");
        println!(
            "VIRQ_IRQ_PRESSURE_CONFIG mode={mode} intid={INTID} sender_cpu=2 target_cpu=0 \
             period_us={period} period_ticks={period_ticks} burst={burst} rounds={ROUNDS} \
             limit={LIMIT} frequency_hz={frequency}"
        );
        Ok((mode == "sgi").then_some(Self {
            period_ticks,
            burst,
        }))
    }
}

#[derive(Default)]
struct Shared {
    stop: AtomicBool,
    exited: AtomicBool,
    pending: AtomicU64,
    handled: AtomicU64,
    errors: AtomicU64,
    start: AtomicU64,
    end: AtomicU64,
    checksum: AtomicU64,
}

struct Event {
    sequence: u64,
    scheduled: u64,
    sent: u64,
    start: u64,
    end: u64,
    observed: u64,
    checksum: u64,
}

struct Report {
    events: Vec<Event>,
    skipped: u64,
}

/// Validated records after the worker and IRQ action have both retired.
/// Owns no live hardware or shared state; retain until runtime capture is frozen.
pub struct RetiredReport {
    report: Report,
    start_count: u64,
    end_count: u64,
    window_start: u64,
    window_end: u64,
}

impl RetiredReport {
    pub fn emit(self, policy: &str) {
        let handled = self.report.events.len();
        for event in &self.report.events {
            println!(
                "VIRQ_IRQ_PRESSURE_EVENT policy={policy} sequence={} scheduled_ticks={} \
                 sent_ticks={} handler_start_ticks={} handler_end_ticks={} observed_ticks={} \
                 checksum={} intid={INTID} sender_cpu=2 target_cpu=0",
                event.sequence,
                event.scheduled,
                event.sent,
                event.start,
                event.end,
                event.observed,
                event.checksum
            );
        }
        println!(
            "VIRQ_IRQ_PRESSURE_SUMMARY policy={policy} sent={handled} handled={handled} errors=0 \
             start_count={} end_count={} window_start_ticks={} window_end_ticks={} \
             skipped_periods={} joined=1 retired=1",
            self.start_count,
            self.end_count,
            self.window_start,
            self.window_end,
            self.report.skipped
        );
    }
}

pub struct Pressure {
    shared: Arc<Shared>,
    irq: Option<ax_hal::irq::IrqHandle>,
    worker: Option<JoinHandle<Result<Report>>>,
    window_start: u64,
    start_count: u64,
    _not_send_sync: PhantomData<*mut ()>,
}

impl Pressure {
    pub fn start(config: Config) -> Result<Self> {
        TimerPlatform::detect()?.validate_cpu(0)?;
        ensure!(
            ax_cpu::registers::current_exception_level() == 2
                && ax_hal::percpu::this_cpu_id() == 0
                && ax_hal::cpu_num() >= 4,
            "SGI pressure requires admitted EL2 with a CPU0 controller and four CPUs"
        );
        let irq = ax_hal::irq::resolve_percpu_irq(ax_hal::irq::HwIrq(INTID))?;
        ensure!(
            irq != ax_hal::irq::ipi_irq() && irq != ax_hal::time::irq_num(),
            "SGI pressure conflicts with a system IRQ"
        );
        let shared = Arc::new(Shared::default());
        let handler = shared.clone();
        let handle = ax_hal::irq::request_irq(
            irq,
            ax_hal::irq::IrqRequest::new_concurrent(move |context| {
                let start = clock::host_ticks();
                let sequence = handler.pending.load(Ordering::Acquire);
                if context.irq != irq
                    || context.cpu != ax_hal::irq::CpuId(0)
                    || !ax_hal::irq::in_irq_context()
                    || sequence != handler.handled.load(Ordering::Relaxed) + 1
                    || sequence > LIMIT
                {
                    handler.errors.fetch_add(1, Ordering::Relaxed);
                }
                let checksum = known_answer(sequence);
                handler.start.store(start, Ordering::Relaxed);
                handler.end.store(clock::host_ticks(), Ordering::Relaxed);
                handler.checksum.store(checksum, Ordering::Relaxed);
                // Publishes this immutable reply until the next request.
                handler.handled.store(sequence, Ordering::Release);
                ax_hal::irq::IrqReturn::Handled
            })
            .scope(ax_hal::irq::IrqScope::PerCpu {
                cpus: ax_hal::irq::CpuMask::from_cpu(ax_hal::irq::CpuId(0)),
            })
            .auto_enable(ax_hal::irq::AutoEnable::No),
        )?;
        let mut source = Self {
            shared,
            irq: Some(handle),
            worker: None,
            window_start: 0,
            start_count: 0,
            _not_send_sync: PhantomData,
        };
        ax_hal::irq::enable_irq(handle)?;
        let worker_shared = source.shared.clone();
        source.worker = Some(
            std::thread::Builder::new()
                .name("virq-sgi-producer-cpu2".into())
                .spawn(move || {
                    let result = produce(&worker_shared, config, irq);
                    worker_shared.exited.store(true, Ordering::Release);
                    result
                })?,
        );
        let deadline = Instant::now() + Duration::from_secs(10);
        while source.shared.handled.load(Ordering::Acquire) == 0 {
            ensure!(
                !source.shared.exited.load(Ordering::Acquire) && Instant::now() < deadline,
                "SGI producer failed or timed out before first delivery"
            );
            std::thread::sleep(Duration::from_millis(1));
        }
        {
            let _irq = ax_std::os::arceos::guard::IrqSaveGuard::new();
            source.start_count = source.shared.handled.load(Ordering::Acquire);
            source.window_start = clock::host_ticks();
        }
        Ok(source)
    }

    /// These are sequential atomic observations; CPU2 may still advance.
    pub fn report_failure(&self) {
        println!(
            "VIRQ_IRQ_PRESSURE_FAILURE pending={} handled={} errors={} stop={} exited={} \
             observed_ticks={} observation=sequential",
            self.shared.pending.load(Ordering::Acquire),
            self.shared.handled.load(Ordering::Acquire),
            self.shared.errors.load(Ordering::Acquire),
            u8::from(self.shared.stop.load(Ordering::Acquire)),
            u8::from(self.shared.exited.load(Ordering::Acquire)),
            clock::host_ticks()
        );
    }

    pub fn retire(mut self) -> Result<RetiredReport> {
        let (window_end, end_count) = {
            let _irq = ax_std::os::arceos::guard::IrqSaveGuard::new();
            (
                clock::host_ticks(),
                self.shared.handled.load(Ordering::Acquire),
            )
        };
        let unexpectedly_exited = self.shared.exited.load(Ordering::Acquire);
        let report = self.close()?.context("SGI producer already joined")?;
        let handled = self.shared.handled.load(Ordering::Acquire);
        ensure!(
            !unexpectedly_exited && end_count > self.start_count,
            "SGI pressure did not remain active across sampling"
        );
        ensure!(
            self.shared.errors.load(Ordering::Relaxed) == 0
                && handled == report.events.len() as u64,
            "SGI delivery count or handler identity error"
        );
        for event in &report.events {
            ensure!(
                event.scheduled <= event.sent
                    && event.sent <= event.start
                    && event.start <= event.end
                    && event.end <= event.observed
                    && event.checksum == known_answer(event.sequence),
                "SGI reply verification failed"
            );
        }
        Ok(RetiredReport {
            report,
            start_count: self.start_count,
            end_count,
            window_start: self.window_start,
            window_end,
        })
    }

    fn close(&mut self) -> Result<Option<Report>> {
        ensure!(ax_hal::percpu::this_cpu_id() == 0, "SGI cleanup left CPU0");
        self.shared.stop.store(true, Ordering::Release);
        // Even a failed producer must be joined before revoking its IRQ action.
        let joined = self
            .worker
            .take()
            .map(|worker| {
                worker
                    .join()
                    .map_err(|_| anyhow::anyhow!("SGI producer panicked"))
                    .and_then(|result| result)
            })
            .transpose();
        if let Some(handle) = self.irq {
            ax_hal::irq::disable_irq(handle)?;
            ax_hal::irq::synchronize_irq(handle)?;
            ax_hal::irq::free_irq(handle)?;
            self.irq = None;
        }
        joined
    }
}

impl Drop for Pressure {
    fn drop(&mut self) {
        if let Err(error) = self.close() {
            println!("VIRQ_IRQ_PRESSURE_CLEANUP_FAILED {error:#}");
        }
    }
}

fn known_answer(mut value: u64) -> u64 {
    for _ in 0..ROUNDS {
        value = core::hint::black_box(value.wrapping_mul(6364136223846793005).wrapping_add(1));
    }
    value
}

fn produce(shared: &Shared, config: Config, irq: ax_hal::irq::IrqId) -> Result<Report> {
    use ax_std::os::arceos::api::task::{AxCpuMask, ax_set_current_affinity};
    ax_set_current_affinity(AxCpuMask::one_shot(2))?;
    let mut report = Report {
        events: Vec::with_capacity(LIMIT as usize),
        skipped: 0,
    };
    let mut due = clock::host_ticks();
    let frequency = ax_cpu::timer::counter_frequency();
    while !shared.stop.load(Ordering::Acquire) {
        let now = clock::host_ticks();
        if now < due {
            let ns = u128::from(due - now) * 1_000_000_000 / u128::from(frequency);
            std::thread::sleep(Duration::from_nanos(u64::try_from(ns)?));
            continue;
        }
        for _ in 0..config.burst {
            if shared.stop.load(Ordering::Acquire) {
                break;
            }
            ensure!(ax_hal::percpu::this_cpu_id() == 2, "SGI producer left CPU2");
            let sequence = report.events.len() as u64 + 1;
            ensure!(sequence <= LIMIT, "SGI pressure capacity exhausted");
            shared.pending.store(sequence, Ordering::Release);
            let sent = clock::host_ticks();
            ax_hal::irq::send_ipi(irq, ax_hal::irq::IpiTarget::Cpu(ax_hal::irq::CpuId(0)))?;
            let deadline = Instant::now() + Duration::from_secs(2);
            while shared.handled.load(Ordering::Acquire) != sequence {
                ensure!(
                    shared.errors.load(Ordering::Relaxed) == 0 && Instant::now() < deadline,
                    "SGI handler failed or acknowledgement timed out"
                );
                std::thread::yield_now();
            }
            report.events.push(Event {
                sequence,
                scheduled: due,
                sent,
                start: shared.start.load(Ordering::Relaxed),
                end: shared.end.load(Ordering::Relaxed),
                observed: clock::host_ticks(),
                checksum: shared.checksum.load(Ordering::Relaxed),
            });
        }
        let missed = (clock::host_ticks() - due) / config.period_ticks;
        report.skipped = report
            .skipped
            .checked_add(missed)
            .context("SGI skipped period overflow")?;
        due = due
            .checked_add(
                (missed + 1)
                    .checked_mul(config.period_ticks)
                    .context("SGI period overflow")?,
            )
            .context("SGI deadline overflow")?;
    }
    Ok(report)
}
