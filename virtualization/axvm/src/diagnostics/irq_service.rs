//! Test-only, boot-selected scheduling experiments for deferred IRQ services.

use std::{
    sync::{
        OnceLock,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};

use crate::{AxVmError, AxVmResult, RunId, SchedulePolicy, host::task};

const ROUNDS_PER_WINDOW: u64 = 8;
const WINDOW: Duration = Duration::from_millis(1);
static CONFIG: OnceLock<Config> = OnceLock::new();

#[derive(Clone, Copy)]
struct Config {
    mode: Mode,
    rounds: u64,
    window: Duration,
}

const DEFAULT: Config = Config {
    mode: Mode::Off,
    rounds: ROUNDS_PER_WINDOW,
    window: WINDOW,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Mode {
    Off,
    Inherit,
    Bounded,
}

impl Mode {
    fn name(self) -> &'static str {
        match self {
            Self::Off => "off",
            Self::Inherit => "inherit",
            Self::Bounded => "bounded",
        }
    }
}

/// Selects one experiment before VM creation. Replacement is rejected.
/// Fair targets keep the default service policy; FIFO targets inherit only in
/// enabled modes. This is an axtest experiment, not a production admission API.
pub fn configure(mode: &str, rounds: u64, window_us: u64) -> AxVmResult {
    let mode = match mode {
        "off" => Mode::Off,
        "inherit" => Mode::Inherit,
        "bounded" => Mode::Bounded,
        _ => return Err(AxVmError::invalid_config("unsupported IRQ service mode")),
    };
    if !(1..=256).contains(&rounds) || !(100..=100_000).contains(&window_us) {
        return Err(AxVmError::invalid_config(
            "IRQ service dispatch limit out of range",
        ));
    }
    CONFIG
        .set(Config {
            mode,
            rounds,
            window: Duration::from_micros(window_us),
        })
        .map_err(|_| AxVmError::invalid_config("IRQ service mode already configured"))?;
    println!(
        "VIRQ_IRQ_SERVICE_CONFIG mode={} limit={rounds} window_ns={}",
        mode.name(),
        window_us * 1000
    );
    Ok(())
}

pub(crate) fn selected_policy(target: SchedulePolicy) -> AxVmResult<SchedulePolicy> {
    if CONFIG.get().unwrap_or(&DEFAULT).mode == Mode::Off {
        return Ok(SchedulePolicy::default());
    }
    match target {
        SchedulePolicy::Fair { .. } => Ok(SchedulePolicy::default()),
        SchedulePolicy::Fifo { .. } => Ok(target),
        _ => Err(AxVmError::invalid_config(
            "IRQ service inheritance supports only Fair and FIFO targets",
        )),
    }
}

/// State is owned solely by the fixed worker, never shared with IRQ producers.
pub(crate) struct Dispatch {
    run: RunId,
    thread: u64,
    mode: Mode,
    target: SchedulePolicy,
    actual: SchedulePolicy,
    limited: bool,
    window_end: Instant,
    used: u64,
    maximum: u64,
    rounds: u64,
    waits: u64,
    limit: u64,
    window: Duration,
}

impl Dispatch {
    pub(crate) fn start(run: RunId, target: SchedulePolicy) -> Self {
        let actual = task::current_thread().base_policy();
        let expected = selected_policy(target).expect("worker policy validated before spawn");
        assert_eq!(
            actual, expected,
            "IRQ service did not receive selected policy"
        );
        let config = *CONFIG.get().unwrap_or(&DEFAULT);
        let mode = config.mode;
        Self {
            run,
            thread: task::current_thread().id().as_u64(),
            mode,
            target,
            actual,
            limited: mode == Mode::Bounded && matches!(target, SchedulePolicy::Fifo { .. }),
            window_end: Instant::now() + config.window,
            used: 0,
            maximum: 0,
            rounds: 0,
            waits: 0,
            limit: config.rounds,
            window: config.window,
        }
    }

    /// Retains all canonical pending state while waiting outside every lock.
    /// A stop bypasses dispatch after the timer wait; it never drains a new round.
    pub(crate) fn admit_round(&mut self, stopping: &AtomicBool) -> bool {
        if self.limited {
            let now = Instant::now();
            if now >= self.window_end {
                self.window_end = now + self.window;
                self.used = 0;
            }
            if self.used == self.limit {
                self.waits += 1;
                std::thread::sleep(self.window_end.saturating_duration_since(now));
                if stopping.load(Ordering::Acquire) {
                    return false;
                }
                self.window_end = Instant::now() + self.window;
                self.used = 0;
            }
            self.used += 1;
            self.maximum = self.maximum.max(self.used);
        }
        self.rounds += 1;
        true
    }
}

impl Drop for Dispatch {
    fn drop(&mut self) {
        let describe = |policy| match policy {
            SchedulePolicy::Fifo { priority } => ("fifo", u64::from(priority.get())),
            SchedulePolicy::Fair { .. } => ("fair", 0),
            _ => ("other", 0),
        };
        let (target, target_priority) = describe(self.target);
        let (actual, actual_priority) = describe(self.actual);
        println!(
            "VIRQ_IRQ_SERVICE vm={} run={} thread={} mode={} target={} target_priority={} \
             actual={} actual_priority={} rounds={} waits={} max_rounds={} limit={} window_ns={}",
            self.run.vm().vm_id(),
            self.run.generation(),
            self.thread,
            self.mode.name(),
            target,
            target_priority,
            actual,
            actual_priority,
            self.rounds,
            self.waits,
            self.maximum,
            self.limit,
            self.window.as_nanos()
        );
    }
}
