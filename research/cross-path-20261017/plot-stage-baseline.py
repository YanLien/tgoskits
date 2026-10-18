#!/usr/bin/env python3
"""Plot the common unique-association baseline subset without adding overlap."""
import hashlib
import json
import os
from pathlib import Path
os.environ.setdefault("MPLCONFIGDIR", "/tmp/crosspath-matplotlib-cache")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from stage_baseline import ADDITIVE_STAGES

ARCHIVE = Path(__file__).resolve().parent


def main():
    path = ARCHIVE/"results/stage-baseline-summary.json"
    report = json.loads(path.read_text())
    if report["independent_boots"] != 8 or not report["original_finalizer_succeeded"]:
        raise ValueError("a formal eight-boot baseline is required")
    labels = ("T0 to IRQ kick", "IRQ kick to wake", "Wake to Ready", "Ready to Running", "Running to Entry (SW)",
              "Entry (SW) to ISR", "Guest ISR", "ISR end to task start", "Guest task execution")
    plt.rcParams.update({"font.size": 9, "pdf.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False})
    figure, axes = plt.subplots(1, 2, figsize=(9, 4.5), sharex=True, sharey=True)
    for ax, policy in zip(axes, ("fair", "fifo80")):
        group = report["policies"][policy]
        distributions = [group["conditional_distributions_ns"][metric] for metric in ADDITIVE_STAGES]
        low, high = ([d[side]["mean"]/1000 for d in distributions] for side in ("lower", "upper"))
        mid = [(a+b)/2 for a, b in zip(low, high)]
        ax.barh(range(len(labels)), mid, xerr=[[m-a for m, a in zip(mid, low)], [b-m for b, m in zip(high, mid)]],
                color="#4c78a8", capsize=2)
        ax.set(yticks=range(len(labels)), yticklabels=labels, xlabel="Conditional mean duration (µs)",
               title=f'{policy}: {group["full_chain_samples"]}/{group["samples"]} unique chains')
    axes[0].invert_yaxis()
    figure.suptitle("Eight-boot stage baseline: Host route overlap is excluded from the serial sum")
    figure.tight_layout()
    output = ARCHIVE/"results/figures"
    output.mkdir(exist_ok=True)
    files = []
    for suffix in ("pdf", "png"):
        target = output/f"stage-baseline.{suffix}"
        figure.savefig(target, dpi=300, bbox_inches="tight")
        files.append(dict(path=str(target.relative_to(ARCHIVE)), sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    plt.close(figure)
    metadata = dict(summary_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    matplotlib_version=matplotlib.__version__, files=files,
                    limitations=["Whiskers are retained offset endpoint bounds, not sampling confidence intervals.",
                                 "All displayed stages use the same unique-association subset per policy.",
                                 "Software entry and Guest task completion are not hardware ERET or device output."])
    (output/"stage-baseline-figure-provenance.json").write_text(json.dumps(metadata, indent=2)+"\n")
    print("STAGE_BASELINE_FIGURE_OK formats=pdf,png")


if __name__ == "__main__":
    main()
