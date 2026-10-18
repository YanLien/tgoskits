#!/usr/bin/env python3
"""Render standalone scientific figures from the accepted hardware cohort."""
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/crosspath-matplotlib-cache")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from factorial_runner import ARCHIVE, PLAN_FILE, STATUS_FILE, digest, validate_completed
from factorial_statistics import CONDITIONS


def main():
    report_path = ARCHIVE/"results/factorial-summary.json"
    report = json.loads(report_path.read_text())
    status = json.loads((ARCHIVE/STATUS_FILE).read_text())
    plan_path = ARCHIVE/PLAN_FILE
    plan = json.loads(plan_path.read_text())
    validate_completed(plan, status, digest(plan_path))
    if report["native_boots"] != 32 or report["plan_sha256"] != digest(plan_path):
        raise ValueError("figures require the fully accepted factorial cohort")
    for filename in ("factorial-run-means.csv", "factorial-task-endpoints.csv", "factorial-environment.csv"):
        if report["derived_tables_sha256"].get(filename) != digest(ARCHIVE/"results"/filename):
            raise ValueError("figure data differs from accepted summary tables")
    output = ARCHIVE/"results/figures"
    output.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42, "ps.fonttype": 42})
    identities = []

    def save(figure, name):
        for suffix in ("pdf", "png"):
            path = output/f"{name}.{suffix}"
            figure.savefig(path, dpi=300, bbox_inches="tight")
            identities.append(dict(path=str(path.relative_to(ARCHIVE)), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        plt.close(figure)

    colors = ("#4c78a8", "#f58518", "#54a24b", "#e45756")
    figure, axes = plt.subplots(1, 2, figsize=(8, 3.2), sharey=True)
    for ax, policy in zip(axes, ("fair", "fifo80")):
        groups = [report["conditions"][policy][c]["release_to_completion"] for c in CONDITIONS]
        lo, hi = ([g[s]["mean"]/1000 for g in groups] for s in ("lower_ns", "upper_ns"))
        mid = [(a+b)/2 for a, b in zip(lo, hi)]
        ax.bar(CONDITIONS, mid, color=colors, yerr=[[(m-a) for a, m in zip(lo, mid)], [(b-m) for b, m in zip(hi, mid)]], capsize=3)
        ax.set(title=policy, xlabel="Condition", ylabel="Release to task completion (µs)")
    figure.suptitle("Run means; whiskers retain clock-offset bounds (8 boots/condition)")
    figure.tight_layout()
    save(figure, "factorial-mean-latency")

    figure, axes = plt.subplots(1, 2, figsize=(8, 3.4), sharey=True)
    for ax, policy in zip(axes, ("fair", "fifo80")):
        effect = report["effects"][policy]["release_to_completion"]
        for row in effect["block_interactions"]:
            lo, hi = (x/1000 for x in row["bounds_ns"])
            ax.plot([row["block"]]*2, [lo, hi], color="#4c78a8", marker="_")
        lo, hi = (x/1000 for x in effect["bootstrap_95_bounds_ns"])
        ax.axhspan(lo, hi, color="#f58518", alpha=.2, label="Whole-block empirical 95% envelope")
        ax.axhline(0, color="black", linewidth=.8)
        ax.set(title=policy, xlabel="Independent complete block", ylabel="Mean interaction AB − A − B + 0 (µs)", xticks=range(1, 9))
        ax.legend(fontsize=7, loc="best")
    figure.suptitle("Interaction of run means; finite-block and calibration limits remain")
    figure.tight_layout()
    save(figure, "factorial-block-interaction")

    with (ARCHIVE/"results/factorial-task-endpoints.csv").open() as stream:
        samples = list(csv.DictReader(stream))
    figure, axes = plt.subplots(1, 2, figsize=(8, 3.4), sharey=True)
    for ax, policy in zip(axes, ("fair", "fifo80")):
        for color, condition in zip(colors, CONDITIONS):
            group = [r for r in samples if r["condition"] == condition and r["policy"] == policy]
            low = sorted(float(r["release_to_completion_lower_ns"])/1000 for r in group)
            high = sorted(float(r["release_to_completion_upper_ns"])/1000 for r in group)
            ranks = [(i+1)/len(group) for i in range(len(group))]
            ax.step(low, ranks, color=color, linewidth=1, where="post", label=condition)
            ax.step(high, ranks, color=color, linewidth=1, where="post", linestyle="--")
        ax.set(title=policy, xlabel="Release to task completion (µs)", ylabel="Empirical cumulative probability")
        ax.legend(title="Condition", fontsize=7)
    figure.suptitle("Descriptive ECDF bounds; 256 jobs/condition, P99.9 equals observed maximum")
    figure.tight_layout()
    save(figure, "factorial-latency-ecdf")

    figure, axes = plt.subplots(1, 2, figsize=(8, 3.2), sharey=True)
    for ax, policy in zip(axes, ("fair", "fifo80")):
        values = [report["conditions"][policy][c]["linux_iterations_per_second_run_mean"]/1e6 for c in CONDITIONS]
        ax.bar(CONDITIONS, values, color=colors)
        ax.set(title=policy, xlabel="0/A: CPU work; B/AB: memory work", ylabel="Linux iterations/s (millions)")
    figure.suptitle("Fenced Linux progress; CPU and memory iterations represent different work")
    figure.tight_layout()
    save(figure, "factorial-linux-throughput")
    metadata = dict(summary_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(),
                    plan_sha256=digest(plan_path), input_tables_sha256=report["derived_tables_sha256"],
                    plot_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    python=sys.version, matplotlib_version=matplotlib.__version__, files=identities,
                    limitations=["Error whiskers in condition means show retained clock-offset bounds, not sampling confidence intervals.",
                                 "The interaction band resamples complete blocks; it does not include physical calibration uncertainty.",
                                 "Descriptive ECDFs pool within-boot tasks without claiming independent repetitions."])
    (output/"figure-provenance.json").write_text(json.dumps(metadata, indent=2)+"\n")
    print(f"PHASE12_FIGURES_OK figures={len(identities)} matplotlib={matplotlib.__version__}")


if __name__ == "__main__":
    main()
