#!/usr/bin/env python3
"""Validate explicit workload evidence alongside calibrated IRQ/Ready samples."""

import argparse
import csv
import json
import re
from pathlib import Path

from analyze_virq_host import measurement_count
from analyze_virq_irq_pressure import validate_pressure, verify_window
from analyze_virq_linux_fence import validate_fences, verify_fence_window
from analyze_virq_isr import analyze as analyze_isr, isr_records
from analyze_virq_ready import analyze as analyze_ready
from analyze_virq_runtime import EVENT, parse
from analyze_virq_services import analyze as analyze_services
from virq_work_counters import LINUX_PROGRESS, checksum_after, linux_memory_expected

SCENARIO = re.compile(r"VIRQ_SCENARIO name=(baseline|cpu_same_core|cpu_continuous|memory_cross_core|linux_cpu|linux_memory)")
CONTROLLER = re.compile(r"VIRQ_CONTROLLER cpu=(\d+)")
BOOT_WORK = re.compile(r"VIRQ_LOAD_BOOT_WORK policy=(fair|fifo80) batches=(\d+)")
SUMMARY = re.compile(
    r"VIRQ_LOAD_SUMMARY policy=(fair|fifo80) cpu=(\d+) thread=(\d+) "
    r"batch_iterations=(\d+) start_batches=(\d+) end_batches=(\d+) "
    r"final_batches=(\d+) wrong_cpu=(\d+) checksum=(\d+) joined=(\d+)"
)
SAMPLE = re.compile(
    r"VIRQ_LOAD_SAMPLE policy=(fair|fifo80) sample=(\d+) "
    r"before_batches=(\d+) after_batches=(\d+)"
)
MEMORY_CONFIG = re.compile(r"VIRQ_MEMORY_CONFIG cpu=(\d+) working_set_bytes=(\d+) chunk_words=(\d+) access=volatile_read_modify_write")
MEMORY_SUMMARY = re.compile(
    r"VIRQ_MEMORY_SUMMARY policy=(fair|fifo80) cpu=(\d+) thread=(\d+) "
    r"working_set_bytes=(\d+) chunk_words=(\d+) start_batches=(\d+) end_batches=(\d+) "
    r"final_batches=(\d+) read_bytes=(\d+) write_bytes=(\d+) checksum=(\d+) "
    r"verified_words=(\d+) mismatch_words=(\d+) wrong_cpu=(\d+) joined=(\d+)"
)
LINUX_CONFIG = re.compile(r"VIRQ_LINUX_CONFIG vm=1 vcpu=0 host_cpu=([13]) guest_cpu=0 workload=(cpu|memory) batch_iterations=8192 report_batches=256")
LINUX_MEMORY_CONFIG = re.compile(r"VIRQ_LINUX_MEMORY_CONFIG working_set_bytes=(\d+) every_batches=(\d+) chunk_words=8192")
LINUX_MEMORY_READY = re.compile(r"LINUX_MEMORY_READY version=1 working_set_bytes=(\d+) every_batches=(\d+) chunk_words=8192")
LINUX_MEMORY_SUMMARY = re.compile(r"VIRQ_LINUX_MEMORY_SUMMARY policy=(fair|fifo80) working_set_bytes=(\d+) every_batches=(\d+) final_memory_batches=(\d+) read_bytes=(\d+) write_bytes=(\d+) checksum=(\d+) stopped=1")
LINUX_BOOT = re.compile(r"VIRQ_LINUX_BOOT vm=1 vcpu=0 host_cpu=([13]) guest_cpu=0 batches=(\d+)")
LINUX_SUMMARY = re.compile(
    r"VIRQ_LINUX_SUMMARY policy=(fair|fifo80) vm=1 vcpu=0 host_cpu=([13]) guest_cpu=0 "
    r"start_batches=(\d+) end_batches=(\d+) final_batches=(\d+) checksum=(\d+) reports=(\d+) "
    r"batch_iterations=8192 report_batches=256 stopped=1"
)
LINUX_SAMPLE = re.compile(
    r"VIRQ_LINUX_SAMPLE policy=(fair|fifo80) sample=(\d+) before_batches=(\d+) after_batches=(\d+)"
)
LINUX_READY = "LINUX_LOAD_READY version=1 guest_cpu=0 batch_iterations=8192 report_batches=256"
VM_RETIRED = re.compile(r"VIRQ_VM_GROUP_RETIRED count=2 empty=1")


def validate_load(log):
    validate_pressure(log)
    validate_fences(log)
    sample_count = measurement_count(log)
    if parse(log, "VIRQ_CONTROLLER", CONTROLLER) != [("0",)]:
        raise ValueError("missing or inconsistent CPU0 controller placement")
    scenarios = parse(log, "VIRQ_SCENARIO", SCENARIO)
    if len(scenarios) != 1:
        raise ValueError("expected exactly one explicit scenario")
    scenario = scenarios[0][0]
    summaries = parse(log, "VIRQ_LOAD_SUMMARY", SUMMARY)
    samples = parse(log, "VIRQ_LOAD_SAMPLE", SAMPLE)
    boot = parse(log, "VIRQ_LOAD_BOOT_WORK", BOOT_WORK)
    memory = parse(log, "VIRQ_MEMORY_SUMMARY", MEMORY_SUMMARY)
    memory_config = parse(log, "VIRQ_MEMORY_CONFIG", MEMORY_CONFIG)
    if scenario not in ("linux_cpu", "linux_memory") and any(marker in log for marker in ("VIRQ_LINUX_", "LINUX_LOAD_", "LINUX_MEMORY_")):
        raise ValueError("unexpected Linux guest workload evidence")
    if scenario != "memory_cross_core" and (memory or memory_config):
        raise ValueError("unexpected memory workload evidence")
    if scenario in ("cpu_continuous", "memory_cross_core"):
        if len(boot) != 2 or {b[0] for b in boot} != {"fair", "fifo80"}:
            raise ValueError("continuous load has no distinct pre-VM progress evidence")
    elif boot:
        raise ValueError("unexpected pre-VM work for a gated or baseline scenario")
    if "VIRQ_LOAD_CLEANUP_FAILED" in log:
        raise ValueError("load cleanup failed")
    if scenario in ("linux_cpu", "linux_memory"):
        if summaries or samples or boot:
            raise ValueError("Linux guest workload also claims Host worker evidence")
        reports, windows = validate_linux(log, sample_count, scenario)
        return scenario, reports, windows
    if scenario == "memory_cross_core":
        if summaries:
            raise ValueError("memory workload also claims CPU-only work")
        reports, windows = validate_memory(memory_config, memory, samples, boot, sample_count)
        return scenario, reports, windows
    if scenario == "baseline":
        if summaries or samples:
            raise ValueError("baseline unexpectedly contains load evidence")
        return scenario, {}, {}
    if len(summaries) != 2 or {s[0] for s in summaries} != {"fair", "fifo80"}:
        raise ValueError("missing or duplicated load summary")
    reports, windows = {}, {}
    for fields in summaries:
        policy = fields[0]
        cpu, thread, iterations, start, end, final, wrong, checksum, joined = map(int, fields[1:])
        if cpu != 1 or not thread or iterations != 8192 or not 0 < start < end <= final:
            raise ValueError("invalid CPU load identity, work size or progress")
        if wrong or joined != 1 or checksum != checksum_after(final * iterations):
            raise ValueError("invalid CPU load completion, placement or checksum")
        boot_batches = dict(boot).get(policy)
        if boot_batches is not None and not 1 < int(boot_batches) <= start:
            raise ValueError("continuous work was not established before the sampling interval")
        selected_windows, progress_samples = sample_windows(samples, policy, start, end, sample_count)
        windows.update(selected_windows)
        reports[policy] = dict(cpu=cpu, thread=thread, batch_iterations=iterations,
                               start_batches=start, end_batches=end, final_batches=final,
                               interval_batches=end-start, interval_iterations=(end-start)*iterations,
                               samples_with_progress=progress_samples,
                               samples_without_observed_progress=sample_count-progress_samples,
                               checksum=checksum, wrong_cpu=wrong, joined=True)
        if boot_batches is not None:
            reports[policy]["pre_vm_batches"] = int(boot_batches)
    return scenario, reports, windows


def linux_host_windows(log, fences, sample_count):
    """Use causal fence windows, or the complete critical Host observations."""
    if fences['mode'] == 'serial':
        return {policy: dict(start_ticks=state['begin_request_ticks'],
                             end_ticks=state['end_observed_ticks'], source='linux_fences')
                for policy, state in fences['policies'].items()}
    observations = isr_records(log)
    expected = [(policy, sample) for policy in ('fair', 'fifo80') for sample in range(1, sample_count+1)]
    if [(row['policy'], row['sample']) for row in observations] != expected:
        raise ValueError('Linux residency needs complete per-policy Host measurement windows')
    tasks = None
    if 'VIRQ_TASK_SAMPLE' in log:
        # Reuse the grammar after the task -> physical -> load import cycle has initialized.
        from analyze_virq_task import TASK
        tasks = parse(log, 'VIRQ_TASK_SAMPLE', TASK)
        if [(row[0], int(row[1])) for row in tasks] != expected:
            raise ValueError('Linux residency needs all task completion observations')
    from analyze_virq_periodic import protocol
    periodic = protocol(log)
    windows = {}
    for policy in ('fair', 'fifo80'):
        selected = [row for row in observations if row['policy'] == policy]
        start = min(row['submit_ticks'] for row in selected)
        end = max(row['observed_ticks'] for row in selected)
        if periodic is not None:
            start = min(row[1] for row in periodic['policies'][policy]['releases'])
        if tasks is not None:
            end = max(end, max(int(row[-1]) for row in tasks if row[0] == policy))
        if not 0 < start < end:
            raise ValueError('Linux Host measurement window is invalid')
        windows[policy] = dict(start_ticks=start, end_ticks=end,
                               source='critical_task_observation' if tasks is not None else 'critical_isr_observation')
    return windows


def validate_linux(log, sample_count, scenario):
    """Check complete serial reports and independent runtime ownership evidence."""
    mode = 'memory' if scenario == 'linux_memory' else 'cpu'
    fences = validate_fences(log)
    enabled = fences['mode'] == 'serial'
    selected = parse(log, "VIRQ_LINUX_CONFIG", LINUX_CONFIG)
    if len(selected) != 1 or selected[0][1] != mode:
        raise ValueError("Linux guest needs one explicit workload configuration")
    host_cpu = selected[0][0]
    configs = parse(log, 'VIRQ_LINUX_MEMORY_CONFIG', LINUX_MEMORY_CONFIG)
    memory_summaries = parse(log, 'VIRQ_LINUX_MEMORY_SUMMARY', LINUX_MEMORY_SUMMARY)
    if mode == 'memory':
        if len(configs) != 1 or [row[0] for row in memory_summaries] != ['fair', 'fifo80']:
            raise ValueError('Linux memory configuration or summaries missing')
        size, every = map(int, configs[0])
        if not 1048576 <= size <= 67108864 or size % 8192 or not 1 <= every <= 1024:
            raise ValueError('Invalid Linux memory working set or duty')
    elif any(marker in log for marker in ('VIRQ_LINUX_MEMORY_', 'LINUX_MEMORY_')):
        raise ValueError('CPU workload has unexpected memory evidence')
    boots = parse(log, "VIRQ_LINUX_BOOT", LINUX_BOOT)
    summaries = parse(log, "VIRQ_LINUX_SUMMARY", LINUX_SUMMARY)
    samples = parse(log, "VIRQ_LINUX_SAMPLE", LINUX_SAMPLE)
    if len(boots) != 2 or [s[0] for s in summaries] != ["fair", "fifo80"]:
        raise ValueError("missing or reordered Linux guest completion evidence")
    if any(boot[0] != host_cpu for boot in boots) or any(summary[1] != host_cpu for summary in summaries):
        raise ValueError("Linux placement declarations disagree")
    if len(parse(log, "VIRQ_VM_GROUP_RETIRED", VM_RETIRED)) != 2:
        raise ValueError("both VM groups must be retired")
    # A new boot resets the serial recurrence. A completion must close exactly
    # that stream; later complete reports may not silently escape validation.
    active, batches, checksum, closed = False, 0, 1, []
    retired, retired_count = True, 0
    memory_ready, pending_memory = False, None
    for line in log.splitlines():
        if "LINUX_LOAD_FAILED" in line:
            raise ValueError("Linux workload reported failure")
        if "LINUX_LOAD_READY" in line:
            if active or not retired or line.strip() != LINUX_READY.replace('version=1', 'version=2' if enabled else 'version=1'):
                raise ValueError("Linux guest readiness protocol mismatch")
            active, batches, checksum, retired = True, 0, 1, False
            memory_ready = False
        elif 'LINUX_MEMORY_READY' in line:
            match = LINUX_MEMORY_READY.fullmatch(line.strip())
            if (mode != 'memory' or not active or memory_ready or batches or match is None
                    or tuple(map(int, match.groups())) != (size, every)):
                raise ValueError('Linux memory readiness protocol mismatch')
            memory_ready = True
        elif "LINUX_LOAD_PROGRESS" in line:
            match = LINUX_PROGRESS.fullmatch(line.strip())
            if not active or match is None:
                raise ValueError("Linux progress outside its active stream")
            count, value = map(int, match.groups()[:2])
            if mode == 'memory':
                if (not memory_ready or match[3] is None
                        or tuple(map(int, match.groups()[2:])) != linux_memory_expected(count, size, every)):
                    raise ValueError('Linux memory progress verification failed')
            elif match[3] is not None:
                raise ValueError('CPU workload has memory progress')
            if count != batches + 256 or value != checksum_after(count * 8192):
                raise ValueError("Linux progress is missing, reordered or has a bad checksum")
            batches, checksum = count, value
        elif "VIRQ_LINUX_BOOT" in line:
            match = LINUX_BOOT.fullmatch(line.strip())
            if not active or match is None or match[1] != host_cpu or int(match[2]) != batches or not batches:
                raise ValueError("Linux boot marker does not match observed progress")
        elif "VIRQ_LINUX_SUMMARY" in line:
            match = LINUX_SUMMARY.fullmatch(line.strip())
            if not active or match is None:
                raise ValueError("Linux completion has no active stream")
            policy, cpu, start, end, final, value, reports = match.groups()
            if cpu != host_cpu:
                raise ValueError("Linux completion placement disagrees with configuration")
            start, end, final, value, reports = map(int, (start, end, final, value, reports))
            valid_window = (0 < start <= end <= final if enabled else 0 < start < end <= final)
            if (final, value, reports) != (batches, checksum, batches // 256) or not valid_window:
                raise ValueError("Linux completion does not match its observed stream")
            closed.append(policy)
            active = False
            if mode == 'memory':
                pending_memory = policy, batches
        elif 'VIRQ_LINUX_MEMORY_SUMMARY' in line:
            match = LINUX_MEMORY_SUMMARY.fullmatch(line.strip())
            if active or match is None or pending_memory is None or match[1] != pending_memory[0]:
                raise ValueError('Linux memory summary outside its stopped stream')
            m, logical, value = linux_memory_expected(pending_memory[1], size, every)
            if tuple(map(int, match.groups()[1:])) != (size, every, m, logical // 2, logical // 2, value):
                raise ValueError('Linux memory completion mismatch')
            pending_memory = None
        elif "VIRQ_VM_GROUP_RETIRED" in line:
            if active or pending_memory is not None or retired or len(closed) != retired_count + 1:
                raise ValueError("VM group retirement is out of order")
            retired = True
            retired_count += 1
    if active or not retired or closed != ["fair", "fifo80"]:
        raise ValueError("Linux guest stream is incomplete")
    # Thread generations bind the selected CPU observations to VM1/vCPU0;
    # Guest sched_getcpu()=0 alone cannot establish Host residency.
    events = parse(log, "VIRQ_RUNTIME ", EVENT)
    bindings = [e for e in events if e[3] == "Binding" and e[5] == "1"]
    threads = {int(e[4]) for e in bindings}
    if len(bindings) != 2 or len(threads) != 2 or any(e[0] != host_cpu or e[6] != "0" for e in bindings):
        raise ValueError("Linux guest needs one vCPU generation per policy")
    host_windows = linux_host_windows(log, fences, sample_count)
    generations = {}
    key = lambda event: (int(event[2]), int(event[1]))
    previous_stop = None
    for policy, binding in zip(('fair', 'fifo80'), sorted(bindings, key=key)):
        thread = int(binding[4])
        owned = [e for e in events if int(e[4]) == thread and e[3] in ("Running", "Stopped", "GuestEntryBoundary")]
        if {e[3] for e in owned} != {"Running", "Stopped", "GuestEntryBoundary"} or any(e[0] != host_cpu for e in owned):
            raise ValueError("Linux guest execution or retirement left its selected Host CPU")
        running = min((event for event in owned if event[3] == 'Running'), key=key)
        entry = min((event for event in owned if event[3] == 'GuestEntryBoundary'), key=key)
        stopped = max(owned, key=key)
        if stopped[3] != "Stopped":
            raise ValueError("Linux vCPU generation was not stopped")
        if not key(running) <= key(binding) < key(entry) < key(stopped):
            raise ValueError('Linux generation Binding, entry or retirement order is invalid')
        if previous_stop is not None and key(running) <= previous_stop:
            raise ValueError('Linux policy generations overlap or reuse a lifecycle')
        window = host_windows[policy]
        if not int(entry[2]) <= window['start_ticks'] <= window['end_ticks'] <= int(stopped[2]):
            raise ValueError('Linux generation does not cover its policy Host measurement window')
        previous_stop = key(stopped)
        generations[policy] = dict(thread=thread, first_running_ticks=int(running[2]),
                                   binding_ticks=int(binding[2]), first_entry_ticks=int(entry[2]),
                                   stopped_ticks=int(stopped[2]), host_window=window,
                                   time_window_verified=True)
    reports, windows = {}, {}
    for boot, fields in zip(boots, summaries):
        policy = fields[0]
        start, end, final, checksum, count = map(int, fields[2:])
        if not 0 < int(boot[1]) <= start or any(n % 256 for n in (start, end, final)):
            raise ValueError("Linux startup or report-boundary count is invalid")
        selected, progress = sample_windows(samples, policy, start, end, sample_count)
        if any(n % 256 for row in selected.values() for n in row.values()):
            raise ValueError("Linux sample uses an unreported counter value")
        windows.update(selected)
        reports[policy] = dict(kind="linux_guest_cpu", vm=1, vcpu=0, host_cpu=int(host_cpu),
            guest_cpu=0, pre_rt_start_batches=int(boot[1]), start_batches=start, end_batches=end,
            final_reported_batches=final, checksum=checksum, reports=count, stopped=True,
            interval_reported_iterations=(end-start)*8192, samples_with_progress=progress,
            samples_without_observed_progress=sample_count-progress)
        reports[policy]['runtime_observation'] = generations[policy]
        if enabled:
            reports[policy]['fenced_throughput'] = fences['policies'][policy]
        if mode == 'memory':
            _, before_bytes, _ = linux_memory_expected(start, size, every)
            _, after_bytes, _ = linux_memory_expected(end, size, every)
            m, logical, value = linux_memory_expected(final, size, every)
            reports[policy].update(kind='linux_guest_memory', working_set_bytes=size,
                every_batches=every, final_memory_batches=m, memory_checksum=value,
                final_logical_read_bytes=logical // 2, final_logical_write_bytes=logical // 2,
                interval_logical_read_bytes=(after_bytes-before_bytes) // 2,
                interval_logical_write_bytes=(after_bytes-before_bytes) // 2)
            for row in selected.values():
                _, before_bytes, _ = linux_memory_expected(row['load_before_batches'], size, every)
                _, after_bytes, _ = linux_memory_expected(row['load_after_batches'], size, every)
                row.update(logical_read_bytes=(after_bytes-before_bytes) // 2,
                           logical_write_bytes=(after_bytes-before_bytes) // 2)
    return reports, windows


def sample_windows(samples, policy, start, end, sample_count):
    selected = [s for s in samples if s[0] == policy]
    if len(selected) != sample_count or [int(s[1]) for s in selected] != list(range(1, sample_count + 1)):
        raise ValueError("missing, reordered or duplicated load samples")
    previous, progress, windows = start, 0, {}
    for _, sample, before, after in selected:
        before, after = int(before), int(after)
        if not previous <= before <= after <= end:
            raise ValueError("load counter regressed or left sampling bounds")
        windows[(policy, int(sample))] = dict(load_before_batches=before,
                                             load_after_batches=after,
                                             load_window_batches=after-before)
        previous = after
        progress += after > before
    return windows, progress


def validate_memory(configs, summaries, samples, boot, sample_count):
    if len(configs) != 1:
        raise ValueError("memory workload needs one explicit configuration")
    cpu, size, chunk = map(int, configs[0])
    if cpu not in (2, 3) or chunk != 1024 or not 1024*1024 <= size <= 64*1024*1024 or size % 8192:
        raise ValueError("invalid memory workload configuration")
    if len(summaries) != 2 or {s[0] for s in summaries} != {"fair", "fifo80"}:
        raise ValueError("missing or duplicated memory completion summaries")
    reports, windows = {}, {}
    for fields in summaries:
        policy = fields[0]
        actual_cpu, thread, actual_size, actual_chunk, start, end, final, reads, writes, checksum, verified, mismatch, wrong, joined = map(int, fields[1:])
        words = size//8
        if (actual_cpu, actual_size, actual_chunk) != (cpu, size, chunk) or not thread or not 0 < start < end <= final:
            raise ValueError("memory identity, size or progress mismatch")
        expected_checksum = (words*(words-1)//2 + final*chunk) % (1 << 64)
        if (reads, writes, checksum, verified, mismatch, wrong, joined) != (final*8192, final*8192, expected_checksum, words, 0, 0, 1):
            raise ValueError("memory traffic, verification or retirement evidence mismatch")
        before_vm = int(dict(boot)[policy])
        if not 1 < before_vm <= start:
            raise ValueError("memory workload was not active before VM startup")
        selected, progress = sample_windows(samples, policy, start, end, sample_count)
        for row in selected.values():
            row.update(logical_read_bytes=row["load_window_batches"]*8192,
                       logical_write_bytes=row["load_window_batches"]*8192)
        windows.update(selected)
        reports[policy] = dict(kind="memory", cpu=cpu, thread=thread, working_set_bytes=size,
            chunk_words=chunk, pre_vm_batches=before_vm, start_batches=start, end_batches=end,
            final_batches=final, final_logical_read_bytes=reads, final_logical_write_bytes=writes,
            interval_logical_read_bytes=(end-start)*8192, interval_logical_write_bytes=(end-start)*8192,
            checksum=checksum, verified_words=verified, mismatch_words=0, wrong_cpu=0, joined=True,
            samples_with_progress=progress, samples_without_observed_progress=sample_count-progress)
    return reports, windows


def analyze(log):
    pressure = validate_pressure(log)
    fences = validate_fences(log)
    service_placement = analyze_services(log)
    scenario, loads, windows = validate_load(log)
    ready_rows, _, ready = analyze_ready(log)
    isr_rows, _, clocks = analyze_isr(log)
    isr = {(r["policy"], r["sample"]): r for r in isr_rows}
    rows = []
    for row in ready_rows:
        key = row["policy"], row["sample"]
        merged = dict(isr[key])
        merged.update(row)
        merged.update(scenario=scenario)
        verify_window(pressure, row['policy'], merged['submit_ticks'], merged['observed_ticks'], merged['frequency_hz'])
        verify_fence_window(fences, row['policy'], merged['submit_ticks'], merged['observed_ticks'], merged['frequency_hz'])
        merged.update(windows.get(key, dict(load_before_batches="", load_after_batches="",
                                            load_window_batches="")))
        rows.append(merged)
    return rows, dict(scenario=scenario, loads=loads, ready=ready, clocks=clocks,
                     service_placement=service_placement, irq_pressure=pressure, linux_fences=fences,
                     limitations=[
                         (f"A separate virtualized Linux VM executes on Host CPU{loads['fair']['host_cpu']}; placement alone does not establish hardware memory interference." if scenario in ("linux_cpu", "linux_memory") else "Host workload only; noncritical VM interference remains untested."),
                         "Linux counters are complete serial-observed reports, not exact ISR overlap, unreported final work, or DRAM traffic.",
                         "Per-sample work observations lie inside submit-to-ack observation windows, not necessarily before Guest ISR.",
                         "Batch-boundary CPU checks supplement affinity, not instruction-level residency measurement.",
                         "Yielding work does not establish a fixed CPU utilization or DRAM/cache contention level.",
                         "Memory counts are logical volatile operations attributed to completed chunks, not DRAM traffic; chunks may cross window boundaries.",
                         "QEMU validates the measurement and workload lifecycle, not hardware performance."
                     ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows, summary = analyze(args.log.read_text())
    except (ValueError, OSError) as error:
        parser.exit(1, f"invalid load measurement: {error}\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
