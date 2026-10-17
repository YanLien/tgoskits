//! Boot-scoped service placement for controlled kernel-test comparisons.

use std::sync::{
    OnceLock,
    atomic::{AtomicUsize, Ordering},
};

use crate::{AxVmError, AxVmResult, host::task};

static CPU: OnceLock<usize> = OnceLock::new();
static COUNTS: [Counts; 2] = [const { Counts::new() }; 2];

struct Counts {
    started: AtomicUsize,
    finished: AtomicUsize,
    observations: AtomicUsize,
    wrong_cpu: AtomicUsize,
}

impl Counts {
    const fn new() -> Self {
        Self {
            started: AtomicUsize::new(0),
            finished: AtomicUsize::new(0),
            observations: AtomicUsize::new(0),
            wrong_cpu: AtomicUsize::new(0),
        }
    }
}

/// Fixes control and signal worker affinity once, before creating any VM.
/// Requires initialized capture and a valid host CPU. No runtime reconfiguration.
pub fn configure(cpu: usize) -> AxVmResult {
    let count = super::STORE.get().map_or(0, std::vec::Vec::len);
    if cpu >= count || cpu >= usize::BITS as usize {
        return Err(AxVmError::invalid_config(
            "service CPU is outside initialized topology",
        ));
    }
    CPU.set(cpu)
        .map_err(|_| AxVmError::invalid_config("service placement already configured"))
}

pub(crate) fn cpu() -> Option<usize> {
    CPU.get().copied()
}

#[derive(Clone, Copy, Debug)]
pub(crate) enum Role {
    Control,
    Signal,
}

impl Role {
    fn name(self) -> &'static str {
        match self {
            Self::Control => "control",
            Self::Signal => "signal",
        }
    }
}

/// Task-local statistics; never owns a thread or changes its affinity.
pub(crate) struct Probe {
    role: Role,
    cpu: usize,
    thread: u64,
    observations: usize,
    wrong_cpu: usize,
}

impl Probe {
    pub(crate) fn start(role: Role) -> Option<Self> {
        let cpu = cpu()?;
        COUNTS[role as usize]
            .started
            .fetch_add(1, Ordering::Relaxed);
        let mut probe = Self {
            role,
            cpu,
            thread: task::current_thread().id().as_u64(),
            observations: 0,
            wrong_cpu: 0,
        };
        probe.observe();
        Some(probe)
    }

    pub(crate) fn observe(&mut self) {
        self.observations += 1;
        self.wrong_cpu += usize::from(task::current_cpu_id() != self.cpu);
    }
}

impl Drop for Probe {
    fn drop(&mut self) {
        self.observe();
        let counts = &COUNTS[self.role as usize];
        counts
            .observations
            .fetch_add(self.observations, Ordering::Relaxed);
        counts
            .wrong_cpu
            .fetch_add(self.wrong_cpu, Ordering::Relaxed);
        println!(
            "VIRQ_SERVICE_THREAD role={} thread={} requested_cpu={} observations={} wrong_cpu={}",
            self.role.name(),
            self.thread,
            self.cpu,
            self.observations,
            self.wrong_cpu
        );
        // Publish this task's completed aggregate; VM teardown joins all producers.
        counts.finished.fetch_add(1, Ordering::Release);
    }
}

/// Checks placement observations after all VM services have exited and joined.
/// A wrong CPU, absent role, or unmatched service lifetime fails the measurement.
pub fn validate() -> AxVmResult {
    let cpu = cpu().ok_or_else(|| AxVmError::invalid_config("service placement not configured"))?;
    for role in [Role::Control, Role::Signal] {
        let counts = &COUNTS[role as usize];
        let finished = counts.finished.load(Ordering::Acquire);
        let started = counts.started.load(Ordering::Relaxed);
        let observations = counts.observations.load(Ordering::Relaxed);
        let wrong = counts.wrong_cpu.load(Ordering::Relaxed);
        println!(
            "VIRQ_SERVICE_SUMMARY role={} requested_cpu={} started={} finished={} observations={} \
             wrong_cpu={}",
            role.name(),
            cpu,
            started,
            finished,
            observations,
            wrong
        );
        if started == 0 || started != finished || observations < started * 2 || wrong != 0 {
            return Err(AxVmError::invalid_config(
                "service placement observations failed",
            ));
        }
    }
    Ok(())
}
