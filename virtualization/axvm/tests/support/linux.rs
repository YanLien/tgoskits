//! Consume bounded serial progress from a separate Linux guest; no shared GPA.

use std::time::{Duration, Instant};

use anyhow::{Context, Result, ensure};
use axvm::{SchedulePolicy, VmStatus};

use super::support::Fixture;

#[derive(Default)]
pub struct Progress {
    offset: usize,
    ready: bool,
    batches: u64,
    checksum: u64,
    reports: u64,
}

impl Progress {
    pub fn start(fixture: &mut Fixture) -> Result<Self> {
        fixture.vm.start()?.wait()?;
        fixture.wait(Duration::from_secs(120), |snapshot, _| {
            snapshot.state == VmStatus::Running && snapshot.cpu.running_vcpu_count == 1
        })?;
        let mut progress = Self::default();
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
            "VIRQ_LINUX_BOOT vm=1 vcpu=0 host_cpu=3 guest_cpu=0 batches={}",
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
                        == "LINUX_LOAD_READY version=1 guest_cpu=0 batch_iterations=8192 \
                            report_batches=256",
                "Linux workload readiness protocol mismatch"
            );
            self.ready = true;
        } else if line.starts_with("LINUX_LOAD_PROGRESS") {
            let mut fields = line.split_whitespace();
            fields.next();
            let batches = field(fields.next(), "batches=")?;
            let checksum = field(fields.next(), "checksum=")?;
            let cpu = field(fields.next(), "guest_cpu=")?;
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
            0 < start && start < end && end <= self.batches,
            "Linux produced no observed progress across the sampling window"
        );
        fixture.stop()?;
        // Stop joins the vCPU and flushes its final complete console records.
        self.consume(fixture)?;
        ensure!(
            fixture.vm.snapshot().cpu.running_vcpu_count == 0,
            "Linux vCPU remained active"
        );
        println!(
            "VIRQ_LINUX_SUMMARY policy={policy} vm=1 vcpu=0 host_cpu=3 guest_cpu=0 \
             start_batches={start} end_batches={end} final_batches={} checksum={} reports={} \
             batch_iterations=8192 report_batches=256 stopped=1",
            self.batches, self.checksum, self.reports
        );
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
