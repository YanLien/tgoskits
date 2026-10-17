//! Test-only cross-domain counter calibration over immutable reply windows.

use std::{
    time::{Duration, Instant},
    vec::Vec,
};

use aarch64_cpu::asm::barrier::{ISH, SY, dmb, isb};
use anyhow::{Result, ensure};
use axvm::{GuestMemoryPort, GuestPhysAddr};

use super::Fixture;

pub const MAILBOX_SIZE: usize = 48 + 300 * 8;
pub const CLOCK_START: u32 = 33;

pub struct Probe {
    pub phase: &'static str,
    pub sequence: u32,
    pub before: u64,
    pub guest: u64,
    pub after: u64,
}

pub struct Delivery {
    pub submitted: u64,
    pub guest: u64,
    pub observed: u64,
}

pub fn host_ticks() -> u64 {
    let ticks = ax_cpu::timer::physical_counter();
    // Also prevent following request stores from preceding this sample.
    isb(SY);
    ticks
}

pub fn read_word(memory: &GuestMemoryPort, address: GuestPhysAddr) -> Result<u64> {
    // Guest release-publishes the reply/received byte before this acquire
    // barrier. Its payload stays immutable until the host's next request.
    dmb(ISH);
    let mut bytes = [0; 8];
    memory.read_bytes(address, &mut bytes)?;
    Ok(u64::from_le_bytes(bytes))
}

pub fn calibrate(
    fixture: &mut Fixture,
    memory: &GuestMemoryPort,
    address: GuestPhysAddr,
    phase: &'static str,
    first: u32,
) -> Result<Vec<Probe>> {
    let deadline = Instant::now() + Duration::from_secs(30);
    let mut probes = Vec::with_capacity(32);
    for sequence in first..first + 32 {
        let before = host_ticks();
        memory.write_bytes(address + 20, &sequence.to_le_bytes())?;
        loop {
            // Sequence <= 65: only the low byte ever changes. The memory
            // copy API need not provide an atomic multi-byte snapshot.
            let mut ack = [0; 1];
            memory.read_bytes(address + 24, &mut ack)?;
            if u32::from(ack[0]) == sequence {
                break;
            }
            ensure!(Instant::now() < deadline, "clock calibration timed out");
            fixture.flush_console()?;
            std::thread::yield_now();
        }
        let guest = read_word(memory, address + 32)?;
        let after = host_ticks();
        ensure!(before <= after, "host counter moved backwards");
        probes.push(Probe {
            phase,
            sequence,
            before,
            guest,
            after,
        });
    }
    Ok(probes)
}

pub fn offset_bounds(probes: &[Probe]) -> Result<(i128, i128)> {
    let low = probes
        .iter()
        .map(|p| i128::from(p.before) - i128::from(p.guest))
        .max()
        .expect("calibration has probes");
    let high = probes
        .iter()
        .map(|p| i128::from(p.after) - i128::from(p.guest))
        .min()
        .expect("calibration has probes");
    ensure!(low <= high, "clock offset intervals do not intersect");
    Ok((low, high))
}

pub fn validate_delivery(sample: &Delivery, low: i128, high: i128) -> Result<()> {
    ensure!(
        sample.submitted <= sample.observed,
        "host counter moved backwards"
    );
    ensure!(
        i128::from(sample.guest) + high >= i128::from(sample.submitted)
            && i128::from(sample.guest) + low <= i128::from(sample.observed),
        "ISR timestamp is outside its causal host window"
    );
    Ok(())
}
