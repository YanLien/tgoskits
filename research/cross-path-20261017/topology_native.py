#!/usr/bin/env python3
"""Validate the sealed primary cohort before the separately named native checks."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from factorial_runner import (
    ARCHIVE, REPO, analyze_run, digest, execute_runs, identity_for, read,
    validate_completed, validate_runtime_sidecars, verify_derived, verify_frozen,
)

PLAN = "configs/topology-native-v3-plan.json"
STATUS = "results/topology-native-v3-status.json"


def require_primary_complete(plan, state, pipeline, expected_sha256):
    """Return registered completed boots only after the primary pipeline is sealed."""
    runs = validate_completed(plan, state, expected_sha256)
    if (pipeline.get("cohort") != plan["cohort"] or not pipeline.get("terminal")
            or not pipeline.get("success") or pipeline.get("phase") != "sealed"):
        raise ValueError("primary statistics, figures and seal must finish successfully first")
    if any(item.get("tasks") != 64 for item in state["completed"]):
        raise ValueError("32 accepted primary boots must contain 2048 task observations")
    return runs


def check_hashes(expected):
    for relative, sha in expected.items():
        if digest(REPO/relative) != sha:
            raise ValueError(f"registered input changed: {relative}")


def verify_primary_seal(plan, state, pipeline):
    """Read the original seal without rerunning its mutating finalizer."""
    summary = read("results/factorial-summary.json")
    audit = read("results/phase12-checkpoint-audit.json")
    if (summary["plan_sha256"] != state["plan_sha256"]
            or (summary["native_boots"], summary["task_observations"]) != (32, 2048)
            or audit.get("cohort") != plan["cohort"]
            or not audit.get("source_and_analysis_identity_verified")
            or (audit["factorial_native_boots"], audit["factorial_task_observations"]) != (32, 2048)):
        raise ValueError("primary summary or checkpoint audit differs from accepted cohort")
    for accepted in state["completed"]:
        output = ARCHIVE/"results"/accepted["name"]
        verify_derived(output, accepted)
        if (digest(ARCHIVE/"raw"/(accepted["name"]+".log")) != accepted["raw_sha256"]
                or digest(output/"analysis-input.log") != accepted["analysis_input_sha256"]):
            raise ValueError("accepted primary measurement bytes changed")
    manifest = ARCHIVE/"SHA256SUMS"
    registered = {}
    for line in manifest.read_text().splitlines():
        sha, relative = line.split("  ", 1)
        path = (REPO/relative).resolve()
        if not path.is_relative_to(ARCHIVE) or relative in registered:
            raise ValueError("invalid primary seal path")
        registered[relative] = sha
    required = ["configs/factorial-recovery-plan.json", "results/factorial-recovery-status.json",
                "results/factorial-summary.json", "results/phase12-checkpoint-audit.json"]
    for accepted in state["completed"]:
        name = accepted["name"]
        required.extend([f"raw/{name}.log", f"results/{name}/analysis-input.log"])
        required.extend(f"results/{name}/{p}" for p in accepted["derived_sha256"])
    if any(str((ARCHIVE/p).relative_to(REPO)) not in registered for p in required):
        raise ValueError("primary seal omits required accepted evidence")
    check_hashes(registered)
    # An ended runner alone is insufficient while its parent still plots/seals.
    for pid in (state["controller_pid"], pipeline["controller_pid"]):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        raise ValueError(f"original controller has not exited: {pid}")
    return digest(manifest)


def check_ready(*, before_apply=False):
    native = read(PLAN)
    original = read("configs/factorial-recovery-plan.json")
    state = read("results/factorial-recovery-status.json")
    pipeline = json.loads(Path("/tmp/phase12-recovery-pipeline-status.json").read_text())
    expected_sha = native["primary_plan_sha256"]
    if digest(ARCHIVE/"configs/factorial-recovery-plan.json") != expected_sha:
        raise ValueError("primary plan changed")
    require_primary_complete(original, state, pipeline, expected_sha)
    check_hashes(native["control_sha256"])
    if before_apply:
        verify_frozen(original)
        check_hashes(native["patch_before_sha256"])
    else:
        check_hashes(native["source_sha256"])
        check_hashes(native["captured_source_sha256"])
        check_hashes(native["patch_after_sha256"])
        # Old source bytes intentionally differ after the reviewed patch;
        # the original control and sealed evidence bytes must still match.
        check_hashes(original["control_sha256"])
    validate_runtime_sidecars(ARCHIVE/"configs/topology-native-v3/board.toml",
                             REPO/"virtualization/axvm/tests/vcpu-runtime/frequency")
    manifest_sha = verify_primary_seal(original, state, pipeline)
    return native, manifest_sha


def check_handoff(name, cpu):
    """Audit the observed post-task protocol separately from task latency."""
    raw = (ARCHIVE/"raw"/(name+".log")).read_text(errors="replace")
    pattern = (r"VIRQ_LINUX_HANDOFF policy=(fair|fifo80) protocol=pause_after_tasks host_cpu=1 "
               r"last_task_observed_ticks=(\d+) pause_requested_ticks=(\d+) "
               r"paused_ticks=(\d+) linux_retired_ticks=(\d+) resumed_ticks=(\d+)")
    markers = re.findall(pattern, raw)
    if cpu == 3:
        if markers:
            raise ValueError("independent CPU3 unexpectedly entered shared-core handoff")
        return {}
    if len(markers) != 2 or {row[0] for row in markers} != {"fair", "fifo80"}:
        raise ValueError("shared-core handoff is missing or duplicated")
    fences = read(f"results/{name}/linux_fence/linux-fence-summary.json")["policies"]
    audit = {}
    for policy, *ticks in markers:
        last, requested, paused, retired, resumed = map(int, ticks)
        observed = re.findall(r"VIRQ_TASK_SAMPLE policy="+policy+r" sample=\d+ [^\r\n]* observed_ticks=(\d+)", raw)
        fence = fences[policy]
        if (len(observed) != 32 or last != max(map(int, observed))
                or not last <= requested <= paused <= fence["end_request_ticks"]
                <= fence["end_observed_ticks"] <= retired <= resumed):
            raise ValueError("shared handoff preceded a task or crossed the End fence")
        audit[policy] = dict(last_task_observed_ticks=last, pause_requested_ticks=requested,
                             paused_ticks=paused, linux_retired_ticks=retired, resumed_ticks=resumed,
                             **fence)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-ready", action="store_true", help="read-only after-patch readiness check")
    mode.add_argument("--before-apply", action="store_true", help="read-only original-source and seal check")
    args = parser.parse_args()
    try:
        plan, seal_sha = check_ready(before_apply=args.before_apply)
    except (ValueError, KeyError, OSError) as error:
        print(f"TOPOLOGY_NATIVE_NOT_READY: {error}", flush=True)
        return 2
    if args.check_ready or args.before_apply:
        print(f"TOPOLOGY_NATIVE_READY before_apply={int(args.before_apply)} primary_seal_sha256={seal_sha}")
        return 0
    plan_sha = digest(ARCHIVE/PLAN)
    if (ARCHIVE/STATUS).exists():
        raise FileExistsError("inspect the existing native status; never restart automatically")
    for run in plan["runs"]:
        name = run["name"]
        if any(path.exists() for path in (ARCHIVE/"raw"/(name+".log"),
                                         ARCHIVE/"configs"/name, ARCHIVE/"results"/name)):
            raise FileExistsError(f"refusing to replace an existing native run: {name}")

    def run_one(run):
        if digest(ARCHIVE/PLAN) != plan_sha:
            raise ValueError("native plan changed during execution")
        _, current_seal = check_ready()
        if current_seal != seal_sha:
            raise ValueError("primary seal identity changed")
        subprocess.run(["sh", str(ARCHIVE/"run-topology-native-timechain.sh"),
                        run["name"], str(run["linux_host_cpu"])], cwd=REPO, check=True)
        check_hashes(plan["source_sha256"])
        check_hashes(plan["captured_source_sha256"])
        check_hashes(plan["control_sha256"])
        fixed, _ = identity_for(run)
        if fixed["fixture"].get("linux_host_cpu") != run["linux_host_cpu"]:
            raise ValueError("generated Linux CPU differs from native registration")
        observed_sources = {**fixed["tests"], **fixed["host"], **fixed["cpu"], **fixed["driver"]}
        if observed_sources != plan["captured_source_sha256"]:
            raise ValueError("captured measurement source differs from native registration")
        accepted = analyze_run(run)
        load = read(f'results/{run["name"]}/load/summary.json')
        if (accepted["tasks"] != 64 or set(load["loads"]) != {"fair", "fifo80"}
                or any(p["host_cpu"] != run["linux_host_cpu"]
                       or not p["runtime_observation"]["time_window_verified"]
                       for p in load["loads"].values())):
            raise ValueError("actual task count or Linux residency is invalid")
        accepted.update(primary_seal_sha256=seal_sha,
                        handoff=check_handoff(run["name"], run["linux_host_cpu"]),
                        scope=plan["scope"], performance_comparison=False)
        return accepted

    execute_runs(plan["runs"], ARCHIVE/STATUS, run_one, plan_sha256=plan_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
