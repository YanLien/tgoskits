//! Quiescent raw sequences for diagnosing counter visibility and read cadence.

use anyhow::{Result, ensure};
use ax_cpu::timer;

pub struct Series {
    mode: &'static str,
    begin_ticks: u64,
    end_ticks: u64,
    values: [u64; 256],
}

/// The caller is already pinned with IRQs masked and no VM exists.
pub fn capture() -> Result<[Series; 3]> {
    Ok([
        capture_series("physical", timer::physical_counter)?,
        capture_series("virtual", timer::virtual_counter)?,
        capture_series("physical_raw", raw_physical_counter)?,
    ])
}

fn capture_series(mode: &'static str, mut read: impl FnMut() -> u64) -> Result<Series> {
    let begin_ticks = super::clock::host_ticks();
    let values = core::array::from_fn(|_| read());
    let end_ticks = super::clock::host_ticks();
    ensure!(end_ticks >= begin_ticks, "counter series envelope reversed");
    Ok(Series {
        mode,
        begin_ticks,
        end_ticks,
        values,
    })
}

fn raw_physical_counter() -> u64 {
    let value: u64;
    // SAFETY: the EL2-only caller has physical-counter access, and the existing
    // snapshot guard pins this CPU and excludes IRQs. This instruction only
    // reads a register. It deliberately has no ISB and is diagnostic data,
    // never a replacement for the production causal timestamp boundary.
    unsafe {
        core::arch::asm!("mrs {}, CNTPCT_EL0", out(reg) value, options(nostack));
    }
    value
}

impl Series {
    pub fn report(self, policy: &str, point: &str, cpu: usize, counter_hz: u64) {
        println!(
            "VIRQ_COUNTER_SERIES policy={} point={} cpu={} mode={} begin_ticks={} end_ticks={} \
             counter_hz={} values={:?}",
            policy,
            point,
            cpu,
            self.mode,
            self.begin_ticks,
            self.end_ticks,
            counter_hz,
            self.values
        );
    }
}
