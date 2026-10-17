//! Host work owned through startup, sampling, VM shutdown, and joined cleanup.

#[path = "contention/work.rs"]
mod work;
use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    thread::JoinHandle,
    time::{Duration, Instant},
};

use anyhow::{Context, Result, ensure};
pub use work::Workload;
use work::{CPU_ITERATIONS, MEMORY_WORDS_PER_BATCH, WorkResult, WorkState};

#[derive(Default)]
struct Shared {
    active: AtomicBool,
    run_gate: ax_std::os::arceos::api::task::AxWaitQueueHandle,
    stop: AtomicBool,
    exited: AtomicBool,
    batches: AtomicU64,
    wrong_cpu: AtomicU64,
}

struct WorkerReport {
    thread: u64,
    work: WorkResult,
}

pub struct HostContention {
    shared: Arc<Shared>,
    worker: Option<JoinHandle<Result<WorkerReport>>>,
    spec: Workload,
}

impl HostContention {
    pub fn start(spec: Workload) -> Result<Self> {
        spec.validate()?;
        ensure!(
            spec.cpu() < ax_std::os::arceos::task::sched::cpu_topology_len()?,
            "contention CPU is unavailable"
        );
        let shared = Arc::new(Shared::default());
        let worker_shared = shared.clone();
        let worker = std::thread::Builder::new()
            .name(format!("virq-host-load-cpu{}", spec.cpu()))
            .spawn(move || {
                let result = execute(&worker_shared, spec);
                worker_shared.exited.store(true, Ordering::Release);
                result
            })
            .context("spawn host contention worker")?;
        let mut load = Self {
            shared,
            worker: Some(worker),
            spec,
        };
        let deadline = Instant::now() + Duration::from_secs(10);
        while load.batches() == 0 {
            if load.shared.exited.load(Ordering::Acquire) {
                // Join observes the worker's original allocation/setup error.
                load.join()?;
                anyhow::bail!("host load ended at startup");
            }
            ensure!(Instant::now() < deadline, "host load startup timed out");
            std::thread::sleep(Duration::from_millis(1));
        }
        Ok(load)
    }

    pub fn activate(&self) -> Result<()> {
        use ax_std::os::arceos::api::task::ax_wait_queue_wake;
        let before = self.batches();
        self.shared.active.store(true, Ordering::Release);
        ax_wait_queue_wake(&self.shared.run_gate, 1);
        let deadline = Instant::now() + Duration::from_secs(10);
        while self.batches() == before {
            ensure!(
                !self.shared.exited.load(Ordering::Acquire),
                "host load exited before activation"
            );
            ensure!(Instant::now() < deadline, "host load activation timed out");
            std::thread::sleep(Duration::from_millis(1));
        }
        Ok(())
    }

    pub fn batches(&self) -> u64 {
        // Pure completed-batch count, not publication of the private buffer.
        self.shared.batches.load(Ordering::Relaxed)
    }

    pub fn finish(mut self, start_batches: u64, end_batches: u64, policy: &str) -> Result<()> {
        let unexpectedly_exited = self.shared.exited.load(Ordering::Acquire);
        let report = self.join()?.context("host load was already joined")?;
        let wrong_cpu = self.shared.wrong_cpu.load(Ordering::Relaxed);
        ensure!(
            !unexpectedly_exited,
            "host load ended before sampling finished"
        );
        ensure!(
            end_batches > start_batches,
            "host load made no sampling progress"
        );
        ensure!(wrong_cpu == 0, "host load left its requested CPU");
        let cpu = self.spec.cpu();
        let thread = report.thread;
        let final_batches = self.batches();
        match report.work {
            WorkResult::Cpu { checksum } => println!(
                "VIRQ_LOAD_SUMMARY policy={policy} cpu={cpu} thread={thread} \
                 batch_iterations={CPU_ITERATIONS} start_batches={start_batches} \
                 end_batches={end_batches} final_batches={final_batches} wrong_cpu={wrong_cpu} \
                 checksum={checksum} joined=1"
            ),
            WorkResult::Memory {
                bytes,
                checksum,
                verified_words,
                read_bytes,
                write_bytes,
            } => println!(
                "VIRQ_MEMORY_SUMMARY policy={policy} cpu={cpu} thread={thread} \
                 working_set_bytes={bytes} chunk_words={MEMORY_WORDS_PER_BATCH} \
                 start_batches={start_batches} end_batches={end_batches} \
                 final_batches={final_batches} read_bytes={read_bytes} write_bytes={write_bytes} \
                 checksum={checksum} verified_words={verified_words} mismatch_words=0 \
                 wrong_cpu={wrong_cpu} joined=1"
            ),
        }
        Ok(())
    }

    fn join(&mut self) -> Result<Option<WorkerReport>> {
        self.shared.stop.store(true, Ordering::Release);
        ax_std::os::arceos::api::task::ax_wait_queue_wake(&self.shared.run_gate, 1);
        self.worker
            .take()
            .map(|worker| {
                worker
                    .join()
                    .map_err(|_| anyhow::anyhow!("host load panicked"))?
            })
            .transpose()
    }
}

impl Drop for HostContention {
    fn drop(&mut self) {
        if let Err(error) = self.join() {
            println!("VIRQ_LOAD_CLEANUP_FAILED {error:#}");
        }
    }
}

fn execute(shared: &Shared, spec: Workload) -> Result<WorkerReport> {
    use ax_std::os::arceos::{
        api::task::{AxCpuMask, ax_current_task_id, ax_set_current_affinity},
        modules::ax_hal::percpu::this_cpu_id,
    };
    let cpu = spec.cpu();
    ax_set_current_affinity(AxCpuMask::one_shot(cpu)).context("pin host contention worker")?;
    let thread = ax_current_task_id();
    let mut work = WorkState::new(spec)?;
    let mut batches = 0u64;
    loop {
        if batches != 0 && !shared.active.load(Ordering::Acquire) {
            ax_std::os::arceos::api::task::ax_wait_queue_wait_until(
                &shared.run_gate,
                || shared.active.load(Ordering::Acquire) || shared.stop.load(Ordering::Acquire),
                None,
            );
        }
        if shared.stop.load(Ordering::Acquire) {
            break;
        }
        if this_cpu_id() != cpu {
            shared.wrong_cpu.fetch_add(1, Ordering::Relaxed);
        }
        work.run_batch();
        batches = batches
            .checked_add(1)
            .context("host load batch count overflow")?;
        shared.batches.store(batches, Ordering::Relaxed);
        std::thread::yield_now();
    }
    Ok(WorkerReport {
        thread,
        work: work.finish(batches)?,
    })
}
