#!/usr/bin/env python3
"""Validate explicit workload evidence alongside calibrated IRQ/Ready samples."""

import argparse
import csv
import json
import re
from pathlib import Path

from analyze_virq_host import measurement_count
from analyze_virq_isr import analyze as analyze_isr
from analyze_virq_ready import analyze as analyze_ready
from analyze_virq_runtime import EVENT, parse
from analyze_virq_services import analyze as analyze_services

SCENARIO = re.compile(r"VIRQ_SCENARIO name=(baseline|cpu_same_core|cpu_continuous|memory_cross_core|linux_cpu)")
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
LINUX_CONFIG = re.compile(r"VIRQ_LINUX_CONFIG vm=1 vcpu=0 host_cpu=3 guest_cpu=0 workload=cpu batch_iterations=8192 report_batches=256")
LINUX_BOOT = re.compile(r"VIRQ_LINUX_BOOT vm=1 vcpu=0 host_cpu=3 guest_cpu=0 batches=(\d+)")
LINUX_SUMMARY = re.compile(
    r"VIRQ_LINUX_SUMMARY policy=(fair|fifo80) vm=1 vcpu=0 host_cpu=3 guest_cpu=0 "
    r"start_batches=(\d+) end_batches=(\d+) final_batches=(\d+) checksum=(\d+) reports=(\d+) "
    r"batch_iterations=8192 report_batches=256 stopped=1"
)
LINUX_SAMPLE = re.compile(
    r"VIRQ_LINUX_SAMPLE policy=(fair|fifo80) sample=(\d+) before_batches=(\d+) after_batches=(\d+)"
)
LINUX_READY = "LINUX_LOAD_READY version=1 guest_cpu=0 batch_iterations=8192 report_batches=256"
LINUX_PROGRESS = re.compile(r"LINUX_LOAD_PROGRESS batches=(\d+) checksum=(\d+) guest_cpu=0")
VM_RETIRED = re.compile(r"VIRQ_VM_GROUP_RETIRED count=2 empty=1")


def checksum_after(iterations):
    """Advance the affine recurrence by exponentiation, modulo 2**64."""
    mask = (1 << 64) - 1
    multiplier, increment, checksum = 6364136223846793005, 1, 1
    while iterations:
        if iterations & 1:
            checksum = (multiplier * checksum + increment) & mask
        increment = (multiplier * increment + increment) & mask
        multiplier = multiplier * multiplier & mask
        iterations >>= 1
    return checksum


def validate_load(log):
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
    if scenario != "linux_cpu" and any(marker in log for marker in ("VIRQ_LINUX_", "LINUX_LOAD_")):
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
    if scenario == "linux_cpu":
        if summaries or samples or boot:
            raise ValueError("Linux guest workload also claims Host worker evidence")
        reports, windows = validate_linux(log, sample_count)
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


def validate_linux(log, sample_count):
    """Check complete serial reports and independent runtime ownership evidence."""
    if len(parse(log, "VIRQ_LINUX_CONFIG", LINUX_CONFIG)) != 1:
        raise ValueError("Linux guest needs one explicit workload configuration")
    boots = parse(log, "VIRQ_LINUX_BOOT", LINUX_BOOT)
    summaries = parse(log, "VIRQ_LINUX_SUMMARY", LINUX_SUMMARY)
    samples = parse(log, "VIRQ_LINUX_SAMPLE", LINUX_SAMPLE)
    if len(boots) != 2 or [s[0] for s in summaries] != ["fair", "fifo80"]:
        raise ValueError("missing or reordered Linux guest completion evidence")
    if len(parse(log, "VIRQ_VM_GROUP_RETIRED", VM_RETIRED)) != 2:
        raise ValueError("both VM groups must be retired")
    # A new boot resets the serial recurrence. A completion must close exactly
    # that stream; later complete reports may not silently escape validation.
    active, batches, checksum, closed = False, 0, 1, []
    retired, retired_count = True, 0
    for line in log.splitlines():
        if "LINUX_LOAD_FAILED" in line:
            raise ValueError("Linux workload reported failure")
        if "LINUX_LOAD_READY" in line:
            if active or not retired or line.strip() != LINUX_READY:
                raise ValueError("Linux guest readiness protocol mismatch")
            active, batches, checksum, retired = True, 0, 1, False
        elif "LINUX_LOAD_PROGRESS" in line:
            match = LINUX_PROGRESS.fullmatch(line.strip())
            if not active or match is None:
                raise ValueError("Linux progress outside its active stream")
            count, value = map(int, match.groups())
            if count != batches + 256 or value != checksum_after(count * 8192):
                raise ValueError("Linux progress is missing, reordered or has a bad checksum")
            batches, checksum = count, value
        elif "VIRQ_LINUX_BOOT" in line:
            match = LINUX_BOOT.fullmatch(line.strip())
            if not active or match is None or int(match[1]) != batches or not batches:
                raise ValueError("Linux boot marker does not match observed progress")
        elif "VIRQ_LINUX_SUMMARY" in line:
            match = LINUX_SUMMARY.fullmatch(line.strip())
            if not active or match is None:
                raise ValueError("Linux completion has no active stream")
            policy, start, end, final, value, reports = match.groups()
            start, end, final, value, reports = map(int, (start, end, final, value, reports))
            if (final, value, reports) != (batches, checksum, batches // 256) or not 0 < start < end <= final:
                raise ValueError("Linux completion does not match its observed stream")
            closed.append(policy)
            active = False
        elif "VIRQ_VM_GROUP_RETIRED" in line:
            if active or retired or len(closed) != retired_count + 1:
                raise ValueError("VM group retirement is out of order")
            retired = True
            retired_count += 1
    if active or not retired or closed != ["fair", "fifo80"]:
        raise ValueError("Linux guest stream is incomplete")
    # Thread generations bind the CPU3 execution observations to VM1/vCPU0;
    # Guest sched_getcpu()=0 alone cannot establish Host residency.
    events = parse(log, "VIRQ_RUNTIME ", EVENT)
    bindings = [e for e in events if e[3] == "Binding" and e[5] == "1"]
    threads = {int(e[4]) for e in bindings}
    if len(threads) != 2 or any(e[0] != "3" or e[6] != "0" for e in bindings):
        raise ValueError("Linux guest needs one vCPU generation per policy")
    for thread in threads:
        owned = [e for e in events if int(e[4]) == thread and e[3] in ("Running", "Stopped", "GuestEntryBoundary")]
        if {e[3] for e in owned} != {"Running", "Stopped", "GuestEntryBoundary"} or any(e[0] != "3" for e in owned):
            raise ValueError("Linux guest execution or retirement left Host CPU3")
        if max(owned, key=lambda e: (int(e[2]), int(e[1])))[3] != "Stopped":
            raise ValueError("Linux vCPU generation was not stopped")
    reports, windows = {}, {}
    for boot, fields in zip(boots, summaries):
        policy = fields[0]
        start, end, final, checksum, count = map(int, fields[1:])
        if not 0 < int(boot[0]) <= start or any(n % 256 for n in (start, end, final)):
            raise ValueError("Linux startup or report-boundary count is invalid")
        selected, progress = sample_windows(samples, policy, start, end, sample_count)
        if any(n % 256 for row in selected.values() for n in row.values()):
            raise ValueError("Linux sample uses an unreported counter value")
        windows.update(selected)
        reports[policy] = dict(kind="linux_guest_cpu", vm=1, vcpu=0, host_cpu=3,
            guest_cpu=0, pre_rt_start_batches=int(boot[0]), start_batches=start, end_batches=end,
            final_reported_batches=final, checksum=checksum, reports=count, stopped=True,
            interval_reported_iterations=(end-start)*8192, samples_with_progress=progress,
            samples_without_observed_progress=sample_count-progress)
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
        merged.update(windows.get(key, dict(load_before_batches="", load_after_batches="",
                                            load_window_batches="")))
        rows.append(merged)
    return rows, dict(scenario=scenario, loads=loads, ready=ready, clocks=clocks,
                     service_placement=service_placement,
                     limitations=[
                         ("A separate virtualized Linux VM executes on Host CPU3; this does not establish shared-CPU or hardware memory interference." if scenario == "linux_cpu" else "Host workload only; noncritical VM interference remains untested."),
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
