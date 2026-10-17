//! Targeted interrupt delivery and host policy across real VM run generations.

#![cfg_attr(target_os = "none", no_std)]
#![no_main]

use ax_runtime as _;
use ax_std as _;

#[path = "support/clock.rs"]
mod clock;
mod support;

use std::{
    time::{Duration, Instant},
    vec::Vec,
};

use anyhow::{Context, Result, ensure};
use axvm::{GuestMemoryPort, GuestPhysAddr, RtPriority, SchedulePolicy, VmStatus};
use support::Fixture;

const SAMPLES: u32 = 300;
const VECTOR: u32 = 48;

#[axtest::tests]
mod tests {
    #[test]
    fn targeted_interrupts_and_host_policy_survive_reset() -> axtest::AxTestResult {
        super::support::case(super::run())
    }
}

fn run() -> Result<()> {
    let resource: toml::Value =
        toml::from_str(&std::fs::read_to_string("/tests/vcpu-runtime.toml")?)?;
    let capture = resource
        .get("probe_capture")
        .and_then(toml::Value::as_bool)
        .context("missing probe capture state")?;
    #[cfg(not(feature = "probe-capture"))]
    ensure!(!capture, "probe capture requested without compiled support");
    #[cfg(feature = "probe-capture")]
    if capture {
        axvm::diagnostics::initialize(ax_std::os::arceos::task::sched::cpu_topology_len()?)?;
    }
    println!(
        "VIRQ_PROBE_PROFILE compiled={} enabled={}",
        usize::from(cfg!(feature = "probe-capture")),
        usize::from(capture)
    );
    let entry = resource
        .get("entry")
        .and_then(toml::Value::as_integer)
        .context("test resources have no guest entry")?;
    let entry = usize::try_from(entry)?;
    let mailbox = resource
        .get("mailbox")
        .and_then(toml::Value::as_integer)
        .context("test resources have no mailbox address")?;
    let mailbox = usize::try_from(mailbox)?;
    ensure!(
        (0x4000_0000..=0x4800_0000 - clock::MAILBOX_SIZE).contains(&mailbox)
            && mailbox.is_multiple_of(8),
        "mailbox is outside aligned guest RAM"
    );
    let fifo = SchedulePolicy::fifo(RtPriority::new(80).context("valid FIFO priority")?);
    // Both policies, CPU_ON, reset, injection and teardown share one host boot.
    for policy in [SchedulePolicy::default(), fifo] {
        support::with_vm("/guest/builtin/configs/vm-2.toml", policy, |fixture| {
            ensure!(
                fixture.vm.snapshot().description.bsp_entry.as_usize() == entry,
                "guest entry disagrees with the prepared ELF"
            );
            exercise(fixture, GuestPhysAddr::from(mailbox), policy)
        })?;
    }
    #[cfg(feature = "probe-capture")]
    if capture {
        let snapshot = axvm::diagnostics::finish()?;
        ensure!(
            snapshot.dropped == 0 && snapshot.incomplete == 0,
            "probe capture lost records"
        );
        for kind in [
            axvm::diagnostics::EventKind::Binding,
            axvm::diagnostics::EventKind::ReadyEnqueue,
            axvm::diagnostics::EventKind::Running,
        ] {
            ensure!(
                snapshot.events.iter().any(|e| e.kind == kind),
                "probe capture missing {kind:?}"
            );
        }
        ensure!(
            snapshot
                .events
                .iter()
                .filter(|e| e.kind == axvm::diagnostics::EventKind::IrqKick)
                .count()
                >= 600,
            "probe capture missing interrupt publications"
        );
        for event in &snapshot.events {
            println!(
                "VIRQ_RUNTIME cpu={} sequence={} ticks={} kind={:?} thread={} value0={} value1={}",
                event.cpu,
                event.sequence,
                event.ticks,
                event.kind,
                event.thread,
                event.value0,
                event.value1
            );
        }
        println!(
            "VIRQ_RUNTIME_SUMMARY records={} dropped={} incomplete={}",
            snapshot.events.len(),
            snapshot.dropped,
            snapshot.incomplete
        );
    }
    Ok(())
}

fn read_mailbox(memory: &GuestMemoryPort, address: GuestPhysAddr) -> Result<[u32; 5]> {
    let mut bytes = [0; 20];
    memory.read_bytes(address, &mut bytes)?;
    Ok(core::array::from_fn(|index| {
        u32::from_le_bytes(bytes[index * 4..index * 4 + 4].try_into().unwrap())
    }))
}

fn wait_mailbox(
    fixture: &mut Fixture,
    memory: &GuestMemoryPort,
    address: GuestPhysAddr,
    deadline: Instant,
    mut ready: impl FnMut(&[u32; 5]) -> bool,
) -> Result<[u32; 5]> {
    loop {
        fixture.flush_console()?;
        ensure!(
            fixture.vm.snapshot().state == VmStatus::Running,
            "guest stopped before acknowledgement"
        );
        let state = read_mailbox(memory, address)?;
        if ready(&state) {
            return Ok(state);
        }
        ensure!(Instant::now() < deadline, "mailbox timed out: {state:?}");
        std::thread::sleep(Duration::from_millis(1));
    }
}

fn exercise(fixture: &mut Fixture, address: GuestPhysAddr, policy: SchedulePolicy) -> Result<()> {
    let old_run = fixture.vm.start()?.wait()?;
    let old_memory = fixture.vm.guest_memory(old_run)?;
    let old_interrupt = fixture.vm.interrupt_port(old_run, 1, VECTOR)?;
    wait_ready(fixture)?;
    wait_mailbox(
        fixture,
        &old_memory,
        address,
        Instant::now() + Duration::from_secs(30),
        |state| state[0] == 1 && state[1] == 1 && state[3] != 0,
    )?;
    fixture.check_policy(policy, 2)?;

    let run = fixture
        .vm
        .reset()?
        .wait()
        .context("reset into a fresh run")?;
    ensure!(run != old_run, "reset reused the previous run");
    ensure!(
        old_memory.read_bytes(address, &mut [0; 4]).is_err(),
        "retired memory port stayed open"
    );
    ensure!(
        old_interrupt.pulse().is_err(),
        "retired interrupt port stayed open"
    );
    let memory = fixture.vm.guest_memory(run)?;
    let interrupt = fixture.vm.interrupt_port(run, 1, VECTOR)?;
    // RAM can retain the preceding run's mailbox until guest startup clears
    // BSS. The new serial backend proves this run reached main before polling.
    wait_ready(fixture)?;
    let deadline = Instant::now() + Duration::from_secs(30);
    // Zephyr's SMP startup may still deliver a scheduler IPI after both ready
    // stores. Establish an idle boundary before the first pulse; the captured
    // count then stays fixed for the complete 300-delivery interval.
    let mut parks = None;
    let mut quiet_since = Instant::now();
    let initial = wait_mailbox(fixture, &memory, address, deadline, |state| {
        if parks != Some(state[3]) {
            parks = Some(state[3]);
            quiet_since = Instant::now();
        }
        state[2] != 0
            || (state[0] == 1
                && state[1] == 1
                && state[3] != 0
                && quiet_since.elapsed() >= Duration::from_millis(50))
    })?;
    fixture.check_policy(policy, 2)?;
    ensure!(initial[2] == 0, "guest received an unrequested interrupt");
    let frequency = clock::read_word(&memory, address + 40)?;
    ensure!(
        frequency != 0 && frequency == ax_cpu::timer::counter_frequency(),
        "host and guest counter frequencies disagree"
    );
    let mut probes = clock::calibrate(fixture, &memory, address, "before", 1)?;
    memory.write_bytes(address + 20, &clock::CLOCK_START.to_le_bytes())?;
    let mut timings = Vec::with_capacity(SAMPLES as usize);
    for count in 1..=SAMPLES {
        let submitted = Instant::now();
        // Pending bits coalesce edges: keep exactly one unacknowledged pulse.
        let submitted_ticks = clock::host_ticks();
        interrupt.pulse()?;
        let pulse_ns = submitted.elapsed().as_nanos();
        let state = wait_mailbox(fixture, &memory, address, deadline, |state| {
            state[2] >= count
        })?;
        let ack_observed_ns = submitted.elapsed().as_nanos();
        let observed_ticks = clock::host_ticks();
        let guest_ticks = clock::read_word(&memory, address + 48 + (count as usize - 1) * 8)?;
        timings.push((
            pulse_ns,
            ack_observed_ns,
            clock::Delivery {
                submitted: submitted_ticks,
                guest: guest_ticks,
                observed: observed_ticks,
            },
        ));
        ensure!(state[2] == count, "duplicate interrupt: {state:?}");
        ensure!(
            state[3] == initial[3],
            "non-target vCPU left suspend: {state:?}"
        );
    }
    probes.extend(clock::calibrate(fixture, &memory, address, "after", 34)?);
    let (offset_low, offset_high) = clock::offset_bounds(&probes)?;
    for (_, _, stamp) in &timings {
        clock::validate_delivery(stamp, offset_low, offset_high)?;
    }
    // Both intervals use the host clock. Confirmation includes mailbox polling
    // and scheduling; it is not a guest ISR timestamp or a physical IRQ latency.
    // Emit only after sampling so serial output does not enter these intervals.
    let policy_name = match policy {
        SchedulePolicy::Fifo { .. } => "fifo80",
        _ => "fair",
    };
    for probe in &probes {
        println!(
            "VIRQ_CLOCK_SAMPLE policy={policy_name} phase={} sequence={} host_before={} \
             guest_ticks={} host_after={} frequency_hz={frequency}",
            probe.phase, probe.sequence, probe.before, probe.guest, probe.after
        );
    }
    for (index, (pulse_ns, ack_observed_ns, stamp)) in timings.iter().enumerate() {
        println!(
            "VIRQ_HOST_SAMPLE policy={policy_name} sample={} pulse_ns={pulse_ns} \
             ack_observed_ns={ack_observed_ns}",
            index + 1
        );
        println!(
            "VIRQ_ISR_SAMPLE policy={policy_name} sample={} submit_ticks={} guest_ticks={} \
             observed_ticks={} frequency_hz={frequency}",
            index + 1,
            stamp.submitted,
            stamp.guest,
            stamp.observed
        );
    }
    println!("VIRQ_INJECT_COMPLETE vm=2 vcpu=1 vector=48 samples=300 errors=0");
    println!("E1_COUNTERS idle_vcpu_returns=0 acknowledgements=300 policy={policy:?}");
    memory.write_bytes(address + 16, &1u32.to_le_bytes())?;
    fixture.wait(Duration::from_secs(30), |snapshot, output| {
        snapshot.state == VmStatus::Stopped
            && output.contains("SOFTWARE VIRQ COMPLETE streams=1 samples_each=300 total=300")
    })?;
    fixture.validate_console(|output| {
        ensure!(
            output.contains("SOFTWARE VIRQ COMPLETE streams=1 samples_each=300 total=300"),
            "guest omitted completion"
        );
        Ok(())
    })?;
    fixture.check_policy(policy, 0)?;
    ensure!(
        interrupt.pulse().is_err(),
        "stopped run retained its interrupt port"
    );
    fixture.stop()
}

fn wait_ready(fixture: &mut Fixture) -> Result<()> {
    // CPU_ON may enter before the owner publishes its participant snapshot.
    fixture.wait(Duration::from_secs(30), |snapshot, output| {
        snapshot.cpu.running_vcpu_count == 2
            && output.contains("SOFTWARE VIRQ READY suspend vector=48 samples=300")
    })
}
