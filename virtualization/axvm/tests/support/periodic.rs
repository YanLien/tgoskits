//! Fixed logical arrivals, serialized ISR admission, and immutable batch drain.

use std::{time::Duration, vec::Vec};

use anyhow::{Context, Result, ensure};
use axvm::{GuestMemoryPort, GuestPhysAddr, VmStatus};

use super::{Fixture, clock, task_completion};

#[derive(Clone, Copy)]
pub struct Config {
    ticks: u64,
    rounds: u32,
    samples: u32,
}

impl Config {
    pub fn from_resource(
        resource: &toml::Value,
        task: Option<task_completion::Config>,
        samples: u32,
    ) -> Result<Option<Self>> {
        let period = resource
            .get("period_us")
            .and_then(toml::Value::as_integer)
            .context("missing release period")?;
        if period == 0 {
            ensure!(
                task.is_none_or(|config| config.rounds() == 4096),
                "legacy workload changed"
            );
            return Ok(None);
        }
        let task = task.context("periodic release needs tasks")?;
        ensure!(
            (100..=1000000).contains(&period) && task.is_blocked(),
            "invalid periodic release mode"
        );
        let frequency = ax_cpu::timer::counter_frequency();
        let ticks = frequency
            .checked_mul(u64::try_from(period)?)
            .context("release period overflow")?
            / 1_000_000;
        ensure!(ticks != 0, "release period below counter resolution");
        let rounds = task.rounds();
        println!(
            "VIRQ_PERIODIC_CONFIG version=1 period_ns={} period_ticks={ticks} rounds={rounds} \
             jobs={samples} frequency_hz={frequency} deadline_origin=scheduled_release",
            period * 1000
        );
        Ok(Some(Self {
            ticks,
            rounds,
            samples,
        }))
    }

    pub fn verify(self, memory: &GuestMemoryPort, address: GuestPhysAddr) -> Result<()> {
        let header = clock::read_word(memory, address + 56 + self.samples as usize * 40)?;
        ensure!(
            header == (u64::from(self.rounds) << 32 | 1),
            "periodic Guest extension mismatch"
        );
        Ok(())
    }

    pub fn schedule(self) -> Result<Schedule> {
        Ok(Schedule {
            config: self,
            epoch: clock::host_ticks()
                .checked_add(self.ticks)
                .context("release epoch overflow")?,
            releases: Vec::with_capacity(self.samples as usize),
        })
    }

    pub fn drain(
        self,
        fixture: &mut Fixture,
        memory: &GuestMemoryPort,
        address: GuestPhysAddr,
        policy: &str,
    ) -> Result<Vec<task_completion::Sample>> {
        let marker = format!("SOFTWARE VIRQ TASKS_DRAINED samples={}", self.samples);
        fixture.wait(Duration::from_secs(30), |snapshot, output| {
            snapshot.state == VmStatus::Running
                && output.split_inclusive('\n').any(|line| {
                    line.ends_with('\n') && line.trim_end_matches(['\r', '\n']) == marker
                })
        })?;
        // The final serial marker follows all Guest publications. No task or
        // ISR slot changes after this point, including across a low-byte wrap.
        let header = clock::read_word(memory, address + 48 + self.samples as usize * 16)?;
        ensure!(
            header == (u64::from(self.samples) | 1u64 << 32),
            "periodic drain count mismatch"
        );
        let observed = clock::host_ticks();
        let mut samples: Vec<task_completion::Sample> = Vec::with_capacity(self.samples as usize);
        for index in 0..self.samples as usize {
            let payload = address + 56 + self.samples as usize * 16 + index * 8;
            let sample = task_completion::Sample {
                start: clock::read_word(memory, payload)?,
                end: clock::read_word(memory, payload + self.samples as usize * 8)?,
                checksum: clock::read_word(memory, payload + self.samples as usize * 16)?,
                observed,
            };
            ensure!(
                sample.checksum == u64::from(expected(self.rounds)),
                "periodic task result mismatch"
            );
            if let Some(previous) = samples.last() {
                ensure!(
                    previous.end <= sample.start,
                    "periodic tasks overlap or reorder"
                );
            }
            let backlog = address + 64 + self.samples as usize * 40 + index * 8;
            let isr = clock::read_word(memory, backlog)?;
            let task = clock::read_word(memory, backlog + self.samples as usize * 8)?;
            ensure!(
                (1..=u64::from(self.samples)).contains(&isr)
                    && (1..=u64::from(self.samples)).contains(&task),
                "periodic backlog out of range"
            );
            println!(
                "VIRQ_PERIODIC_BACKLOG policy={policy} sample={} isr_outstanding={isr} \
                 task_outstanding={task}",
                index + 1
            );
            samples.push(sample);
        }
        println!(
            "VIRQ_PERIODIC_DRAIN policy={policy} jobs={} completed={} observed_ticks={observed} \
             ready=1",
            self.samples, self.samples
        );
        Ok(samples)
    }
}

pub struct Schedule {
    config: Config,
    epoch: u64,
    releases: Vec<(u64, u64, u64)>,
}

impl Schedule {
    pub fn wait(&self, count: u32) -> Result<u64> {
        let due = self
            .epoch
            .checked_add(
                u64::from(count - 1)
                    .checked_mul(self.config.ticks)
                    .context("release grid overflow")?,
            )
            .context("release deadline overflow")?;
        loop {
            let now = clock::host_ticks();
            if now >= due {
                return Ok(due);
            }
            let ns = u128::from(due - now) * 1_000_000_000
                / u128::from(ax_cpu::timer::counter_frequency());
            std::thread::sleep(Duration::from_nanos(u64::try_from(ns)?));
        }
    }

    pub fn record(&mut self, due: u64, submitted: u64, count: u32) {
        let arrived =
            ((submitted - self.epoch) / self.config.ticks + 1).min(u64::from(self.config.samples));
        self.releases
            .push((due, submitted, arrived - u64::from(count)));
    }

    pub fn report(self, policy: &str) {
        for (index, (due, submitted, backlog)) in self.releases.iter().enumerate() {
            println!(
                "VIRQ_PERIODIC_RELEASE policy={policy} sample={} scheduled_ticks={due} \
                 submitted_ticks={submitted} host_due_backlog={backlog}",
                index + 1
            );
        }
    }
}

fn expected(mut rounds: u32) -> u32 {
    let (mut value, mut multiplier, mut increment) = (0x12345678u32, 1664525u32, 1013904223u32);
    while rounds != 0 {
        if rounds & 1 != 0 {
            value = value.wrapping_mul(multiplier).wrapping_add(increment);
        }
        increment = increment.wrapping_mul(multiplier.wrapping_add(1));
        multiplier = multiplier.wrapping_mul(multiplier);
        rounds >>= 1;
    }
    value
}
