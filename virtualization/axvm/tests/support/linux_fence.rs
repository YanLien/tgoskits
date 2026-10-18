//! Causal serial snapshots; state belongs to one Linux run, never a VM ID.

use anyhow::{Context, Result, ensure};

use super::{MemoryConfig, checksum_after, field};
use crate::clock;

#[derive(Clone, Copy)]
struct Snapshot {
    batches: u64,
    ns: u64,
    request_ticks: u64,
    observed_ticks: u64,
}

#[derive(Default)]
pub(super) struct Fences {
    enabled: bool,
    resolution_ns: Option<u64>,
    pending: Option<u64>,
    snapshots: Vec<Snapshot>,
}

impl Fences {
    pub fn new(enabled: bool) -> Self {
        Self {
            enabled,
            ..Self::default()
        }
    }

    pub fn enabled(&self) -> bool {
        self.enabled
    }

    pub fn ready(&self) -> bool {
        !self.enabled || self.resolution_ns.is_some()
    }

    pub fn completed(&self, end: bool) -> bool {
        self.snapshots.len() == if end { 2 } else { 1 }
    }

    pub fn request(&mut self, end: bool) -> Result<()> {
        ensure!(
            self.enabled && self.ready() && self.pending.is_none(),
            "fence not ready"
        );
        ensure!(
            self.snapshots.len() == usize::from(end),
            "fence request phase mismatch"
        );
        self.pending = Some(clock::host_ticks());
        Ok(())
    }

    pub fn validate_report(&self, batches: u64) -> Result<()> {
        ensure!(self.ready(), "Linux progress before fence readiness");
        ensure!(
            self.snapshots.last().is_none_or(|s| s.batches <= batches),
            "Linux progress precedes earlier fence snapshot"
        );
        Ok(())
    }

    pub fn line(
        &mut self,
        line: &str,
        ready: bool,
        batches: u64,
        memory: Option<MemoryConfig>,
    ) -> Result<()> {
        ensure!(self.enabled && ready, "unexpected Linux fence record");
        let mut fields = line.split_whitespace();
        match fields.next() {
            Some("LINUX_FENCE_READY") => {
                ensure!(
                    self.resolution_ns.is_none() && batches == 0,
                    "duplicate or late fence readiness"
                );
                ensure!(
                    fields.next() == Some("version=1")
                        && fields.next() == Some("clock=monotonic_raw"),
                    "fence clock protocol mismatch"
                );
                let resolution = field(fields.next(), "resolution_ns=")?;
                let bytes = field(fields.next(), "working_set_bytes=")?;
                let every = field(fields.next(), "every_batches=")?;
                ensure!(
                    (1..=1000000).contains(&resolution) && fields.next().is_none(),
                    "invalid fence clock resolution"
                );
                ensure!(
                    (bytes, every) == memory.map_or((0, 1), |m| (m.bytes, m.every)),
                    "fence workload configuration mismatch"
                );
                self.resolution_ns = Some(resolution);
            }
            Some("LINUX_FENCE_REPLY") => {
                let request_ticks = self.pending.context("unsolicited fence reply")?;
                ensure!(
                    self.ready() && fields.next() == Some("version=1"),
                    "fence reply version mismatch"
                );
                let expected = if self.snapshots.is_empty() {
                    "phase=begin"
                } else {
                    "phase=end"
                };
                ensure!(
                    fields.next() == Some(expected) && self.snapshots.len() < 2,
                    "fence reply phase mismatch"
                );
                let count = field(fields.next(), "batches=")?;
                let checksum = field(fields.next(), "checksum=")?;
                let ns = field(fields.next(), "time_ns=")?;
                let cpu = field(fields.next(), "guest_cpu=")?;
                if let Some(memory) = memory {
                    let m = field(fields.next(), "memory_batches=")?;
                    let bytes = field(fields.next(), "logical_bytes=")?;
                    let sum = field(fields.next(), "memory_checksum=")?;
                    ensure!(
                        (m, bytes, sum) == memory.expected(count)?,
                        "fence memory verification failed"
                    );
                }
                let iterations = count
                    .checked_mul(8192)
                    .context("fence iterations overflow")?;
                ensure!(
                    fields.next().is_none()
                        && cpu == 0
                        && ns > 0
                        && count > 0
                        && count >= batches
                        && count - batches <= 256
                        && checksum == checksum_after(iterations),
                    "fence counter or checksum mismatch"
                );
                let observed_ticks = clock::host_ticks();
                ensure!(
                    request_ticks <= observed_ticks,
                    "fence Host clock regressed"
                );
                self.snapshots.push(Snapshot {
                    batches: count,
                    ns,
                    request_ticks,
                    observed_ticks,
                });
                self.pending = None;
            }
            _ => anyhow::bail!("unknown Linux fence record"),
        }
        Ok(())
    }

    pub fn finish(&self, policy: &str) -> Result<()> {
        if !self.enabled {
            return Ok(());
        }
        ensure!(
            self.pending.is_none() && self.snapshots.len() == 2,
            "fences not completed"
        );
        let (begin, end) = (self.snapshots[0], self.snapshots[1]);
        ensure!(
            end.batches > begin.batches
                && end.ns > begin.ns
                && end.request_ticks > begin.observed_ticks,
            "fenced window has no work or time"
        );
        let hz = ax_cpu::timer::counter_frequency();
        ensure!(hz > 0, "zero fence Host clock frequency");
        let lower =
            u128::from(end.request_ticks - begin.observed_ticks) * 1000000000 / u128::from(hz);
        let upper = (u128::from(end.observed_ticks - begin.request_ticks) * 1000000000)
            .div_ceil(u128::from(hz));
        let tolerance = 2
            * (1000000000u128.div_ceil(u128::from(hz))
                + u128::from(self.resolution_ns.context("missing fence resolution")?));
        let elapsed = u128::from(end.ns - begin.ns);
        ensure!(
            elapsed + tolerance >= lower && elapsed <= upper + tolerance,
            "Guest fenced elapsed violates Host causal bounds"
        );
        println!(
            "VIRQ_LINUX_FENCE_SUMMARY policy={policy} begin_batches={} end_batches={} begin_ns={} \
             end_ns={} begin_request_ticks={} begin_observed_ticks={} end_request_ticks={} \
             end_observed_ticks={} frequency_hz={hz} stopped=1",
            begin.batches,
            end.batches,
            begin.ns,
            end.ns,
            begin.request_ticks,
            begin.observed_ticks,
            end.request_ticks,
            end.observed_ticks
        );
        Ok(())
    }
}
