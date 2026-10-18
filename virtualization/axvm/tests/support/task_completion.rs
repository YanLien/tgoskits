//! Test-only Guest thread completion over immutable mailbox slots.

use std::time::Instant;

use anyhow::{Context, Result, ensure};
use axvm::{GuestMemoryPort, GuestPhysAddr, VmStatus};

use super::{Fixture, clock};

const ROUNDS: u32 = 4096;
const EXPECTED_CHECKSUM: u64 = 1_853_662_840;

#[derive(Clone, Copy)]
pub struct Config {
    relative_deadline_ns: u64,
    wait_mode: &'static str,
    rounds: u32,
}

impl Config {
    pub fn from_resource(resource: &toml::Value) -> Result<Option<Self>> {
        let enabled = resource
            .get("task_enabled")
            .and_then(toml::Value::as_bool)
            .context("missing Guest task mode")?;
        if !enabled {
            return Ok(None);
        }
        let wait_mode = match resource.get("task_wait").and_then(toml::Value::as_str) {
            Some("spin") => "spin",
            Some("blocked") => "blocked",
            _ => anyhow::bail!("missing or invalid Guest task wait mode"),
        };
        let deadline = resource
            .get("task_deadline_ns")
            .and_then(toml::Value::as_integer)
            .context("missing Guest task relative deadline")?;
        let deadline = u64::try_from(deadline)?;
        let rounds = resource
            .get("task_rounds")
            .and_then(toml::Value::as_integer)
            .unwrap_or(i64::from(ROUNDS));
        let rounds = u32::try_from(rounds)?;
        ensure!(
            (4096..=1048576).contains(&rounds),
            "invalid Guest workload rounds"
        );
        ensure!(
            (1_000..=1_000_000_000).contains(&deadline),
            "invalid task deadline"
        );
        Ok(Some(Self {
            relative_deadline_ns: deadline,
            wait_mode,
            rounds,
        }))
    }

    pub fn announce(self) {
        println!(
            "VIRQ_TASK_CONFIG protocol=1 rounds={} relative_deadline_ns={} wait_mode={}",
            self.rounds, self.relative_deadline_ns, self.wait_mode
        );
    }

    pub fn is_blocked(self) -> bool {
        self.wait_mode == "blocked"
    }

    pub fn rounds(self) -> u32 {
        self.rounds
    }
}

pub struct Sample {
    pub start: u64,
    pub end: u64,
    pub checksum: u64,
    pub observed: u64,
}

pub fn verify_protocol(
    memory: &GuestMemoryPort,
    address: GuestPhysAddr,
    samples: u32,
) -> Result<()> {
    let header = clock::read_word(memory, address + 48 + samples as usize * 16)?;
    ensure!(
        header == 1u64 << 32,
        "Guest task protocol or initial completion is invalid"
    );
    Ok(())
}

pub fn observe(
    fixture: &mut Fixture,
    memory: &GuestMemoryPort,
    address: GuestPhysAddr,
    samples: u32,
    count: u32,
    deadline: Instant,
) -> Result<Sample> {
    let publication = address + 48 + samples as usize * 16;
    loop {
        let mut completed = [0; 1];
        memory.read_bytes(publication, &mut completed)?;
        // Only one task is outstanding, so the preceding low byte differs
        // even across count=256. Each task slot is written once and retained.
        if completed[0] == count as u8 {
            break;
        }
        ensure!(
            fixture.vm.snapshot().state == VmStatus::Running,
            "Guest stopped before task completion"
        );
        ensure!(Instant::now() < deadline, "Guest task completion timed out");
        fixture.flush_console()?;
        std::thread::yield_now();
    }
    // read_word's acquire barrier follows the Guest release publication;
    // the arrays remain immutable until VM shutdown, including error cleanup.
    let payload = address + 56 + samples as usize * 16 + (count as usize - 1) * 8;
    let sample = Sample {
        start: clock::read_word(memory, payload)?,
        end: clock::read_word(memory, payload + samples as usize * 8)?,
        checksum: clock::read_word(memory, payload + samples as usize * 16)?,
        observed: clock::host_ticks(),
    };
    ensure!(
        sample.checksum == EXPECTED_CHECKSUM,
        "Guest task checksum mismatch"
    );
    Ok(sample)
}

pub fn validate(sample: &Sample, delivery: &clock::Delivery, low: i128, high: i128) -> Result<()> {
    ensure!(
        delivery.guest_end <= sample.start && sample.start <= sample.end,
        "Guest task timestamps are not ordered after ISR end"
    );
    ensure!(
        delivery.observed <= sample.observed
            && i128::from(sample.end) + low <= i128::from(sample.observed)
            && i128::from(sample.start) + high >= i128::from(delivery.submitted),
        "Guest task timestamp violates its causal Host window"
    );
    Ok(())
}
