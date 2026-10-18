//! Consume bounded serial progress from a separate Linux guest; no shared GPA.

use std::time::{Duration, Instant};

use anyhow::{Context, Result, ensure};
use axvm::{SchedulePolicy, VmStatus};

use super::support::Fixture;

#[path = "linux_fence.rs"]
mod fence;

#[derive(Clone, Copy)]
pub struct MemoryConfig {
    bytes: u64,
    every: u64,
}

impl MemoryConfig {
    pub fn from_resource(resource: &toml::Value) -> Result<Self> {
        let read = |name| -> Result<u64> {
            u64::try_from(
                resource
                    .get(name)
                    .and_then(toml::Value::as_integer)
                    .context("missing Linux memory setting")?,
            )
            .context("negative Linux memory setting")
        };
        let config = Self {
            bytes: read("linux_memory_bytes")?,
            every: read("linux_memory_every")?,
        };
        ensure!(
            (1048576..=67108864).contains(&config.bytes)
                && config.bytes.is_multiple_of(8192)
                && (1..=1024).contains(&config.every),
            "invalid Linux memory settings"
        );
        println!(
            "VIRQ_LINUX_MEMORY_CONFIG working_set_bytes={} every_batches={} chunk_words=8192",
            config.bytes, config.every
        );
        Ok(config)
    }

    fn expected(self, batches: u64) -> Result<(u64, u64, u64)> {
        let memory_batches = batches.div_ceil(self.every);
        let accesses = memory_batches
            .checked_mul(8192)
            .context("Linux memory access overflow")?;
        let logical_bytes = accesses
            .checked_mul(16)
            .context("Linux memory byte overflow")?;
        let words = u128::from(self.bytes / 8);
        let q = u128::from(accesses) / words;
        let r = u128::from(accesses) % words;
        let checksum = q * words * (words + 1) / 2
            + words * q * q.saturating_sub(1) / 2
            + r * (r + 1) / 2
            + r * q;
        Ok((memory_batches, logical_bytes, checksum as u64))
    }
}

#[derive(Default)]
pub struct Progress {
    host_cpu: usize,
    offset: usize,
    ready: bool,
    batches: u64,
    checksum: u64,
    reports: u64,
    memory: Option<MemoryConfig>,
    memory_ready: bool,
    fences: fence::Fences,
}

impl Progress {
    pub fn host_cpu(&self) -> usize {
        self.host_cpu
    }

    pub fn start(
        fixture: &mut Fixture,
        memory: Option<MemoryConfig>,
        fences: bool,
        host_cpu: usize,
    ) -> Result<Self> {
        ensure!(matches!(host_cpu, 1 | 3), "invalid Linux Host CPU");
        let snapshot = fixture.vm.snapshot();
        ensure!(
            snapshot.vcpu.len() == 1
                && snapshot.vcpu[0].id == 0
                && snapshot.vcpu[0].phys_cpu_set == Some(1usize << host_cpu),
            "Linux vCPU affinity disagrees with its measurement configuration"
        );
        fixture.vm.start()?.wait()?;
        fixture.wait(Duration::from_secs(120), |snapshot, _| {
            snapshot.state == VmStatus::Running && snapshot.cpu.running_vcpu_count == 1
        })?;
        let mut progress = Self {
            host_cpu,
            memory,
            fences: fence::Fences::new(fences),
            ..Self::default()
        };
        let deadline = Instant::now() + Duration::from_secs(120);
        while progress.batches == 0 {
            progress.poll(fixture)?;
            ensure!(
                Instant::now() < deadline,
                "Linux workload startup timed out"
            );
            std::thread::sleep(Duration::from_millis(1));
        }
        fixture.check_policy(SchedulePolicy::default(), 1)?;
        println!(
            "VIRQ_LINUX_BOOT vm=1 vcpu=0 host_cpu={host_cpu} guest_cpu=0 batches={}",
            progress.batches
        );
        Ok(progress)
    }

    pub fn poll(&mut self, fixture: &mut Fixture) -> Result<u64> {
        fixture.flush_console()?;
        let snapshot = fixture.vm.snapshot();
        ensure!(
            snapshot.state == VmStatus::Running && snapshot.last_failure.is_none(),
            "Linux workload stopped before measurement completed"
        );
        self.consume(fixture)?;
        Ok(self.batches)
    }

    pub fn begin_window(&mut self, fixture: &mut Fixture) -> Result<u64> {
        self.window(fixture, false)
    }

    pub fn end_window(&mut self, fixture: &mut Fixture) -> Result<u64> {
        self.window(fixture, true)
    }

    fn window(&mut self, fixture: &mut Fixture, end: bool) -> Result<u64> {
        self.poll(fixture)?;
        if self.fences.enabled() {
            self.fences.request(end)?;
            fixture.send_input(if end { b'E' } else { b'B' })?;
            let deadline = Instant::now() + Duration::from_secs(10);
            while !self.fences.completed(end) {
                self.poll(fixture)?;
                ensure!(Instant::now() < deadline, "Linux fence response timed out");
                if !self.fences.completed(end) {
                    std::thread::sleep(Duration::from_millis(1));
                }
            }
        }
        Ok(self.batches)
    }

    fn consume(&mut self, fixture: &Fixture) -> Result<()> {
        fixture.validate_console(|text| {
            while let Some(end) = text[self.offset..].find('\n') {
                let end = self.offset + end + 1;
                self.line(text[self.offset..end].trim_end_matches(['\r', '\n']))?;
                self.offset = end;
            }
            Ok(())
        })
    }

    fn line(&mut self, line: &str) -> Result<()> {
        ensure!(
            !line.contains("LINUX_LOAD_FAILED"),
            "Linux reported a workload failure"
        );
        if line.starts_with("LINUX_LOAD_READY") {
            ensure!(
                !self.ready
                    && line
                        == format!(
                            "LINUX_LOAD_READY version={} guest_cpu=0 batch_iterations=8192 \
                             report_batches=256",
                            if self.fences.enabled() { 2 } else { 1 }
                        ),
                "Linux workload readiness protocol mismatch"
            );
            self.ready = true;
        } else if line.starts_with("LINUX_MEMORY_READY") {
            let config = self.memory.context("unexpected Linux memory declaration")?;
            ensure!(
                self.ready
                    && !self.memory_ready
                    && self.batches == 0
                    && line
                        == format!(
                            "LINUX_MEMORY_READY version=1 working_set_bytes={} every_batches={} \
                             chunk_words=8192",
                            config.bytes, config.every
                        ),
                "Linux memory readiness protocol mismatch"
            );
            self.memory_ready = true;
        } else if line.starts_with("LINUX_FENCE_") {
            ensure!(
                self.memory.is_none() || self.memory_ready,
                "fence before memory readiness"
            );
            self.fences
                .line(line, self.ready, self.batches, self.memory)?;
        } else if line.starts_with("LINUX_LOAD_PROGRESS") {
            let mut fields = line.split_whitespace();
            fields.next();
            let batches = field(fields.next(), "batches=")?;
            let checksum = field(fields.next(), "checksum=")?;
            let cpu = field(fields.next(), "guest_cpu=")?;
            self.fences.validate_report(batches)?;
            if let Some(config) = self.memory {
                ensure!(self.memory_ready, "Linux memory progress before readiness");
                let memory_batches = field(fields.next(), "memory_batches=")?;
                let logical_bytes = field(fields.next(), "logical_bytes=")?;
                let checksum = field(fields.next(), "memory_checksum=")?;
                ensure!(
                    (memory_batches, logical_bytes, checksum) == config.expected(batches)?,
                    "Linux memory progress verification failed"
                );
            }
            ensure!(
                fields.next().is_none() && self.ready && cpu == 0,
                "Linux workload identity mismatch"
            );
            ensure!(
                Some(batches) == self.batches.checked_add(256),
                "Linux workload report missing or reordered"
            );
            let iterations = batches
                .checked_mul(8192)
                .context("Linux iteration count overflow")?;
            ensure!(
                checksum == checksum_after(iterations),
                "Linux workload checksum mismatch"
            );
            self.batches = batches;
            self.checksum = checksum;
            self.reports += 1;
        }
        Ok(())
    }

    pub fn finish(
        &mut self,
        fixture: &mut Fixture,
        policy: &str,
        start: u64,
        end: u64,
    ) -> Result<()> {
        self.poll(fixture)?;
        ensure!(
            0 < start
                && (start < end || self.fences.enabled() && start == end)
                && end <= self.batches,
            "Linux produced no observed progress across the sampling window"
        );
        fixture.stop()?;
        // Stop joins the vCPU and flushes its final complete console records.
        self.consume(fixture)?;
        ensure!(
            fixture.vm.snapshot().cpu.running_vcpu_count == 0,
            "Linux vCPU remained active"
        );
        self.fences.finish(policy)?;
        println!(
            "VIRQ_LINUX_SUMMARY policy={policy} vm=1 vcpu=0 host_cpu={} guest_cpu=0 \
             start_batches={start} end_batches={end} final_batches={} checksum={} reports={} \
             batch_iterations=8192 report_batches=256 stopped=1",
            self.host_cpu, self.batches, self.checksum, self.reports
        );
        if let Some(config) = self.memory {
            let (batches, bytes, checksum) = config.expected(self.batches)?;
            println!(
                "VIRQ_LINUX_MEMORY_SUMMARY policy={policy} working_set_bytes={} every_batches={} \
                 final_memory_batches={batches} read_bytes={} write_bytes={} checksum={checksum} \
                 stopped=1",
                config.bytes,
                config.every,
                bytes / 2,
                bytes / 2
            );
        }
        Ok(())
    }
}

fn field(value: Option<&str>, prefix: &str) -> Result<u64> {
    value
        .and_then(|v| v.strip_prefix(prefix))
        .context("Linux workload field missing")?
        .parse()
        .context("Linux workload field is not an unsigned integer")
}

fn checksum_after(mut iterations: u64) -> u64 {
    let (mut multiplier, mut increment, mut checksum) = (6364136223846793005u64, 1u64, 1u64);
    while iterations != 0 {
        if iterations & 1 != 0 {
            checksum = multiplier.wrapping_mul(checksum).wrapping_add(increment);
        }
        increment = multiplier.wrapping_mul(increment).wrapping_add(increment);
        multiplier = multiplier.wrapping_mul(multiplier);
        iterations >>= 1;
    }
    checksum
}
