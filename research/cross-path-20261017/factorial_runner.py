#!/usr/bin/env python3
"""Run a preregistered, fail-stop set of independent four-condition blocks."""
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time
import tomllib

from factorial_statistics import balanced_blocks

ARCHIVE = Path(__file__).resolve().parent
REPO = ARCHIVE.parent.parent
ANALYSIS = REPO/"virtualization/axvm/tests/analysis"
COHORT = os.environ.get("FACTORIAL_COHORT", "factorial")
if COHORT not in ("factorial", "factorial-recovery"):
    raise ValueError("unknown factorial cohort")
PLAN_FILE = f"configs/{COHORT}-plan.json"
STATUS_FILE = f"results/{COHORT}-status.json"
SETTINGS = {"0": ("linux_cpu", "off"), "A": ("linux_cpu", "sgi"),
            "B": ("linux_memory", "off"), "AB": ("linux_memory", "sgi")}
DERIVED_INPUTS = ("task/summary.json", "task/samples.csv", "load/summary.json", "runtime/summary.json",
                  "thermal/samples.csv", "frequency/samples.csv", "stage_baseline/samples.json")


def execute_runs(runs, status_path, run_one, *, plan_sha256=None):
    """Persist progress and stop permanently at the first rejected boot."""
    state = dict(controller_pid=os.getpid(), started_unix=time.time(), terminal=False,
                 success=False, active_run=None, completed=[], plan_sha256=plan_sha256)
    with status_path.open("x") as stream:
        json.dump(state, stream, indent=2)

    def save():
        temporary = status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2)+"\n")
        temporary.replace(status_path)

    try:
        for run in runs:
            state["active_run"] = run["name"]
            save()
            print(f'FACTORIAL_BEGIN block={run.get("block")} condition={run.get("condition")} name={run["name"]}', flush=True)
            accepted = run_one(run)
            state["completed"].append(accepted)
            state["active_run"] = None
            save()
            print(f'FACTORIAL_ACCEPTED name={run["name"]}', flush=True)
        state.update(terminal=True, success=True, finished_unix=time.time())
        save()
    except BaseException as error:
        state.update(terminal=True, success=False, error=repr(error), finished_unix=time.time())
        save()
        raise
    return state


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_fit_sha256(data):
    """Hash all original FIT bytes except its single root packaging timestamp."""
    if len(data) < 40:
        raise ValueError("truncated FIT header")
    magic, total, cursor, names, _, version, _, _, names_size, structure_size = struct.unpack(">10I", data[:40])
    end = cursor+structure_size
    if (magic != 0xd00dfeed or total != len(data) or version != 17 or cursor < 40
            or end > total or names+names_size > total):
        raise ValueError("unsupported or invalid FIT layout")
    normalized = bytearray(data)
    depth, timestamps, finished = 0, 0, False
    while cursor+4 <= end:
        token = struct.unpack_from(">I", data, cursor)[0]
        cursor += 4
        if token == 1:
            zero = data.find(b"\0", cursor, end)
            if zero < 0:
                raise ValueError("unterminated FIT node")
            cursor = (zero+4)&~3
            depth += 1
        elif token == 2:
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced FIT nodes")
        elif token == 3:
            if cursor+8 > end or depth < 1:
                raise ValueError("invalid FIT property")
            length, name = struct.unpack_from(">II", data, cursor)
            cursor += 8
            zero = data.find(b"\0", names+name, names+names_size) if name < names_size else -1
            if zero < 0 or cursor+length > end:
                raise ValueError("invalid FIT property name or data bounds")
            if depth == 1 and data[names+name:zero] == b"timestamp":
                if length != 4:
                    raise ValueError("unexpected FIT packaging timestamp width")
                normalized[cursor:cursor+4] = b"\0"*4
                timestamps += 1
            cursor = (cursor+length+3)&~3
        elif token == 4:
            continue
        elif token == 9:
            finished = depth == 0
            break
        else:
            raise ValueError("unknown FIT structure token")
    if not finished or timestamps != 1:
        raise ValueError("FIT must have one root packaging timestamp and balanced structure")
    return hashlib.sha256(normalized).hexdigest()


def read(relative):
    return json.loads((ARCHIVE/relative).read_text())


def validate_completed(plan, state, plan_sha256):
    """Bind complete accepted run identities to the exact registered plan."""
    if not state["terminal"] or not state["success"] or state.get("plan_sha256") != plan_sha256:
        raise ValueError("a successful terminal cohort bound to the original plan is required")
    blocks = plan["blocks"]
    if (plan["independent_blocks"], plan["native_boots"], len(blocks)) != (8, 32, 8):
        raise ValueError("eight complete blocks and 32 boots required")
    if [b["block"] for b in blocks] != list(range(1, 9)) or [b["order"] for b in blocks] != balanced_blocks(plan["seed"]):
        raise ValueError("block ordering differs from preregistration")
    expected = []
    for block in blocks:
        runs = block["runs"]
        if (len(runs) != 4 or [r["condition"] for r in runs] != block["order"]
                or [r["position"] for r in runs] != [1, 2, 3, 4]
                or any(r["block"] != block["block"] for r in runs)):
            raise ValueError("complete block identities or positions changed")
        expected.extend(runs)
    if len({r["name"] for r in expected}) != 32 or len(state["completed"]) != 32:
        raise ValueError("32 unique accepted Host boots required")
    for run, accepted in zip(expected, state["completed"]):
        if any(accepted.get(key) != run[key] for key in ("block", "position", "condition", "name")):
            raise ValueError("accepted boot identity differs from registered block membership")
    return expected


def verify_derived(output, accepted):
    """Reject edited summaries, CSVs or stage rows before statistical use."""
    hashes = accepted.get("derived_sha256")
    if (not hashes or not set(DERIVED_INPUTS).issubset(hashes)
            or any(digest(output/relative) != expected for relative, expected in hashes.items())):
        raise ValueError("accepted derived analysis bytes changed or hashes are missing")


def verify_frozen(plan):
    for relative, expected in {**plan["source_sha256"], **plan["control_sha256"]}.items():
        if digest(REPO/relative) != expected:
            raise ValueError(f"frozen source or control changed: {relative}")


def normalized_linux_vm(text, scenario):
    """Keep shared VM resources distinct from the assigned workload label."""
    config = tomllib.loads(text)
    expected = {"linux_cpu": "linux-ordinary-cpu", "linux_memory": "linux-ordinary-memory"}
    if scenario not in expected or config.get("base", {}).pop("name", None) != expected[scenario]:
        raise ValueError("Linux VM name does not match its assigned workload")
    return config


def validate_runtime_sidecars(board_config, reference_dir):
    """Reject incomplete case directories before any board allocation."""
    for filename in ("guest-builds.toml", "host-initramfs.toml"):
        actual, expected = board_config.parent/filename, reference_dir/filename
        if not actual.is_file() or actual.read_bytes() != expected.read_bytes():
            raise ValueError(f"runtime case needs the frozen preparation/packaging sidecar: {filename}")


def identity_for(run):
    """Verify expected experimental differences and return fixed identities."""
    folder = ARCHIVE/"configs"/run["name"]
    provenance = json.loads((folder/"provenance.json").read_text())
    if provenance["runtime"] != "board" or provenance["exit_code"] != 0:
        raise ValueError("a successful board boot is required")
    if provenance["raw_log_sha256"] != digest(ARCHIVE/"raw"/(run["name"]+".log")):
        raise ValueError("raw boot bytes changed")
    fixture = tomllib.loads((folder/"measurement.toml").read_text())
    scenario, pressure = SETTINGS[run["condition"]]
    expected = dict(scenario=scenario, irq_pressure=pressure, linux_memory_bytes=16777216 if scenario == "linux_memory" else 0)
    if any(fixture.pop(key) != value for key, value in expected.items()):
        raise ValueError("experimental condition differs from preregistration")
    if (fixture["samples"], fixture["recording"], fixture["task_rounds"], fixture["period_us"], fixture["task_deadline_ns"]) != (32, "on", 4096, 20000, 10000000):
        raise ValueError("fixed real-time workload changed")
    environment = [line for line in (folder/"environment.txt").read_text().splitlines()
                   if not line.startswith(("VIRQ_HOST_LOAD=", "VIRQ_IRQ_PRESSURE="))]
    artifacts = {name: digest(folder/name) for name in ("realtime.elf", "realtime.bin", "realtime-input.dtb",
                 "linux-input.dtb", "host-input.dtb", "zephyr.config", "realtime-vm.toml")}
    linux_vm_text = (folder/"linux-vm.toml").read_text()
    linux = json.loads((folder/"linux-build.json").read_text())
    if linux["working_set_bytes"] != expected["linux_memory_bytes"] or not linux["fences_enabled"]:
        raise ValueError("Linux workload differs from assigned B condition")
    for key in ("workload_elf_sha256", "kernel_sha256", "initramfs_sha256"):
        if linux[key] not in provenance["artifact_sha256"].values():
            raise ValueError("Linux build artifact was not captured")
    linux["vm_config_sha256"] = digest(folder/"linux-vm.toml")
    raw = (ARCHIVE/"raw"/(run["name"]+".log")).read_text(errors="replace")
    for pattern, filename in ((r"FIT image ok: (\S+)", "host-boot.fit"), (r"Using DTB from: (\S+)", "host-input.dtb")):
        observed = re.findall(pattern, raw)
        if not observed or provenance["artifact_sha256"].get(observed[-1]) != digest(folder/filename):
            raise ValueError("actual Host boot input does not match captured identity")
    fixed = dict(fixture=fixture, environment=environment, artifacts=artifacts,
                 normalized_linux_vm=normalized_linux_vm(linux_vm_text, scenario),
                 tracked_diff_sha256=digest(folder/"tracked-worktree-before.patch"),
                 status_sha256=digest(folder/"status-before.txt"),
                 tools=(folder/"tool-versions-before-build.txt").read_text().splitlines()[1:],
                 git_commit=provenance["git_commit"], tests=provenance["source_sha256"], host=provenance["host_source_sha256"],
                 cpu=json.loads((folder/"cpu-source-provenance.json").read_text())["source_sha256"],
                 driver=json.loads((folder/"driver-source-provenance.json").read_text())["source_sha256"])
    return fixed, linux


def firmware_for(name):
    """Preserve observed build banners without claiming binary attestation."""
    raw = (ARCHIVE/"raw"/(name+".log")).read_text(errors="replace")
    return dict(uboot_build_banners=sorted(set(re.findall(r"U-Boot \d{4}\.\d{2}[^\r\n]*", raw))),
                bl31_build_banners=sorted(set(re.findall(r"BL31: v[^\r\n]*", raw))),
                exact_firmware_binary_identity_verified=False,
                scope="observed boot/debug and read-only version reply text; missing banners remain absent")


def analyze_run(run):
    name = run["name"]
    output = ARCHIVE/"results"/name
    with (ARCHIVE/"raw"/(name+"-analysis.log")).open("x") as stream:
        subprocess.run(["sh", str(ARCHIVE/"replay-throughput.sh"), name], cwd=REPO, check=True, stdout=stream, stderr=subprocess.STDOUT)
        for kind in ("stages", "probe_cost", "thermal", "frequency", "counter"):
            subprocess.run(["python3", str(ANALYSIS/f"analyze_virq_{kind}.py"), str(output/"analysis-input.log"),
                            "--output-dir", str(output/kind)], cwd=REPO, check=True, stdout=stream, stderr=subprocess.STDOUT)
    decoded = read(f"results/{name}/analysis-input-provenance.json")
    if not decoded["measurement_bytes_unchanged"] or not decoded["decoding_valid_for_analysis"]:
        raise ValueError("analysis must preserve raw measurement bytes")
    probe = read(f"results/{name}/probe_cost/summary.json")
    if not probe["task_observations_valid"] or not probe["complete_chain_accepted"] or probe["recording_mode"] != "on":
        raise ValueError("four-group measurement requires complete recorder-on data")
    if any(policy["samples"] != 32 for policy in probe["policies"].values()):
        raise ValueError("missing task observations")
    for kind in ("thermal", "frequency", "counter"):
        if not read(f"results/{name}/{kind}/summary.json")["observations_available"]:
            raise ValueError("required environmental snapshots are unavailable")
    load = read(f"results/{name}/load/summary.json")
    pressure = read(f"results/{name}/irq_pressure/summary.json")
    if (load["scenario"], pressure["mode"]) != SETTINGS[run["condition"]]:
        raise ValueError("actual pressures differ from assigned condition")
    from stage_baseline import analyze
    rows, stages = analyze((output/"analysis-input.log").read_text())
    stage_dir = output/"stage_baseline"
    stage_dir.mkdir()
    (stage_dir/"summary.json").write_text(json.dumps(stages, indent=2)+"\n")
    (stage_dir/"samples.json").write_text(json.dumps(rows, indent=2)+"\n")
    with (stage_dir/"samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    firmware = firmware_for(name)
    (output/"firmware-observation.json").write_text(json.dumps(firmware, indent=2)+"\n")
    return dict(**run, tasks=len(rows), task_observations_valid=True, firmware=firmware,
                raw_sha256=digest(ARCHIVE/"raw"/(name+".log")),
                analysis_input_sha256=digest(output/"analysis-input.log"),
                derived_sha256={str(path.relative_to(output)): digest(path) for path in output.rglob("*")
                                if path.is_file() and path.suffix in (".json", ".csv")})


def main():
    validate_runtime_sidecars(ARCHIVE/"configs/factorial-board.toml", REPO/"virtualization/axvm/tests/vcpu-runtime/frequency")
    prerequisite = read("results/recorder-ops-status.json")
    finalizer = json.loads(Path("/tmp/recorder-ops-finalizer-status.json").read_text())
    if not prerequisite["terminal"] or not prerequisite["success"] or not finalizer["terminal"] or not finalizer["success"]:
        raise RuntimeError("existing recorder plan and its finalizer must finish successfully first")
    previous = read("configs/recorder-ops-plan.json")
    verify_frozen(previous)
    baseline = read("results/stage-baseline-summary.json")
    if baseline["independent_boots"] != 8:
        raise ValueError("the eight-boot stage baseline must be generated first")
    plan_path, status_path = ARCHIVE/PLAN_FILE, ARCHIVE/STATUS_FILE
    if plan_path.exists() or status_path.exists():
        raise FileExistsError("inspect an existing plan and status; never blindly restart")
    seed = 20261023
    blocks = [dict(block=i+1, order=order, runs=[dict(block=i+1, position=j+1, condition=condition,
              name=f"{COHORT}-board-b{i+1:02d}-{condition.lower()}-32") for j, condition in enumerate(order)])
              for i, order in enumerate(balanced_blocks(seed))]
    controls = dict(previous["control_sha256"])
    for filename in ("factorial_runner.py", "factorial_statistics.py", "summarize-factorial.py", "stage_baseline.py",
                     "summarize-stage-baseline.py", "design/phase12-execution-plan.md", "run-factorial-timechain.sh",
                     "configs/factorial-board.toml", "plot-stage-baseline.py", "plot-phase12.py", "finalize-phase12.py",
                     "run-phase12-pipeline.py", "configs/phase12-plot-requirements.txt", "configs/guest-builds.toml",
                     "configs/host-initramfs.toml"):
        path = ARCHIVE/filename
        controls[str(path.relative_to(REPO))] = digest(path)
    plan = dict(schema_version=1, cohort=COHORT, seed=seed, bootstrap_seed=seed+1, bootstrap_resamples=10000,
        independent_blocks=8, native_boots=32, tasks_per_policy_per_boot=32, blocks=blocks,
        source_sha256=previous["source_sha256"], control_sha256=controls,
        conditions={condition: dict(scenario=s, irq_pressure=p) for condition, (s, p) in SETTINGS.items()},
        primary_metric="scheduled release to calibrated Guest task completion", secondary_metric="observed T0 to calibrated Guest task completion",
        scope="current-EL cross-core dual-VM four-condition hardware observations under recorded environment limitations",
        firmware_observation="RUST_LOG=info,uboot_shell=debug; read-only U-Boot version command; record available U-Boot/BL31 build banners, never infer firmware hashes",
        stopping_rule="stop at the first build, runtime, correctness, loss, identity or analysis failure; preserve incomplete block and original bytes",
        prerequisites={"recorder_audit_sha256": digest(ARCHIVE/"results/recorder-ops-audit.json"),
                       "baseline_summary_sha256": digest(ARCHIVE/"results/stage-baseline-summary.json")},
        limitations=previous["limitations"]+[
            "CPU0..3 A55 only: this cohort does not provide the alternate sharing/affinity topology requested in phase 0.",
            "B substitutes verified memory work for Linux CPU work; the CPU-only control still accesses memory.",
            "Pressure parameters are fixed in this cohort; phase/intensity sensitivity remains separate work.",
            "SGI sender and handler observation also have residual costs not isolated by recorder operations.",
            "Critical Guest work is compute-oriented; a negative result applies only to this workload.",
            "No fixed OPP, continuous frequency/temperature coverage or per-boot U-Boot/BL31 identity proof.",
            "Logical Linux read/write throughput is not a hardware DRAM traffic measurement.",
            "M1/M2 remain false until their full evidence gates are audited."], M1=False, M2=False)
    if COHORT == "factorial-recovery":
        failed = read("results/factorial-status.json")
        failure = read("configs/factorial-infrastructure-failure.json")
        if (not failed["terminal"] or failed["success"] or failed["completed"]
                or failure["original_plan_sha256"] != digest(ARCHIVE/"configs/factorial-plan.json")
                or failure["original_status_sha256"] != digest(ARCHIVE/"results/factorial-status.json")):
            raise ValueError("recovery requires the preserved terminal infrastructure failure with zero accepted data")
        plan["recovery_of"] = failure
    with plan_path.open("x") as stream:
        stream.write(json.dumps(plan, indent=2)+"\n")
    plan_sha256 = digest(plan_path)
    references, linux_references = {}, {}

    def run_one(run):
        if digest(plan_path) != plan_sha256:
            raise ValueError("the registered experiment plan changed")
        verify_frozen(plan)
        scenario, pressure = SETTINGS[run["condition"]]
        subprocess.run(["sh", str(ARCHIVE/"run-factorial-timechain.sh"), run["name"], "board", scenario, pressure, "enabled"],
                       cwd=REPO, check=True, env=dict(os.environ, VIRQ_RECORDING="on"))
        verify_frozen(plan)
        fixed, linux = identity_for(run)
        if "common" not in references:
            references["common"] = fixed
            (ARCHIVE/"configs"/f"{COHORT}-fixed-inputs.json").write_text(json.dumps(fixed, indent=2)+"\n")
        if fixed != references["common"]:
            raise ValueError("fixed critical VM, source, tool or platform identity changed")
        if scenario not in linux_references:
            linux_references[scenario] = linux
            (ARCHIVE/"configs"/f"{COHORT}-{scenario}-inputs.json").write_text(json.dumps(linux, indent=2)+"\n")
        if linux != linux_references[scenario]:
            raise ValueError("Linux input changed within its assigned workload")
        accepted = analyze_run(run)
        host_fit_path = ARCHIVE/"configs"/run["name"]/"host-boot.fit"
        host_fit_sha256 = digest(host_fit_path)
        host_fit_content_sha256 = normalized_fit_sha256(host_fit_path.read_bytes())
        condition_key = "host_fit_"+run["condition"]
        if condition_key not in references:
            references[condition_key] = host_fit_content_sha256
        if host_fit_content_sha256 != references[condition_key]:
            raise ValueError("Host FIT content apart from root packaging timestamp changed within its condition")
        accepted["host_fit_sha256"] = host_fit_sha256
        accepted["host_fit_content_sha256"] = host_fit_content_sha256
        if "firmware" not in references:
            references["firmware"] = accepted["firmware"]
            (ARCHIVE/"configs"/f"{COHORT}-firmware-observations.json").write_text(json.dumps(accepted["firmware"], indent=2)+"\n")
        if accepted["firmware"] != references["firmware"]:
            raise ValueError("observed firmware build banners changed or became unavailable")
        verify_frozen(plan)
        return accepted

    execute_runs([run for block in blocks for run in block["runs"]], status_path, run_one, plan_sha256=plan_sha256)
    print("FACTORIAL_DONE blocks=8 native_boots=32 tasks=2048", flush=True)


if __name__ == "__main__":
    main()
