#!/usr/bin/env python3
"""Validate synthetic SGI delivery, bounded work and joined action retirement."""
import argparse
import json
from pathlib import Path
import re

from analyze_virq_runtime import parse

CONFIG = re.compile(r'VIRQ_IRQ_PRESSURE_CONFIG mode=(off|sgi) intid=15 sender_cpu=2 target_cpu=0 period_us=(\d+) period_ticks=(\d+) burst=(\d+) rounds=64 limit=4096 frequency_hz=(\d+)')
EVENT = re.compile(r'VIRQ_IRQ_PRESSURE_EVENT policy=(fair|fifo80) sequence=(\d+) scheduled_ticks=(\d+) sent_ticks=(\d+) handler_start_ticks=(\d+) handler_end_ticks=(\d+) observed_ticks=(\d+) checksum=(\d+) intid=15 sender_cpu=2 target_cpu=0')
SUMMARY = re.compile(r'VIRQ_IRQ_PRESSURE_SUMMARY policy=(fair|fifo80) sent=(\d+) handled=(\d+) errors=0 start_count=(\d+) end_count=(\d+) window_start_ticks=(\d+) window_end_ticks=(\d+) skipped_periods=(\d+) joined=1 retired=1')


def expected(sequence):
    for _ in range(64):
        sequence = (sequence * 6364136223846793005 + 1) % (1 << 64)
    return sequence


def validate_pressure(log):
    configs = parse(log, 'VIRQ_IRQ_PRESSURE_CONFIG', CONFIG)
    events = parse(log, 'VIRQ_IRQ_PRESSURE_EVENT', EVENT)
    summaries = parse(log, 'VIRQ_IRQ_PRESSURE_SUMMARY', SUMMARY)
    if 'VIRQ_IRQ_PRESSURE_CLEANUP_FAILED' in log:
        raise ValueError('IRQ pressure cleanup failed')
    if not configs:
        if 'VIRQ_IRQ_PRESSURE_' in log:
            raise ValueError('IRQ pressure evidence without configuration')
        return dict(mode='off_legacy', policies={})
    if len(configs) != 1:
        raise ValueError('IRQ pressure needs one configuration')
    mode, period, ticks, burst, frequency = configs[0]
    period, ticks, burst, frequency = map(int, (period, ticks, burst, frequency))
    if not (100 <= period <= 1000000 and 1 <= burst <= 8 and ticks > 0
            and frequency > 0 and ticks == frequency * period // 1000000):
        raise ValueError('Invalid IRQ pressure period, burst or counter frequency')
    result = dict(mode=mode, period_us=period, period_ticks=ticks, burst=burst,
                  frequency_hz=frequency, policies={})
    if mode == 'off':
        if events or summaries:
            raise ValueError('Disabled IRQ pressure has active evidence')
        return result
    if [row[0] for row in summaries] != ['fair', 'fifo80']:
        raise ValueError('IRQ pressure summaries are missing or reordered')
    if [row[0] for row in events] != sorted([row[0] for row in events]):
        raise ValueError('IRQ pressure policy streams are interleaved')
    for policy, sent, handled, before, after, start, end, skipped in summaries:
        sent, handled, before, after, start, end, skipped = map(int, (sent, handled, before, after, start, end, skipped))
        selected = [tuple(map(int, row[1:])) for row in events if row[0] == policy]
        if not (0 < before < after <= sent == handled <= 4096 and 0 < start < end
                and len(selected) == sent):
            raise ValueError('IRQ pressure work, window or completion count mismatch')
        previous, due, in_burst = 0, None, 0
        for index, row in enumerate(selected, 1):
            sequence, planned, posted, begin, finish, observed, checksum = row
            # Burst members share a planned timestamp; only sends/replies are serial.
            if (sequence != index or not planned <= posted <= begin <= finish <= observed
                    or posted < previous or checksum != expected(sequence)):
                raise ValueError('IRQ pressure order, checksum or identity mismatch')
            if planned == due:
                in_burst += 1
            else:
                if due is not None and (planned <= due or (planned-due) % ticks or in_burst != burst):
                    raise ValueError('IRQ pressure schedule is off its period grid')
                due, in_burst = planned, 1
            if in_burst > burst:
                raise ValueError('IRQ pressure burst exceeds configured maximum')
            previous = observed
        if selected[before-1][4] > start or selected[after-1][4] > end:
            raise ValueError('IRQ pressure window counters precede their handler completion')
        if ((before < sent and selected[before][4] < start)
                or (after < sent and selected[after][4] < end)):
            raise ValueError('IRQ pressure window counters omit a completed handler')
        result['policies'][policy] = dict(sent=sent, handled=handled, start_count=before,
            end_count=after, window_start_ticks=start, window_end_ticks=end,
            skipped_periods=skipped, joined=True, retired=True,
            events=[dict(sequence=r[0], scheduled_ticks=r[1], sent_ticks=r[2], handler_start_ticks=r[3],
                         handler_end_ticks=r[4], observed_ticks=r[5], checksum=r[6]) for r in selected])
    return result


def verify_window(pressure, policy, start, end, frequency):
    """Require the same counter and an active source across the observed chain."""
    if pressure['mode'] != 'sgi':
        return
    state = pressure['policies'][policy]
    if pressure['frequency_hz'] != frequency:
        raise ValueError('IRQ pressure and critical chain use different counter frequencies')
    if not state['window_start_ticks'] <= start <= end <= state['window_end_ticks']:
        raise ValueError('IRQ pressure window does not cover the critical observation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    try:
        report = validate_pressure(args.log.read_text())
    except (ValueError, OSError) as error:
        parser.exit(1, f'invalid IRQ pressure: {error}\n')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'policies'}))


if __name__ == '__main__':
    main()
