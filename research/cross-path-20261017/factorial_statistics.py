"""Complete-block interaction of run means with outward clock-offset bounds."""
import math
from numbers import Real
import random
import statistics

CONDITIONS = ("0", "A", "B", "AB")


def balanced_blocks(seed):
    """Balance positions and within-block ordered predecessors, twice each."""
    rng = random.Random(seed)
    labels = list(CONDITIONS)
    rng.shuffle(labels)
    rows = [[labels[i] for i in row] for row in ((0, 1, 3, 2), (1, 2, 0, 3), (2, 3, 1, 0), (3, 0, 2, 1)) for _ in range(2)]
    rng.shuffle(rows)
    return rows


def summarize_blocks(blocks, *, seed, resamples=10000):
    """Bootstrap whole independent blocks; never bootstrap within-boot jobs."""
    if len(blocks) < 2 or len({b["block"] for b in blocks}) != len(blocks):
        raise ValueError("at least two independent uniquely identified complete blocks required")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("integer seed required")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or not 200 <= resamples <= 100000:
        raise ValueError("200..100000 bootstrap resamples required")
    contrasts = []
    for block in blocks:
        groups = block["conditions"]
        if set(groups) != set(CONDITIONS):
            raise ValueError("exactly four condition run means required per block")
        for endpoints in groups.values():
            if (len(endpoints) != 2 or any(isinstance(v, bool) or not isinstance(v, Real)
                    or not math.isfinite(v) or v < 0 for v in endpoints) or endpoints[0] > endpoints[1]):
                raise ValueError("finite nonnegative ordered run-mean bounds required")
        low = math.fsum((groups["AB"][0], -groups["A"][1], -groups["B"][1], groups["0"][0]))
        high = math.fsum((groups["AB"][1], -groups["A"][0], -groups["B"][0], groups["0"][1]))
        if not math.isfinite(low) or not math.isfinite(high):
            raise ValueError("interaction endpoints exceed finite range")
        contrasts.append([low, high])
    mean = lambda rows: [statistics.mean(v[side] for v in rows) for side in (0, 1)]
    rng = random.Random(seed)
    draws = [mean(rng.choices(contrasts, k=len(contrasts))) for _ in range(resamples)]
    lows, highs = (sorted(r[side] for r in draws) for side in (0, 1))
    middle = len(contrasts)//2
    return dict(independent_complete_blocks=len(blocks),
        interaction_mean_bounds_ns=mean(contrasts),
        bootstrap_95_bounds_ns=[lows[math.ceil(.025*resamples)-1], highs[math.ceil(.975*resamples)-1]],
        block_interactions=[dict(block=b["block"], bounds_ns=c) for b, c in zip(blocks, contrasts)],
        positive_block_bounds=sum(c[0] > 0 for c in contrasts), negative_block_bounds=sum(c[1] < 0 for c in contrasts),
        first_half_mean_bounds_ns=mean(contrasts[:middle]), second_half_mean_bounds_ns=mean(contrasts[middle:]),
        leave_one_block_out_mean_bounds_ns=[mean(contrasts[:i]+contrasts[i+1:]) for i in range(len(contrasts))],
        sampling_unit="independent_complete_block_of_four_host_boots",
        seed=seed, resamples=resamples, interval_method="paired_complete_block_percentile_endpoint_envelope",
        limitations=["Run mean bounds retain clock-offset intervals, not physical calibration guarantees.",
                     "Eight blocks do not establish bootstrap coverage or adequate power.",
                     "Within-boot jobs and the two fixed-order policies are not independent boot repetitions.",
                     "An interaction does not by itself prove a propagation mechanism."])
