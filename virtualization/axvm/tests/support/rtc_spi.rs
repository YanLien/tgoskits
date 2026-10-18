//! Exclusive, host-owned QEMU PL031 alarm; never changes the RTC calendar.

use core::marker::PhantomData;
use std::sync::{
    Arc,
    atomic::{AtomicBool, AtomicU32, Ordering},
};

use aarch64_cpu::asm::barrier::{SY, dsb};
use anyhow::{Context, Result, ensure};
use ax_arm_pl031::Rtc;
use ax_std::os::arceos::modules::ax_hal;
use ax_sync::RawSpinLock;
use axvm::{VcpuInterruptPort, diagnostics::HostIrqCapture};

static BORROWED: AtomicBool = AtomicBool::new(false);

#[derive(Default)]
struct Counters {
    handled: AtomicU32,
    errors: AtomicU32,
    wrong_cpu: AtomicU32,
    invalid_alarm: AtomicU32,
    pulse_failed: AtomicU32,
}

pub struct RtcSpi {
    bank: Arc<RawSpinLock<Option<Rtc>>>,
    counters: Arc<Counters>,
    irq: Option<ax_hal::irq::IrqHandle>,
    observation: Option<HostIrqCapture>,
    original: Option<u32>,
    borrowed: bool,
    _not_send_sync: PhantomData<*mut ()>,
}

impl RtcSpi {
    pub fn start(port: VcpuInterruptPort) -> Result<Self> {
        ensure!(
            ax_hal::platform_name() == "linux,dummy-virt",
            "RTC needs QEMU virt"
        );
        ensure!(
            ax_cpu::registers::current_exception_level() == 2,
            "RTC needs EL2"
        );
        ensure!(
            ax_hal::percpu::this_cpu_id() == 0,
            "RTC controller needs CPU0"
        );
        verify_firmware()?;
        let gic = ax_hal::irq::resolve_percpu_irq(ax_hal::irq::HwIrq(30))?;
        let irq = ax_hal::irq::resolve_irq_source(ax_hal::irq::IrqSource::ControllerLine {
            domain: gic.domain,
            hwirq: ax_hal::irq::HwIrq(34),
        })
        .context("resolve RTC SPI in the active GIC domain")?;
        ensure!(
            irq != ax_hal::time::irq_num(),
            "RTC aliases the scheduler timer"
        );
        ensure!(
            Some(irq) != ax_hal::console::irq_num(),
            "RTC aliases the console"
        );
        let mut source = Self {
            bank: Arc::new(RawSpinLock::new(None)),
            counters: Arc::new(Counters::default()),
            irq: None,
            observation: None,
            original: None,
            borrowed: false,
            _not_send_sync: PhantomData,
        };
        BORROWED
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| anyhow::anyhow!("RTC fixture already borrowed"))?;
        source.borrowed = true;
        let bank = source.bank.clone();
        let counters = source.counters.clone();
        let handle = ax_hal::irq::request_irq(
            irq,
            ax_hal::irq::IrqRequest::new_concurrent(move |context| {
                let valid = {
                    let mut guard = bank.lock_irqsave();
                    if let Some(rtc) = guard.as_mut() {
                        let pending = rtc.interrupt_pending();
                        rtc.enable_interrupt(false);
                        rtc.clear_interrupt();
                        dsb(SY);
                        pending && !rtc.matched() && !rtc.interrupt_pending()
                    } else {
                        false
                    }
                };
                // The callback itself is owned by the IRQ framework, not locked
                // or shared with task code. Only the register bank is serialized.
                let failure = if context.cpu != ax_hal::irq::CpuId(0) {
                    Some(&counters.wrong_cpu)
                } else if !valid {
                    Some(&counters.invalid_alarm)
                } else if port.pulse().is_err() {
                    Some(&counters.pulse_failed)
                } else {
                    None
                };
                if let Some(counter) = failure {
                    counter.fetch_add(1, Ordering::Relaxed);
                    counters.errors.fetch_add(1, Ordering::Relaxed);
                }
                counters.handled.fetch_add(1, Ordering::Release);
                ax_hal::irq::IrqReturn::Handled
            })
            .affinity(ax_hal::irq::IrqAffinity::Fixed(ax_hal::irq::CpuId(0)))
            .auto_enable(ax_hal::irq::AutoEnable::No),
        )
        .context("request exclusive RTC SPI34")?;
        source.irq = Some(handle);
        ax_hal::irq::disable_irq(handle)?;
        let mapped = ax_mm::iomap(0x0901_0000usize.into(), 0x1000)
            .context("map exclusive PL031 register page as Device memory")?;
        let base = mapped.as_usize() as *mut u32;
        // SAFETY: strict QEMU/FDT admission checked this complete 4KiB PL031
        // resource; iomap supplies a permanent Device RW mapping. This case has
        // no host RTC consumer or Guest RTC/counter driver/passthrough. BORROWED
        // and the disabled exclusive SPI prevent another fixture/IRQ accessor.
        // Each aligned ID word is within the page. No Rtc view exists yet.
        let identity: [u32; 8] = unsafe {
            core::array::from_fn(|index| base.wrapping_add(0xfe0 / 4 + index).read_volatile())
        };
        ensure!(
            identity == [0x31, 0x10, 0x14, 0, 0x0d, 0xf0, 5, 0xb1],
            "unexpected PL031 identity"
        );
        // SAFETY: same live Device mapping and exclusive ownership above.
        // This is the single Rtc object, published only into the IRQ-safe bank.
        // The mapping outlives the IRQ callback and is never unmapped by us.
        let rtc = unsafe { Rtc::new(base) };
        ensure!(
            rtc.match_timestamp() == 0
                && !rtc.interrupt_enabled()
                && !rtc.matched()
                && !rtc.interrupt_pending(),
            "RTC alarm was not inactive"
        );
        source.original = Some(rtc.match_timestamp());
        *source.bank.lock_irqsave() = Some(rtc);
        ax_hal::irq::set_trigger(irq, ax_hal::irq::IrqTrigger::Level)?;
        source.observation = Some(axvm::diagnostics::observe_host_irq(34)?);
        ax_hal::irq::enable_irq(handle)?;
        println!(
            "VIRQ_RTC_CONFIG base=0x9010000 intid=34 cpu=0 target_cpu=1 initial_mr=0 imsc=0 ris=0 \
             mis=0"
        );
        Ok(source)
    }

    pub fn arm(&self, sequence: u32) -> Result<u32> {
        ensure!(
            ax_hal::percpu::this_cpu_id() == 0,
            "RTC controller left CPU0"
        );
        self.check_delivered(sequence - 1)?;
        let handle = self.irq.context("RTC source already closed")?;
        // Mask the exact controller line before acquiring its register bank.
        ax_hal::irq::disable_irq(handle)?;
        let matched = {
            let mut bank = self.bank.lock_irqsave();
            let rtc = bank.as_mut().context("RTC bank absent")?;
            rtc.enable_interrupt(false);
            rtc.clear_interrupt();
            dsb(SY);
            let mut matched = None;
            for _ in 0..3 {
                let now = rtc.get_unix_timestamp();
                rtc.set_match_timestamp(now);
                dsb(SY);
                if rtc.matched() {
                    ensure!(
                        rtc.match_timestamp() == now
                            && !rtc.interrupt_enabled()
                            && !rtc.interrupt_pending(),
                        "RTC masked alarm state disagrees"
                    );
                    matched = Some(now);
                    break;
                }
            }
            let matched = matched.context("RTC alarm crossed three second boundaries")?;
            rtc.enable_interrupt(true);
            dsb(SY);
            ensure!(
                rtc.interrupt_enabled() && rtc.interrupt_pending(),
                "RTC did not assert"
            );
            matched
        };
        ax_hal::irq::enable_irq(handle)?;
        Ok(matched)
    }

    pub fn check_delivered(&self, sequence: u32) -> Result<()> {
        ensure!(
            self.counters.handled.load(Ordering::Acquire) == sequence,
            "RTC interrupt count mismatch"
        );
        ensure!(
            self.counters.errors.load(Ordering::Acquire) == 0,
            "RTC handler pending/clear/CPU/delivery error"
        );
        Ok(())
    }

    /// Observe the existing owner after a failed wait; never acknowledge,
    /// mask, rearm or retry a delivery from this diagnostic path.
    pub fn report_failure(&self) {
        let (handled, errors, wrong_cpu, invalid_alarm, pulse_failed, device) = {
            // Controller and callback are both admitted on CPU0. Copy while
            // locally excluding the callback; print only after releasing it.
            let _irq = ax_std::os::arceos::guard::IrqSaveGuard::new();
            let bank = self.bank.lock_irqsave();
            let device = bank.as_ref().map(|rtc| {
                (
                    rtc.get_unix_timestamp(),
                    rtc.match_timestamp(),
                    rtc.interrupt_enabled(),
                    rtc.matched(),
                    rtc.interrupt_pending(),
                )
            });
            (
                self.counters.handled.load(Ordering::Acquire),
                self.counters.errors.load(Ordering::Relaxed),
                self.counters.wrong_cpu.load(Ordering::Relaxed),
                self.counters.invalid_alarm.load(Ordering::Relaxed),
                self.counters.pulse_failed.load(Ordering::Relaxed),
                device,
            )
        };
        println!(
            "VIRQ_RTC_FAILURE_COUNTS handled={handled} errors={errors} wrong_cpu={wrong_cpu} \
             invalid_alarm={invalid_alarm} pulse_failed={pulse_failed}"
        );
        if let Some((dr, mr, imsc, ris, mis)) = device {
            println!(
                "VIRQ_RTC_FAILURE_DEVICE present=1 dr={dr} mr={mr} imsc={} ris={} mis={}",
                u8::from(imsc),
                u8::from(ris),
                u8::from(mis)
            );
        } else {
            println!("VIRQ_RTC_FAILURE_DEVICE present=0");
        }
        if let Some(handle) = self.irq {
            match ax_hal::irq::irq_status(handle) {
                Ok(status) => println!(
                    "VIRQ_RTC_FAILURE_FRAMEWORK action_enabled={} framework_line_enabled={} \
                     in_flight={} action_running={} hardware_pending=unknown \
                     hardware_active=unknown",
                    u8::from(status.action_enabled),
                    u8::from(status.line_enabled),
                    status.in_flight,
                    u8::from(status.action_running)
                ),
                Err(error) => println!("VIRQ_RTC_FAILURE_FRAMEWORK error={error:?}"),
            }
        }
    }

    pub fn finish(mut self, policy: &str, samples: u32) -> Result<()> {
        self.check_delivered(samples)?;
        self.close()?;
        println!(
            "VIRQ_RTC_SUMMARY policy={policy} intid=34 cpu=0 handled={samples} errors=0 retired=1 \
             restored_mr=0 imsc=0 ris=0 mis=0"
        );
        Ok(())
    }

    fn close(&mut self) -> Result<()> {
        if !self.borrowed {
            return Ok(());
        }
        ensure!(ax_hal::percpu::this_cpu_id() == 0, "RTC cleanup left CPU0");
        if let Some(handle) = self.irq {
            ax_hal::irq::disable_irq(handle)?;
            {
                let mut bank = self.bank.lock_irqsave();
                if let Some(rtc) = bank.as_mut() {
                    rtc.enable_interrupt(false);
                    rtc.clear_interrupt();
                    dsb(SY);
                }
            }
            ax_hal::irq::synchronize_irq(handle)?;
            ax_hal::irq::free_irq(handle)?;
            self.irq = None;
        }
        if let Some(original) = self.original {
            let mut bank = self.bank.lock_irqsave();
            let rtc = bank.as_mut().context("RTC restore lost register owner")?;
            rtc.enable_interrupt(false);
            rtc.set_match_timestamp(original);
            rtc.clear_interrupt();
            dsb(SY);
            ensure!(
                rtc.match_timestamp() == original
                    && !rtc.interrupt_enabled()
                    && !rtc.matched()
                    && !rtc.interrupt_pending(),
                "RTC restore failed"
            );
            self.original = None;
        }
        self.observation.take();
        self.bank.lock_irqsave().take();
        // All callback and register views are now gone. A failed close leaves
        // BORROWED set, quarantining the device instead of publishing an alias.
        BORROWED.store(false, Ordering::Release);
        self.borrowed = false;
        Ok(())
    }
}

impl Drop for RtcSpi {
    fn drop(&mut self) {
        if let Err(error) = self.close() {
            println!("VIRQ_RTC_CLEANUP_FAILED {error:#}");
        }
    }
}

fn verify_firmware() -> Result<()> {
    let fdt = ax_hal::dtb::get_fdt().context("RTC firmware absent")?;
    let mut nodes = fdt.find_compatible(&["arm,pl031"]);
    let node = nodes.next().context("PL031 absent")?;
    ensure!(nodes.next().is_none(), "multiple PL031 resources");
    let reg: std::vec::Vec<u32> = node
        .find_property("reg")
        .context("RTC reg absent")?
        .u32_list()
        .collect();
    let interrupts: std::vec::Vec<u32> = node
        .find_property("interrupts")
        .context("RTC interrupts absent")?
        .u32_list()
        .collect();
    let parent = node
        .interrupt_parent()
        .context("RTC interrupt parent absent")?;
    ensure!(
        reg == [0, 0x9010000, 0, 0x1000] && interrupts == [0, 2, 4],
        "unsupported RTC resource"
    );
    ensure!(
        parent.node.compatibles().any(|s| s == "arm,gic-v3")
            && parent
                .node
                .find_property("#interrupt-cells")
                .map(|p| p.u32())
                == Some(3),
        "RTC needs the QEMU GICv3 binding"
    );
    ensure!(
        matches!(
            node.find_property("status").map(|p| p.str()),
            None | Some("okay" | "ok")
        ),
        "RTC disabled by firmware"
    );
    Ok(())
}
