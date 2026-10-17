//! One finite FIFO60 witness on the IRQ service CPU, joined on every exit.

use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread::JoinHandle,
    time::{Duration, Instant},
};

use anyhow::{Context, Result, ensure};
use ax_std::os::arceos::api::task::{
    AxCpuMask, AxWaitQueueHandle, ax_set_current_affinity, ax_wait_queue_wait_until,
    ax_wait_queue_wake,
};
use axvm::{RtPriority, SchedulePolicy};

#[derive(Default)]
struct Shared {
    ready: AtomicBool,
    active: AtomicBool,
    stop: AtomicBool,
    exited: AtomicBool,
    gate: AxWaitQueueHandle,
}

pub struct Report {
    pub start: u64,
    pub end: u64,
    pub thread: u64,
    pub wrong_cpu: u64,
}

pub struct Witness {
    shared: Arc<Shared>,
    worker: Option<JoinHandle<Result<Report>>>,
}

impl Witness {
    pub fn start() -> Result<Self> {
        let shared = Arc::new(Shared::default());
        let worker_shared = shared.clone();
        let worker = std::thread::Builder::new()
            .name("virq-fifo60-witness".into())
            .spawn(move || {
                let result = execute(&worker_shared);
                worker_shared.exited.store(true, Ordering::Release);
                result
            })?;
        let mut witness = Self {
            shared,
            worker: Some(worker),
        };
        let deadline = Instant::now() + Duration::from_secs(10);
        while !witness.shared.ready.load(Ordering::Acquire) {
            if witness.shared.exited.load(Ordering::Acquire) {
                witness.finish()?;
                anyhow::bail!("inversion witness exited before registration");
            }
            ensure!(
                Instant::now() < deadline,
                "inversion witness startup timed out"
            );
            std::thread::sleep(Duration::from_millis(1));
        }
        Ok(witness)
    }

    /// Called only after arming a delayed physical IRQ on CPU0.
    pub fn activate(&self) {
        self.shared.active.store(true, Ordering::Release);
        ax_wait_queue_wake(&self.shared.gate, 1);
    }

    pub fn finish(&mut self) -> Result<Report> {
        self.worker
            .take()
            .context("inversion witness already joined")?
            .join()
            .map_err(|_| anyhow::anyhow!("inversion witness panicked"))?
    }
}

impl Drop for Witness {
    fn drop(&mut self) {
        if self.worker.is_some() {
            self.shared.stop.store(true, Ordering::Release);
            ax_wait_queue_wake(&self.shared.gate, 1);
            if let Err(error) = self.finish() {
                panic!("inversion witness cleanup failed: {error:#}");
            }
        }
    }
}

fn execute(shared: &Shared) -> Result<Report> {
    ax_set_current_affinity(AxCpuMask::one_shot(0)).context("pin inversion witness")?;
    let current = ax_std::os::arceos::task::thread::current::current_thread_handle()?;
    let policy = SchedulePolicy::fifo(RtPriority::new(60)?);
    current.set_policy(policy)?;
    ensure!(
        current.base_policy() == policy,
        "inversion witness policy mismatch"
    );
    let thread = current.id().as_u64();
    shared.ready.store(true, Ordering::Release);
    ax_wait_queue_wait_until(
        &shared.gate,
        || shared.active.load(Ordering::Acquire) || shared.stop.load(Ordering::Acquire),
        None,
    );
    let start = super::clock::host_ticks();
    let duration = ax_cpu::timer::counter_frequency() / 20;
    let mut wrong_cpu = 0;
    while !shared.stop.load(Ordering::Acquire)
        && super::clock::host_ticks().saturating_sub(start) < duration
    {
        wrong_cpu += u64::from(ax_std::os::arceos::modules::ax_hal::percpu::this_cpu_id() != 0);
        core::hint::spin_loop();
    }
    let end = super::clock::host_ticks();
    Ok(Report {
        start,
        end,
        thread,
        wrong_cpu,
    })
}
