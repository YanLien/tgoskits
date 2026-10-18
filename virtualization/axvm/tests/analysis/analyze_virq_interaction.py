"""Mean-latency interaction from independent, complete experimental blocks.

Each list contains one mean per independent run, in matching block order.
A block contains four runs (0, A, B, AB), with randomized order within the
block. Bootstrap whole blocks: events within a run are not independent
replicates. Intervals describe sampling uncertainty under this design; they
do not incorporate counter calibration error or establish a causal mechanism.
"""

import math
from numbers import Real
import random
import statistics


def _latency(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("latency means must be real numbers, not labels or booleans")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("latency means must be finite and nonnegative")
    return number


def interaction_effect(baseline, irq, memory, joint):
    """Return mean(AB)-mean(A)-mean(B)+mean(0), in the input units."""
    baseline, irq, memory, joint = map(_latency, (baseline, irq, memory, joint))
    try:
        contrast = math.fsum((joint, -irq, -memory, baseline))
    except OverflowError as error:
        raise ValueError("interaction is outside the finite numeric range") from error
    if not math.isfinite(contrast):
        raise ValueError("interaction is outside the finite numeric range")
    return contrast


def _percentile(ordered, fraction):
    position = fraction * (len(ordered)-1)
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper]-ordered[lower])*(position-lower)


def summarize_replicates(baseline, irq, memory, joint, *, seed=0, bootstrap_samples=10000):
    """Estimate a mean contrast and paired-block percentile bootstrap interval.

    Callers must supply independent complete blocks, with corresponding runs
    at the same list index. Equal lengths alone cannot prove that design.
    Two blocks permit computation but do not ensure adequate statistical power.
    This function accepts means, never tail quantiles or individual events.
    """
    try:
        groups = [list(map(_latency, values)) for values in (baseline, irq, memory, joint)]
    except TypeError as error:
        raise ValueError("each condition requires a sequence of run means") from error
    n = len(groups[0])
    if n < 2 or any(len(group) != n for group in groups):
        raise ValueError("at least two complete, equal-length experimental blocks are required")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if (isinstance(bootstrap_samples, bool) or not isinstance(bootstrap_samples, int)
            or not 200 <= bootstrap_samples <= 100000):
        raise ValueError("bootstrap_samples must be an integer between 200 and 100000")
    contrasts = [interaction_effect(*block) for block in zip(*groups)]
    rng = random.Random(seed)
    draws = sorted(statistics.mean(rng.choices(contrasts, k=n))
                   for _ in range(bootstrap_samples))
    return {
        "interaction_ns": statistics.mean(contrasts),
        "replicates": n,
        "ci95_low_ns": _percentile(draws, .025),
        "ci95_high_ns": _percentile(draws, .975),
        "block_interactions_ns": contrasts,
        "condition_run_mean_ns": {name: statistics.mean(group) for name, group in
                                  zip(("0", "A", "B", "AB"), groups)},
        "sampling_unit": "independent_complete_block_of_four_runs",
        "bootstrap_samples": bootstrap_samples,
        "seed": seed,
        "interval_method": "paired_complete_block_percentile_bootstrap_95",
        "limitations": [
            "Input values must be mean latencies in ns, with matching independent block identities.",
            "Events within one boot are not independent experimental repetitions.",
            "This interval does not include timestamp calibration uncertainty.",
            "A mean interaction is not by itself proof of causal propagation.",
            "Small repetition counts and autocorrelation can make the bootstrap unreliable.",
        ],
    }
