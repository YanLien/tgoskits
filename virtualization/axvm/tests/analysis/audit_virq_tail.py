#!/usr/bin/env python3
"""Describe interval-valued IRQ tails; audit sample size without asserting IID."""

import argparse
import csv
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path


STRATA = ("policy", "source", "irq_entry_context", "scenario", "intid")
QUANTILES = (Fraction(95, 100), Fraction(99, 100), Fraction(999, 1000))


def minimum_n(p, confidence):
    """Minimum IID n for P(sample maximum >= population p-quantile) >= c."""
    if not 0 < p < 1 or not 0 < confidence < 1:
        raise ValueError("probability and confidence must be between zero and one")
    return math.ceil(math.log1p(-confidence) / math.log(p))


def summarize(intervals):
    if not intervals:
        raise ValueError("empty stratum")
    n = len(intervals)
    lower = sorted(lo for lo, _ in intervals)
    upper = sorted(hi for _, hi in intervals)
    results = {}
    for p in QUANTILES:
        rank = (n * p.numerator + p.denominator - 1) // p.denominator
        results[str(float(p))] = {
            "empirical_nearest_rank": rank,
            "empirical_quantile_interval_ns": [lower[rank - 1], upper[rank - 1]],
            "is_sample_max_rank": rank == n,
            "iid_hypothetical_expected_observations_above_quantile": float(n * (1 - p)),
            "iid_hypothetical_max_covers_population_quantile_probability":
                -math.expm1(n * math.log(float(p))),
            "iid_min_n_for_95pct_one_sided_max_bound": minimum_n(float(p), .95),
            "population_quantile_bound_claimed": False,
        }
    return {"observations": n, "maximum_interval_ns": [lower[-1], upper[-1]],
            "quantiles": results}


def audit(path, metric):
    raw = path.read_bytes()
    groups = {}
    decomposition_counts = {}
    seen = set()
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        required = {*STRATA, "sample", "complete", metric + "_lower_ns", metric + "_upper_ns"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("CSV lacks required physical-analysis interval/identity fields")
        for row in reader:
            if row["complete"] not in ("True", "False") or any(not row[k] for k in STRATA):
                raise ValueError("invalid decomposition flag or missing stratum identity")
            # A sample ID is unique within each policy, even across entry contexts.
            identity = (row["policy"], int(row["sample"]))
            if identity in seen or identity[1] < 1:
                raise ValueError("duplicate or invalid sample identity")
            seen.add(identity)
            lo, hi = (int(row[metric + suffix]) for suffix in ("_lower_ns", "_upper_ns"))
            if not 0 <= lo <= hi:
                raise ValueError("invalid latency interval")
            key = tuple(row[k] for k in STRATA)
            groups.setdefault(key, []).append((lo, hi))
            decomposition_counts.setdefault(key, {"True": 0, "False": 0})[row["complete"]] += 1
    if not groups:
        raise ValueError("empty CSV")
    return {
        "input": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "metric": metric,
        "iid_stationarity_and_independence_verified": False,
        "inference_status": "descriptive only; IID probabilities are hypothetical planning diagnostics",
        "clock_intervals_are_not_sampling_confidence_intervals": True,
        "pooled_across_runs": False,
        "strata": [dict(identity=dict(zip(STRATA, key)),
                        schedule_decomposition_counts=decomposition_counts[key], **summarize(values))
                   for key, values in sorted(groups.items())],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--metric", default="entry_to_c_isr",
                        choices=("entry_to_c_isr", "arm_to_c_isr"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.csv, args.metric)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
