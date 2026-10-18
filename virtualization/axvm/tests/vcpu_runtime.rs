//! Targeted interrupt delivery and host policy across real VM run generations.

#![cfg_attr(target_os = "none", no_std)]
#![no_main]

use ax_runtime as _;
use ax_std as _;

#[path = "support/clock.rs"]
mod clock;
#[path = "support/contention.rs"]
mod contention;
#[cfg(feature = "axtest-frequency")]
#[path = "support/counter.rs"]
mod counter;
#[cfg(feature = "axtest-frequency")]
#[path = "support/frequency.rs"]
mod frequency;
#[path = "support/inversion.rs"]
mod inversion;
#[path = "support/irq_pressure.rs"]
mod irq_pressure;
#[path = "support/linux.rs"]
mod linux;
#[path = "support/periodic.rs"]
mod periodic;
#[path = "support/physical.rs"]
mod physical;
#[path = "support/platform.rs"]
mod platform;
#[path = "support/rtc_spi.rs"]
mod rtc_spi;
mod support;
#[path = "support/task_completion.rs"]
mod task_completion;
#[cfg(feature = "axtest-thermal")]
#[path = "support/thermal.rs"]
mod thermal;

use std::{
    time::{Duration, Instant},
    vec::Vec,
};

use anyhow::{Context, Result, ensure};
use axvm::{GuestMemoryPort, GuestPhysAddr, RtPriority, SchedulePolicy, VmStatus};
use support::Fixture;

const MAX_SAMPLES: u32 = 1000;
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
    let context = resource
        .get("irq_context")
        .and_then(toml::Value::as_str)
        .context("missing IRQ execution context")?;
    ensure!(
        matches!(context, "current_el" | "guest_running"),
        "invalid IRQ context"
    );
    let guest_running = context == "guest_running";
    run_measurement(&resource, guest_running)
}

fn run_measurement(resource: &toml::Value, guest_running: bool) -> Result<()> {
    let samples = resource
        .get("samples")
        .and_then(toml::Value::as_integer)
        .context("missing sample count")?;
    let samples = u32::try_from(samples).context("invalid sample count")?;
    ensure!(
        (1..=MAX_SAMPLES).contains(&samples),
        "sample count out of range"
    );
    println!("VIRQ_MEASUREMENT samples_per_policy={samples}");
    let task = task_completion::Config::from_resource(resource)?;
    if let Some(config) = task {
        config.announce();
    }
    let period = periodic::Config::from_resource(resource, task, samples)?;
    let mailbox_size = if period.is_some() {
        64 + samples as usize * 56
    } else if task.is_some() {
        56 + samples as usize * 40
    } else {
        48 + samples as usize * 16
    };
    // The FIFO guest spins during calibration; keep its controller off CPU1.
    use ax_std::os::arceos::api::task::{AxCpuMask, ax_set_current_affinity};
    ax_set_current_affinity(AxCpuMask::one_shot(0)).context("pin measurement controller")?;
    println!("VIRQ_CONTROLLER cpu=0");

    let recording = resource
        .get("recording")
        .and_then(toml::Value::as_str)
        .context("missing recording mode")?;
    ensure!(matches!(recording, "on" | "off"), "invalid recording mode");
    println!("VIRQ_RECORDING mode={recording} scope=recorder_operations version=2");
    println!(
        "VIRQ_STAGE_CONFIG version=1 key=cpu_intid_entry_ticks dispatch=host_route \
         timer_sync=lower_el_only"
    );
    axvm::diagnostics::initialize(ax_std::os::arceos::task::sched::cpu_topology_len()?)?;
    if recording == "off" {
        // The same buffers and hooks exist in both modes. Close admission before
        // starting any VM; retain all clock, IRQ and task correctness checks.
        let empty = axvm::diagnostics::finish()?;
        ensure!(
            empty.events.is_empty() && empty.dropped == 0 && empty.incomplete == 0,
            "recording closed after an unexpected producer"
        );
    }
    ensure!(
        ax_std::os::arceos::task::diagnostics::install_ready_trace_hook(rejected_ready_observer)
            .is_err(),
        "ready observer replacement was accepted"
    );
    let service_mode = resource
        .get("irq_service")
        .and_then(toml::Value::as_str)
        .context("missing IRQ service experiment mode")?;
    let service_rounds = u64::try_from(
        resource
            .get("irq_service_rounds")
            .and_then(toml::Value::as_integer)
            .context("missing IRQ dispatch rounds")?,
    )?;
    let service_window_us = u64::try_from(
        resource
            .get("irq_service_window_us")
            .and_then(toml::Value::as_integer)
            .context("missing IRQ dispatch window")?,
    )?;
    let inversion_witness = resource
        .get("inversion_witness")
        .and_then(toml::Value::as_bool)
        .context("missing inversion witness selection")?;
    axvm::diagnostics::irq_service::configure(service_mode, service_rounds, service_window_us)?;
    ensure!(
        axvm::diagnostics::irq_service::configure(service_mode, service_rounds, service_window_us)
            .is_err(),
        "IRQ service mode replacement was accepted"
    );
    let mut envelopes = Vec::with_capacity(128);
    for marker in 0..128 {
        let before = clock::host_ticks();
        axvm::diagnostics::mark(marker);
        let after = clock::host_ticks();
        ensure!(before <= after, "probe envelope counter moved backwards");
        envelopes.push(after - before);
    }

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
        (0x4000_0000..=0x4800_0000 - mailbox_size).contains(&mailbox) && mailbox.is_multiple_of(8),
        "mailbox is outside aligned guest RAM"
    );
    let scenario = resource
        .get("scenario")
        .and_then(toml::Value::as_str)
        .context("test resources have no scenario")?;
    ensure!(
        matches!(
            scenario,
            "baseline"
                | "cpu_same_core"
                | "cpu_continuous"
                | "memory_cross_core"
                | "linux_cpu"
                | "linux_memory"
        ),
        "unsupported load scenario"
    );
    println!("VIRQ_SCENARIO name={scenario}");
    let workload = if scenario == "memory_cross_core" {
        let bytes = resource
            .get("memory_bytes")
            .and_then(toml::Value::as_integer)
            .context("memory scenario has no working set")?;
        let bytes = usize::try_from(bytes).context("memory working set is out of range")?;
        let cpu = if guest_running { 3 } else { 2 };
        println!(
            "VIRQ_MEMORY_CONFIG cpu={cpu} working_set_bytes={bytes} chunk_words=1024 \
             access=volatile_read_modify_write"
        );
        contention::Workload::Memory { bytes, cpu }
    } else {
        contention::Workload::Cpu
    };

    let source_kind = resource
        .get("source")
        .and_then(toml::Value::as_str)
        .context("test resources have no interrupt source")?;
    ensure!(
        matches!(source_kind, "software" | "physical_timer_ppi" | "pl031_spi"),
        "unsupported interrupt source"
    );
    println!("VIRQ_SOURCE kind={source_kind}");
    let explicit_dtb = resource
        .get("explicit_dtb_enabled")
        .and_then(toml::Value::as_bool)
        .unwrap_or(false);
    println!(
        "VIRQ_GUEST_FIRMWARE source={}",
        if explicit_dtb {
            "explicit_dtb"
        } else {
            "inherited"
        }
    );
    if source_kind == "physical_timer_ppi" {
        let host = platform::TimerPlatform::detect()?;
        let expected_layout = match host {
            platform::TimerPlatform::Qemu => "qemu",
            platform::TimerPlatform::OrangePi5Plus => "rk3588",
        };
        ensure!(
            resource
                .get("guest_gic_layout")
                .and_then(toml::Value::as_str)
                .unwrap_or("qemu")
                == expected_layout,
            "Guest GIC layout does not match the host baseline"
        );
        ensure!(
            host == platform::TimerPlatform::Qemu || explicit_dtb,
            "native timer fixture requires explicit Guest firmware"
        );
        host.report();
    }
    let service_placement = resource
        .get("service_placement")
        .and_then(toml::Value::as_str)
        .context("missing service placement")?;
    ensure!(
        matches!(service_placement, "unrestricted" | "cpu0" | "cpu1" | "cpu2"),
        "unsupported service placement"
    );
    println!("VIRQ_SERVICE_PLACEMENT mode={service_placement}");
    if service_placement != "unrestricted" {
        let cpu = service_placement
            .strip_prefix("cpu")
            .context("invalid service CPU")?
            .parse::<usize>()?;
        axvm::diagnostics::service_placement::configure(cpu)?;
        ensure!(
            axvm::diagnostics::service_placement::configure(cpu).is_err(),
            "service placement replacement was accepted"
        );
    }

    if inversion_witness {
        ensure!(
            scenario == "baseline"
                && source_kind == "physical_timer_ppi"
                && !guest_running
                && service_placement == "cpu0",
            "inversion witness requires baseline current-EL PPI with CPU0 services"
        );
        println!("VIRQ_INVERSION_CONFIG cpu=0 priority=60 duration_ms=50 sample=1");
    }
    if period.is_some() {
        ensure!(
            matches!(scenario, "linux_cpu" | "linux_memory")
                && !guest_running
                && !inversion_witness
                && matches!(source_kind, "pl031_spi" | "physical_timer_ppi")
                && service_placement == "cpu0",
            "periodic fixture requires dual-VM current-EL physical source and CPU0 services"
        );
    }
    let pressure = irq_pressure::Config::from_resource(resource)?;
    if pressure.is_some() {
        ensure!(
            matches!(scenario, "linux_cpu" | "linux_memory")
                && !guest_running
                && !inversion_witness
                && matches!(source_kind, "pl031_spi" | "physical_timer_ppi")
                && service_placement == "cpu0"
                && task.is_some_and(task_completion::Config::is_blocked),
            "SGI pressure requires blocked dual-VM current-EL physical source with CPU0 services"
        );
    }
    let linux_memory = if scenario == "linux_memory" {
        Some(linux::MemoryConfig::from_resource(resource)?)
    } else {
        None
    };
    let linux_fences = resource
        .get("linux_fences_enabled")
        .and_then(toml::Value::as_bool)
        .unwrap_or(false);
    ensure!(
        !linux_fences || matches!(scenario, "linux_cpu" | "linux_memory"),
        "Linux fences require a Linux peer"
    );
    let linux_host_cpu = match resource.get("linux_host_cpu") {
        None => 3,
        Some(value) => usize::try_from(
            value
                .as_integer()
                .context("Linux Host CPU must be an integer")?,
        )
        .context("negative Linux Host CPU")?,
    };
    ensure!(
        matches!(linux_host_cpu, 1 | 3)
            && (linux_host_cpu == 3 || matches!(scenario, "linux_cpu" | "linux_memory")),
        "invalid Linux Host CPU or missing Linux peer"
    );
    if matches!(scenario, "linux_cpu" | "linux_memory") {
        println!(
            "VIRQ_LINUX_FENCE_CONFIG version=1 mode={} clock=monotonic_raw",
            if linux_fences { "serial" } else { "off" }
        );
        ensure!(
            matches!(source_kind, "pl031_spi" | "physical_timer_ppi")
                && !guest_running
                && service_placement == "cpu0",
            "Linux peer requires current-EL physical source and CPU0 services"
        );
        ensure!(
            ax_std::os::arceos::task::sched::cpu_topology_len()? >= 4,
            "Linux measurement requires the four-CPU fixture"
        );
        ensure!(
            linux_host_cpu != 1
                || (resource
                    .get("explicit_dtb_enabled")
                    .and_then(toml::Value::as_bool)
                    == Some(true)
                    && task.is_some_and(task_completion::Config::is_blocked)),
            "Linux CPU1 sharing requires explicit Guest firmware and blocked tasks"
        );
        println!(
            "VIRQ_LINUX_CONFIG vm=1 vcpu=0 host_cpu={linux_host_cpu} guest_cpu=0 workload={} \
             batch_iterations=8192 report_batches=256",
            if linux_memory.is_some() {
                "memory"
            } else {
                "cpu"
            }
        );
    }
    if guest_running {
        ensure!(
            source_kind == "physical_timer_ppi"
                && service_placement == "cpu2"
                && matches!(scenario, "baseline" | "memory_cross_core"),
            "guest-running IRQ context needs baseline or cross-core memory, PPI and CPU2 services"
        );
        println!(
            "VIRQ_GUEST_EXECUTION mode=running target_cpu=1 controller_policy=default \
             service_cpu=2 irq_cpu=1"
        );
    }
    let fifo = SchedulePolicy::fifo(RtPriority::new(80).context("valid FIFO priority")?);
    // Both policies, CPU_ON, reset, injection and teardown share one host boot.
    let mut pressure_reports = Vec::new();
    #[cfg(feature = "axtest-thermal")]
    let mut thermal_samples = Vec::with_capacity(4);
    #[cfg(feature = "axtest-frequency")]
    let mut frequency_samples =
        Vec::with_capacity(4 * ax_std::os::arceos::modules::ax_hal::cpu_num());
    println!(
        "VIRQ_FREQUENCY_CONFIG enabled={} scope=policy_before_create_after_retirement \
         method=pmu_cycle_bracket target_us=2000 cpus={}",
        u8::from(cfg!(feature = "axtest-frequency")),
        ax_std::os::arceos::modules::ax_hal::cpu_num()
    );
    println!(
        "VIRQ_THERMAL_CONFIG enabled={} scope=policy_before_create_after_retirement \
         sensors=soc0_little3",
        u8::from(cfg!(feature = "axtest-thermal"))
    );
    println!(
        "VIRQ_COUNTER_CONFIG enabled={} version=1 reads=256 modes=physical_virtual_raw \
         scope=before_frequency_cycles exception_level=2",
        u8::from(cfg!(feature = "axtest-frequency"))
    );
    for policy in [SchedulePolicy::default(), fifo] {
        let policy_name = match policy {
            SchedulePolicy::Fifo { .. } => "fifo80",
            _ => "fair",
        };
        #[cfg(feature = "axtest-thermal")]
        thermal_samples.push(thermal::Snapshot::capture(policy_name, "before_create")?);
        #[cfg(feature = "axtest-frequency")]
        frequency::capture_group(policy_name, "before_create", &mut frequency_samples)?;
        // Establish affinity before any FIFO guest can monopolize CPU1.
        // Keep this guard outside with_vm so its error cleanup joins the VM first.
        let load = if matches!(
            scenario,
            "cpu_same_core" | "cpu_continuous" | "memory_cross_core"
        ) {
            Some(contention::HostContention::start(workload)?)
        } else {
            None
        };
        if matches!(scenario, "cpu_continuous" | "memory_cross_core") {
            let load = load.as_ref().context("continuous scenario has no load")?;
            load.activate()?;
            println!(
                "VIRQ_LOAD_BOOT_WORK policy={policy_name} batches={}",
                load.batches()
            );
        }
        let mut work_window = None;
        if matches!(scenario, "linux_cpu" | "linux_memory") {
            support::with_vms(
                [
                    ("/guest/builtin/configs/vm-2.toml", policy),
                    (
                        "/guest/builtin/configs/vm-1.toml",
                        SchedulePolicy::default(),
                    ),
                ],
                |fixtures| {
                    let [fixture, peer] = fixtures;
                    let mut progress =
                        linux::Progress::start(peer, linux_memory, linux_fences, linux_host_cpu)?;
                    ensure!(
                        fixture.vm.snapshot().description.bsp_entry.as_usize() == entry,
                        "guest entry disagrees with the prepared ELF"
                    );
                    work_window = Some(exercise(
                        fixture,
                        Measurement {
                            address: GuestPhysAddr::from(mailbox),
                            policy,
                            load: None,
                            source_kind,
                            guest_running,
                            samples,
                            linux: Some((peer, &mut progress)),
                            inversion_witness,
                            task,
                            pressure,
                            period,
                        },
                    )?);
                    Ok(())
                },
            )?;
        } else {
            support::with_vm("/guest/builtin/configs/vm-2.toml", policy, |fixture| {
                ensure!(
                    fixture.vm.snapshot().description.bsp_entry.as_usize() == entry,
                    "guest entry disagrees with the prepared ELF"
                );
                work_window = Some(exercise(
                    fixture,
                    Measurement {
                        address: GuestPhysAddr::from(mailbox),
                        policy,
                        load: load.as_ref(),
                        source_kind,
                        guest_running,
                        samples,
                        linux: None,
                        inversion_witness,
                        task,
                        pressure,
                        period,
                    },
                )?);
                Ok(())
            })?;
        }
        #[cfg(feature = "axtest-thermal")]
        thermal_samples.push(thermal::Snapshot::capture(policy_name, "after_retirement")?);
        #[cfg(feature = "axtest-frequency")]
        frequency::capture_group(policy_name, "after_retirement", &mut frequency_samples)?;
        let outcome = work_window.context("measurement outcome missing")?;
        if let Some(report) = outcome.pressure {
            pressure_reports.push((policy_name, report));
        }
        if let Some(load) = load {
            let (start, end) = outcome.work_window;
            load.finish(start, end, policy_name)?;
        }
    }
    if service_placement != "unrestricted" {
        axvm::diagnostics::service_placement::validate()?;
    }
    let snapshot = axvm::diagnostics::finish()?;
    #[cfg(feature = "axtest-frequency")]
    for sample in frequency_samples {
        sample.report();
    }
    #[cfg(feature = "axtest-thermal")]
    for sample in thermal_samples {
        sample.report();
    }
    println!(
        "VIRQ_TRACE_FROZEN records={} dropped={} incomplete={} vm_groups_retired=2",
        snapshot.events.len(),
        snapshot.dropped,
        snapshot.incomplete
    );
    // All VM groups have joined and capture admission is closed. Exporting the
    // retained pressure records cannot extend either Guest's traced lifetime.
    for (policy, report) in pressure_reports {
        report.emit(policy);
    }
    if snapshot.dropped != 0 || snapshot.incomplete != 0 {
        for cpu in 0..ax_std::os::arceos::modules::ax_hal::cpu_num() {
            let records = snapshot
                .events
                .iter()
                .filter(|event| event.cpu == cpu)
                .count();
            println!("VIRQ_TRACE_OCCUPANCY cpu={cpu} records={records} scope=committed_prefix");
        }
    }
    ensure!(
        snapshot.dropped == 0 && snapshot.incomplete == 0,
        "runtime trace lost records"
    );
    for (index, ticks) in envelopes.iter().enumerate() {
        println!(
            "VIRQ_TRACE_ENVELOPE sample={} ticks={} frequency_hz={}",
            index + 1,
            ticks,
            ax_cpu::timer::counter_frequency()
        );
    }
    if recording == "off" {
        ensure!(
            snapshot.events.is_empty(),
            "disabled recording captured events"
        );
        println!(
            "VIRQ_RECORDING_SUMMARY mode=off records=0 dropped=0 incomplete=0 \
             stage_observations=unavailable"
        );
        return Ok(());
    }
    let physical_count = snapshot
        .events
        .iter()
        .filter(|event| event.kind == axvm::diagnostics::EventKind::HostIrqEntry)
        .count();
    ensure!(
        physical_count
            == if source_kind != "software" {
                samples as usize * 2
            } else {
                0
            },
        "physical IRQ trace expected exactly {} entries for a physical source",
        samples * 2
    );
    if guest_running {
        ensure!(
            snapshot.events.iter().any(|event| event.kind
                == axvm::diagnostics::EventKind::HostIrqEntry
                && event.value1 == 2),
            "guest-running context captured no low-EL physical IRQ"
        );
    }
    let ready_count = snapshot
        .events
        .iter()
        .filter(|event| event.kind == axvm::diagnostics::EventKind::ReadyEnqueue)
        .count();
    ensure!(ready_count > 0, "runtime trace has no ready events");
    println!("VIRQ_READY_SUMMARY records={ready_count}");
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
    println!(
        "VIRQ_RECORDING_SUMMARY mode=on records={} dropped=0 incomplete=0 \
         stage_observations=available",
        snapshot.events.len()
    );
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

struct Measurement<'a> {
    address: GuestPhysAddr,
    policy: SchedulePolicy,
    load: Option<&'a contention::HostContention>,
    source_kind: &'a str,
    guest_running: bool,
    samples: u32,
    linux: Option<(&'a mut Fixture, &'a mut linux::Progress)>,
    inversion_witness: bool,
    task: Option<task_completion::Config>,
    pressure: Option<irq_pressure::Config>,
    period: Option<periodic::Config>,
}

struct MeasurementOutcome {
    work_window: (u64, u64),
    pressure: Option<irq_pressure::RetiredReport>,
}

fn exercise(fixture: &mut Fixture, measurement: Measurement<'_>) -> Result<MeasurementOutcome> {
    let Measurement {
        address,
        policy,
        load,
        source_kind,
        guest_running,
        samples,
        mut linux,
        inversion_witness,
        task,
        pressure,
        period,
    } = measurement;
    report_lifecycle(fixture, "before_start");
    let old_run = fixture.vm.start()?.wait()?;
    let old_memory = fixture.vm.guest_memory(old_run)?;
    let old_interrupt = fixture.vm.interrupt_port(old_run, 1, VECTOR)?;
    wait_ready(fixture, samples, &old_memory)?;
    wait_mailbox(
        fixture,
        &old_memory,
        address,
        Instant::now() + Duration::from_secs(30),
        |state| state[0] == 1 && state[1] == 1 && state[3] != 0,
    )?;
    fixture.check_policy(policy, 2)?;

    report_lifecycle(fixture, "before_reset");

    let run = fixture
        .vm
        .reset()?
        .wait()
        .context("reset into a fresh run")?;
    ensure!(run != old_run, "reset reused the previous run");
    report_lifecycle(fixture, "after_reset");
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
    wait_ready(fixture, samples, &memory)?;
    report_lifecycle(fixture, "ready_after_reset");
    let deadline = Instant::now() + Duration::from_secs(30);
    // Zephyr's SMP startup may still deliver a scheduler IPI after both ready
    // stores. Establish an idle boundary before the first pulse; the captured
    // count then stays fixed for the complete delivery interval.
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
    if task.is_some() {
        task_completion::verify_protocol(&memory, address, samples)?;
        if let Some(config) = period {
            config.verify(&memory, address)?;
        }
    }
    ensure!(
        frequency != 0 && frequency == ax_cpu::timer::counter_frequency(),
        "host and guest counter frequencies disagree"
    );
    let policy_name = match policy {
        SchedulePolicy::Fifo { .. } => "fifo80",
        _ => "fair",
    };
    let mut load_samples = Vec::with_capacity(samples as usize);
    println!("VIRQ_LOAD_STAGE before_calibration policy={policy_name}");
    let mut probes = clock::calibrate(fixture, &memory, address, "before", 1)?;
    println!("VIRQ_LOAD_STAGE after_calibration policy={policy_name}");
    if guest_running {
        memory.write_bytes(address + 28, &1u32.to_le_bytes())?;
        // Publish the mode before the Guest acquire-observes CLOCK_START.
        aarch64_cpu::asm::barrier::dmb(aarch64_cpu::asm::barrier::ISH);
    }
    memory.write_bytes(address + 20, &clock::CLOCK_START.to_le_bytes())?;
    if let Some(load) = load {
        load.activate()?;
    }
    let mut blocker = if inversion_witness {
        Some(inversion::Witness::start()?)
    } else {
        None
    };
    let mut witness_report = None;
    let mut timings = Vec::with_capacity(samples as usize);
    let mut task_samples = Vec::with_capacity(if task.is_some() { samples as usize } else { 0 });
    let mut physical = if source_kind == "physical_timer_ppi" {
        Some(physical::PhysicalTimer::start(
            interrupt.clone(),
            usize::from(guest_running),
        )?)
    } else {
        None
    };
    let mut rtc = if source_kind == "pl031_spi" {
        ensure!(resource_unused_rtc()?, "Guest RTC/counter driver is active");
        Some(rtc_spi::RtcSpi::start(interrupt.clone())?)
    } else {
        None
    };
    let mut rtc_arms = Vec::with_capacity(samples as usize);
    let mut physical_deadlines = Vec::with_capacity(samples as usize);
    let mut linux_samples = Vec::new();
    let pressure = pressure.map(irq_pressure::Pressure::start).transpose()?;
    let linux_start = if let Some((peer, progress)) = linux.as_mut() {
        progress.begin_window(peer)?
    } else {
        0
    };
    let load_start = load.as_ref().map_or(0, |load| load.batches());
    let mut schedule = period.map(periodic::Config::schedule).transpose()?;
    for count in 1..=samples {
        let due = schedule.as_ref().map(|plan| plan.wait(count)).transpose()?;
        let linux_before = if let Some((peer, progress)) = linux.as_mut() {
            progress.poll(peer)?
        } else {
            0
        };
        let submitted = Instant::now();
        // Pending bits coalesce edges: keep exactly one unacknowledged pulse.
        let submitted_ticks = clock::host_ticks();
        if let (Some(plan), Some(due)) = (schedule.as_mut(), due) {
            plan.record(due, submitted_ticks, count);
        }
        let batches_before = load.as_ref().map_or(0, |load| load.batches());
        if let Some(source) = &physical {
            physical_deadlines.push(source.arm(count)?);
        } else if let Some(source) = &rtc {
            rtc_arms.push(source.arm(count)?);
        } else {
            interrupt.pulse()?;
        }
        if count == 1
            && let Some(witness) = &blocker
        {
            witness.activate();
        }
        let pulse_ns = submitted.elapsed().as_nanos();
        let isr_deadline = if period.is_some() {
            Instant::now() + Duration::from_secs(30)
        } else {
            deadline
        };
        let state = wait_mailbox(fixture, &memory, address, isr_deadline, |state| {
            if period.is_some() {
                state[2] == count
            } else {
                state[2] >= count
            }
        })
        .map_err(|error| {
            println!(
                "VIRQ_DELIVERY_FAILURE policy={policy_name} expected_sample={count} \
                 submitted_ticks={submitted_ticks} failed_ticks={} frequency_hz={frequency} \
                 guest_header={:?} guest_task_publication={:?} vm_state={:?} running_vcpus={}",
                clock::host_ticks(),
                read_mailbox(&memory, address),
                task.map(|_| clock::read_word(&memory, address + 48 + samples as usize * 16)),
                fixture.vm.snapshot().state,
                fixture.vm.snapshot().cpu.running_vcpu_count
            );
            if let Some(source) = &rtc {
                source.report_failure();
            }
            if let Some(source) = &pressure {
                source.report_failure();
            }
            error.context(format!(
                "critical acknowledgement policy={policy_name} sample={count}"
            ))
        })?;
        if let Some(source) = &physical {
            source.check_delivered(count)?;
        }
        if let Some(source) = &rtc {
            source.check_delivered(count)?;
        }
        let ack_observed_ns = submitted.elapsed().as_nanos();
        let batches_after = load.as_ref().map_or(0, |load| load.batches());
        let observed_ticks = clock::host_ticks();
        if let Some((peer, progress)) = linux.as_mut() {
            linux_samples.push((linux_before, progress.poll(peer)?));
        }
        load_samples.push((batches_before, batches_after));
        let guest_ticks = clock::read_word(&memory, address + 48 + (count as usize - 1) * 8)?;
        let guest_end_ticks = clock::read_word(
            &memory,
            address + 48 + samples as usize * 8 + (count as usize - 1) * 8,
        )?;
        if task.is_some() && period.is_none() {
            task_samples.push(task_completion::observe(
                fixture, &memory, address, samples, count, deadline,
            )?);
        }
        if count == 1
            && let Some(witness) = blocker.as_mut()
        {
            witness_report = Some(witness.finish()?);
        }
        timings.push((
            pulse_ns,
            ack_observed_ns,
            clock::Delivery {
                submitted: submitted_ticks,
                guest: guest_ticks,
                guest_end: guest_end_ticks,
                observed: observed_ticks,
            },
        ));
        ensure!(state[2] == count, "duplicate interrupt: {state:?}");
        ensure!(
            task.is_some_and(task_completion::Config::is_blocked) || state[3] == initial[3],
            "non-target vCPU left suspend: {state:?}"
        );
    }
    if let Some(config) = period {
        task_samples = config.drain(fixture, &memory, address, policy_name)?;
    }
    // Semaphore scheduling may cause Guest SMP activity on CPU0. Retain the
    // original quiet-core contract for every pre-existing workload mode;
    // blocked tasks report observed background activity without claiming its
    // cause. The Guest ISR still rejects vector48 on any CPU other than CPU1.
    let idle_vcpu_returns = read_mailbox(&memory, address)?[3]
        .checked_sub(initial[3])
        .context("non-target Guest return counter moved backwards")?;
    ensure!(
        task.is_some_and(task_completion::Config::is_blocked) || idle_vcpu_returns == 0,
        "non-target vCPU left suspend after its final acknowledgement"
    );
    let shared_linux = linux
        .as_ref()
        .is_some_and(|(_, progress)| progress.host_cpu() == 1);
    let linux_end = if shared_linux {
        ensure!(
            task_samples.len() == samples as usize,
            "shared-core handoff requires every completed task"
        );
        // After its last task the Guest spins to answer the after probes. Its
        // FIFO owner must park before the normal Linux owner can reply End.
        // Retire physical producers first; SGI pressure still covers End.
        if let Some(source) = physical.take() {
            source.finish(policy_name, samples)?;
        }
        if let Some(source) = rtc.take() {
            source.finish(policy_name, samples)?;
        }
        let last_task_observed = task_samples
            .iter()
            .map(|sample| sample.observed)
            .max()
            .context("shared-core handoff has no completed task")?;
        let pause_requested = clock::host_ticks();
        fixture
            .vm
            .pause()?
            .wait()
            .context("pause after all tasks")?;
        let paused = clock::host_ticks();
        let (peer, progress) = linux.as_mut().context("shared Linux disappeared")?;
        let end = progress.end_window(peer)?;
        progress.finish(peer, policy_name, linux_start, end)?;
        let linux_retired = clock::host_ticks();
        fixture
            .vm
            .resume()?
            .wait()
            .context("resume after Linux End")?;
        let resumed = clock::host_ticks();
        fixture.check_policy(policy, 2)?;
        println!(
            "VIRQ_LINUX_HANDOFF policy={policy_name} protocol=pause_after_tasks host_cpu=1 \
             last_task_observed_ticks={last_task_observed} \
             pause_requested_ticks={pause_requested} paused_ticks={paused} \
             linux_retired_ticks={linux_retired} resumed_ticks={resumed}"
        );
        end
    } else if let Some((peer, progress)) = linux.as_mut() {
        progress.end_window(peer)?
    } else {
        0
    };
    let load_end = load.as_ref().map_or(0, |load| load.batches());
    let pressure = pressure.map(irq_pressure::Pressure::retire).transpose()?;
    probes.extend(clock::calibrate(fixture, &memory, address, "after", 34)?);
    if let Some(source) = physical {
        source.finish(policy_name, samples)?;
    }
    if let Some(source) = rtc {
        source.finish(policy_name, samples)?;
    }
    let (offset_low, offset_high) = clock::offset_bounds(&probes)?;
    for (_, _, stamp) in &timings {
        clock::validate_delivery(stamp, offset_low, offset_high)?;
    }
    if task.is_some() {
        ensure!(
            task_samples.len() == timings.len(),
            "Guest task samples missing"
        );
        for (sample, (_, _, stamp)) in task_samples.iter().zip(&timings) {
            task_completion::validate(sample, stamp, offset_low, offset_high)?;
        }
    }
    if let Some(report) = witness_report {
        let guest_low = i128::from(timings[0].2.guest) + offset_low;
        let guest_high = i128::from(timings[0].2.guest) + offset_high;
        let due = physical_deadlines[0];
        ensure!(
            report.wrong_cpu == 0 && report.start < due && due < report.end,
            "inversion witness did not bracket the physical deadline on CPU0"
        );
        let resource: toml::Value =
            toml::from_str(&std::fs::read_to_string("/tests/vcpu-runtime.toml")?)?;
        let enabled = resource.get("irq_service").and_then(toml::Value::as_str) != Some("off")
            && matches!(policy, SchedulePolicy::Fifo { .. });
        ensure!(
            if enabled {
                guest_low > i128::from(report.start) && guest_high < i128::from(report.end)
            } else {
                guest_low >= i128::from(report.end)
            },
            "IRQ service inheritance did not produce the expected scheduling order"
        );
        println!(
            "VIRQ_INVERSION_WITNESS policy={policy_name} sample=1 blocker_cpu=0 \
             blocker_priority=60 blocker_thread={} start_ticks={} end_ticks={} due_ticks={} \
             guest_low_ticks={} guest_high_ticks={} preempted={} joined=1 wrong_cpu=0",
            report.thread,
            report.start,
            report.end,
            due,
            guest_low,
            guest_high,
            u8::from(enabled)
        );
    }
    if !shared_linux && let Some((peer, progress)) = linux.as_mut() {
        progress.finish(peer, policy_name, linux_start, linux_end)?;
    }
    for (index, (before, after)) in linux_samples.iter().enumerate() {
        println!(
            "VIRQ_LINUX_SAMPLE policy={policy_name} sample={} before_batches={before} \
             after_batches={after}",
            index + 1
        );
    }
    // Both intervals use the host clock. Confirmation includes mailbox polling
    // and scheduling; it is not a guest ISR timestamp or a physical IRQ latency.
    // Emit only after sampling so serial output does not enter these intervals.
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
             guest_end_ticks={} observed_ticks={} frequency_hz={frequency} deadline_ns={} \
             deadline_miss={} trace_loss=unknown",
            index + 1,
            stamp.submitted,
            stamp.guest,
            stamp.guest_end,
            stamp.observed,
            physical_deadlines
                .get(index)
                .map_or(0, |due| due.saturating_sub(stamp.submitted) * 1_000_000_000
                    / frequency),
            physical_deadlines.get(index).map_or("na", |due| {
                let guest_low = i128::from(stamp.guest) + offset_low;
                let guest_high = i128::from(stamp.guest) + offset_high;
                if guest_low > i128::from(*due) {
                    "true"
                } else if guest_high <= i128::from(*due) {
                    "false"
                } else {
                    "unknown"
                }
            })
        );
    }
    for (index, sample) in task_samples.iter().enumerate() {
        println!(
            "VIRQ_TASK_SAMPLE policy={policy_name} sample={} start_ticks={} end_ticks={} \
             checksum={} observed_ticks={}",
            index + 1,
            sample.start,
            sample.end,
            sample.checksum,
            sample.observed
        );
    }
    if let Some(plan) = schedule {
        plan.report(policy_name);
    }
    if load.is_some() {
        for (index, (before, after)) in load_samples.iter().enumerate() {
            println!(
                "VIRQ_LOAD_SAMPLE policy={policy_name} sample={} before_batches={before} \
                 after_batches={after}",
                index + 1
            );
        }
    }
    for (index, due) in physical_deadlines.iter().enumerate() {
        println!(
            "VIRQ_PHYSICAL_ARM policy={policy_name} sample={} due_ticks={due} intid=30 cpu={}",
            index + 1,
            usize::from(guest_running)
        );
    }
    for (index, matched) in rtc_arms.iter().enumerate() {
        println!(
            "VIRQ_RTC_ARM policy={policy_name} sample={} match_seconds={matched} intid=34 cpu=0",
            index + 1
        );
    }
    println!("VIRQ_INJECT_COMPLETE vm=2 vcpu=1 vector=48 samples={samples} errors=0");
    println!(
        "E1_COUNTERS idle_vcpu_returns={idle_vcpu_returns} acknowledgements={samples} \
         policy={policy:?}"
    );
    if task.is_some() {
        println!(
            "VIRQ_TASK_BACKGROUND policy={policy_name} non_target_vcpu_returns={idle_vcpu_returns}"
        );
    }
    memory.write_bytes(address + 16, &1u32.to_le_bytes())?;
    let completed =
        format!("SOFTWARE VIRQ COMPLETE streams=1 samples_each={samples} total={samples}");
    fixture.wait(Duration::from_secs(30), |snapshot, output| {
        snapshot.state == VmStatus::Stopped
            && output
                .lines()
                .any(|line| line.trim_end_matches('\r') == completed)
    })?;
    fixture.validate_console(|output| {
        ensure!(
            output
                .lines()
                .any(|line| line.trim_end_matches('\r') == completed),
            "guest omitted completion"
        );
        Ok(())
    })?;
    fixture.check_policy(policy, 0)?;
    ensure!(
        interrupt.pulse().is_err(),
        "stopped run retained its interrupt port"
    );
    fixture.stop()?;
    Ok(MeasurementOutcome {
        work_window: (load_start, load_end),
        pressure,
    })
}

fn wait_ready(fixture: &mut Fixture, samples: u32, memory: &GuestMemoryPort) -> Result<()> {
    // CPU_ON may enter before the owner publishes its participant snapshot.
    let outcome = fixture.wait(Duration::from_secs(30), |snapshot, output| {
        snapshot.cpu.running_vcpu_count == 2
            && output.split_inclusive('\n').any(|line| {
                line.ends_with('\n')
                    && line
                        .trim_end_matches(['\r', '\n'])
                        .starts_with("SOFTWARE VIRQ READY suspend vector=48 samples=")
            })
    });
    if outcome.is_err() {
        report_lifecycle(fixture, "ready_failed");
        if let Err(error) = report_boot_failure_memory(memory) {
            println!("VIRQ_FAILURE_MEMORY unavailable={error:#}");
        }
    }
    outcome?;
    let expected = format!("SOFTWARE VIRQ READY suspend vector=48 samples={samples}");
    fixture.validate_console(|output| {
        ensure!(
            output
                .lines()
                .any(|line| line.trim_end_matches('\r') == expected),
            "guest sample count disagrees with resource"
        );
        Ok(())
    })
}

fn report_boot_failure_memory(memory: &GuestMemoryPort) -> Result<()> {
    let resource: toml::Value =
        toml::from_str(&std::fs::read_to_string("/tests/vcpu-runtime.toml")?)?;
    let Some(regions) = resource
        .get("boot_failure_regions")
        .and_then(toml::Value::as_array)
    else {
        return Ok(());
    };
    ensure!(regions.len() <= 4, "too many boot diagnostic regions");
    for region in regions {
        let name = region
            .get("name")
            .and_then(toml::Value::as_str)
            .context("region name")?;
        let start = usize::try_from(
            region
                .get("address")
                .and_then(toml::Value::as_integer)
                .context("region address")?,
        )?;
        let size = usize::try_from(
            region
                .get("size")
                .and_then(toml::Value::as_integer)
                .context("region size")?,
        )?;
        let end = start.checked_add(size).context("region end overflow")?;
        ensure!(
            (16..=4096).contains(&size)
                && size.is_multiple_of(16)
                && start >= 0x4000_0000
                && end <= 0x4800_0000
                && start.is_multiple_of(8),
            "boot diagnostic region outside bounded Guest RAM"
        );
        let mut bytes = std::vec![0u8; size];
        memory.read_bytes(GuestPhysAddr::from(start), &mut bytes)?;
        println!(
            "VIRQ_FAILURE_MEMORY_BEGIN region={name} address={start:#x} size={size} concurrent=1"
        );
        for (index, chunk) in bytes.chunks_exact(16).enumerate() {
            let low = u64::from_le_bytes(chunk[..8].try_into()?);
            let high = u64::from_le_bytes(chunk[8..].try_into()?);
            println!(
                "VIRQ_FAILURE_MEMORY region={name} address={:#x} low={low:#018x} high={high:#018x}",
                start + index * 16
            );
        }
        println!("VIRQ_FAILURE_MEMORY_END region={name} size={size}");
    }
    Ok(())
}

fn report_lifecycle(fixture: &Fixture, stage: &str) {
    let snapshot = fixture.vm.snapshot();
    println!(
        "VIRQ_LIFECYCLE stage={stage} ticks={} vm={} run={:?} state={:?} operation={:?} \
         entry_count={} park_count={} participants={} vcpus={:?}",
        clock::host_ticks(),
        snapshot.vm_id,
        snapshot.run,
        snapshot.state,
        snapshot.current_operation,
        snapshot.entry_count,
        snapshot.park_count,
        snapshot.cpu.running_vcpu_count,
        snapshot.vcpu
    );
}

fn rejected_ready_observer(_: ax_std::os::arceos::task::diagnostics::ReadyTraceRecord) {
    panic!("rejected ready observer was invoked");
}

fn resource_unused_rtc() -> Result<bool> {
    let resource: toml::Value =
        toml::from_str(&std::fs::read_to_string("/tests/vcpu-runtime.toml")?)?;
    let config: toml::Value = toml::from_str(&std::fs::read_to_string(
        "/guest/builtin/configs/vm-2.toml",
    )?)?;
    ensure!(
        config
            .get("devices")
            .and_then(|v| v.get("passthrough"))
            .and_then(toml::Value::as_array)
            .is_some_and(|v| v.is_empty()),
        "RTC fixture forbids Guest passthrough"
    );
    Ok(resource
        .get("guest_rtc_unused")
        .and_then(toml::Value::as_bool)
        == Some(true))
}
