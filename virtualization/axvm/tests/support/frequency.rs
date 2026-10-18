//! Quiescent, per-CPU delivered-cycle snapshots; never used while VMs exist.

use anyhow::{Context, Result, ensure};
use ax_cpu::{
    interrupt,
    pmu::{EventConfig, Pmu},
};
use ax_std::os::arceos::{
    api::task::{AxCpuMask, ax_set_current_affinity},
    modules::ax_hal,
};

pub struct Snapshot {
    policy: &'static str,
    point: &'static str,
    cpu: usize,
    midr: u64,
    version: u8,
    ticks: [u64; 4],
    cycles: [u64; 2],
    counter_hz: u64,
    counter_series: [super::counter::Series; 3],
}

/// Called only immediately before VM creation or after synchronous retirement.
pub fn capture_group(
    policy: &'static str,
    point: &'static str,
    snapshots: &mut std::vec::Vec<Snapshot>,
) -> Result<()> {
    let result = (|| {
        for cpu in 0..ax_hal::cpu_num() {
            pin_to(cpu)?;
            snapshots.push(capture(policy, point, cpu)?);
        }
        Ok(())
    })();
    // The measurement controller owns CPU0 affinity at both call sites. Restore
    // it even when another CPU cannot provide the required observation.
    pin_to(0).context("restore measurement controller affinity")?;
    result
}

fn pin_to(cpu: usize) -> Result<()> {
    ensure!(ax_hal::irq::is_cpu_online(cpu), "frequency CPU is offline");
    ax_set_current_affinity(AxCpuMask::one_shot(cpu)).context("pin frequency observer")?;
    for _ in 0..256 {
        if ax_hal::percpu::this_cpu_id() == cpu {
            return Ok(());
        }
        std::thread::yield_now();
    }
    anyhow::bail!("frequency observer affinity did not settle on CPU{cpu}")
}

fn capture(policy: &'static str, point: &'static str, cpu: usize) -> Result<Snapshot> {
    let _irqs = IrqGuard::new();
    ensure!(
        ax_hal::percpu::this_cpu_id() == cpu,
        "frequency observer migrated"
    );
    let counter_hz = ax_cpu::timer::counter_frequency();
    let duration = counter_hz / 500;
    ensure!(duration > 0, "frequency reference clock is unavailable");
    ensure!(
        ax_cpu::registers::current_exception_level() == 2,
        "counter observation requires the actual EL2 host"
    );
    // The same pinned, IRQ-excluded scope owns these read-only observations.
    let counter_series = super::counter::capture()?;
    // SAFETY: this optional test feature has no perf owner and both call sites
    // exclude every VM. Affinity has settled on this CPU; IRQs remain masked
    // until after the PMU session drops. No external debug PMU user is admitted.
    let mut pmu = unsafe { Pmu::current() }.context("probe required frequency PMU")?;
    let info = pmu.info();
    // SAFETY: all local PMU users have been withdrawn as above. The callback
    // performs bounded arithmetic and register reads only, never schedules or
    // enables IRQs, and receives no reconfiguration capability.
    let (ticks, cycles) = unsafe {
        pmu.with_temporary_cycle_counter(
            EventConfig {
                event: 0x11,
                exclude_user: true,
                exclude_kernel: true,
                include_hypervisor: true,
            },
            |cycle| {
                let t0 = super::clock::host_ticks();
                let c0 = cycle.read();
                let t1 = super::clock::host_ticks();
                let mut work = 1u64;
                while super::clock::host_ticks().wrapping_sub(t1) < duration {
                    work =
                        core::hint::black_box(work.wrapping_mul(1664525).wrapping_add(1013904223));
                }
                core::hint::black_box(work);
                let t2 = super::clock::host_ticks();
                let c1 = cycle.read();
                let t3 = super::clock::host_ticks();
                ([t0, t1, t2, t3], [c0, c1])
            },
        )
    }
    .context("borrow required idle PMU for frequency observation")?;
    ensure!(
        ax_hal::percpu::this_cpu_id() == cpu,
        "frequency observer migrated"
    );
    ensure!(
        ticks[0] > 0
            && ticks.windows(2).all(|pair| pair[0] <= pair[1])
            && ticks[2] > ticks[1]
            && ticks[2] - ticks[1] >= duration,
        "frequency reference clock reversed or window was too short"
    );
    ensure!(
        cycles[1] > cycles[0],
        "frequency cycle counter did not advance"
    );
    Ok(Snapshot {
        policy,
        point,
        cpu,
        midr: info.midr,
        version: info.version,
        ticks,
        cycles,
        counter_hz,
        counter_series,
    })
}

impl Snapshot {
    pub fn report(self) {
        println!(
            "VIRQ_FREQUENCY_SAMPLE policy={} point={} cpu={} midr={} pmuver={} t0={} t1={} t2={} \
             t3={} c0={} c1={} counter_hz={}",
            self.policy,
            self.point,
            self.cpu,
            self.midr,
            self.version,
            self.ticks[0],
            self.ticks[1],
            self.ticks[2],
            self.ticks[3],
            self.cycles[0],
            self.cycles[1],
            self.counter_hz
        );
        for series in self.counter_series {
            series.report(self.policy, self.point, self.cpu, self.counter_hz);
        }
    }
}

struct IrqGuard(bool);

impl IrqGuard {
    fn new() -> Self {
        let enabled = interrupt::irqs_enabled();
        interrupt::disable_irqs();
        Self(enabled)
    }
}

impl Drop for IrqGuard {
    fn drop(&mut self) {
        if self.0 {
            interrupt::enable_irqs();
        }
    }
}
