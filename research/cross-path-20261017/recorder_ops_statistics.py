"""Whole-pair endpoint bootstrap; inputs contain one observation per boot pair."""
import math
import random
import statistics


def paired_endpoints(rows, seed, resamples=10000):
    if len(rows) < 2 or len({r['block'] for r in rows}) != len(rows):
        raise ValueError('independent, uniquely identified boot pairs required')
    if resamples < 1:
        raise ValueError('positive bootstrap sample count required')
    for r in rows:
        low, high = r['latency_difference_lower_ns'], r['latency_difference_upper_ns']
        if not math.isfinite(low) or not math.isfinite(high) or low > high:
            raise ValueError('finite ordered pair endpoints required')
    rng = random.Random(seed)
    lows, highs = [], []
    for _ in range(resamples):
        draw = [rows[rng.randrange(len(rows))] for _ in rows]
        lows.append(statistics.mean(r['latency_difference_lower_ns'] for r in draw))
        highs.append(statistics.mean(r['latency_difference_upper_ns'] for r in draw))
    lows.sort()
    highs.sort()
    return dict(independent_pairs=len(rows), bootstrap_seed=seed, bootstrap_resamples=resamples,
        latency_on_minus_off_mean_lower_ns=statistics.mean(r['latency_difference_lower_ns'] for r in rows),
        latency_on_minus_off_mean_upper_ns=statistics.mean(r['latency_difference_upper_ns'] for r in rows),
        paired_bootstrap_95_lower_ns=lows[math.ceil(.025*resamples)-1],
        paired_bootstrap_95_upper_ns=highs[math.ceil(.975*resamples)-1])
