#!/usr/bin/env python3
"""Source-bound read-only native function audit; never launches a target."""
import argparse
import ast
from collections import Counter, defaultdict
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zlib

HERE = Path(__file__).resolve().parent
CONTRACT_SHA = '8ff5e4a14fc159d0b0ec81bd26c00fe1860c62611d9e6a0f38c15989e6518d0e'
SOURCE_SHA = '0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb'
FREEZE_SHA = '0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8'
MASK = (1 << 64) - 1
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
MARKER = re.compile(r'(?<![A-Za-z0-9_])(?:VIRQ_[A-Z0-9_]+|LINUX_(?:PHASE|FENCE|LOAD|MEMORY)_[A-Z0-9_]+|AXTEST_[A-Z_]+|AXVM_TEST_FAILED|SOFTWARE VIRQ (?:COMPLETE|FAIL))(?= |$)')
EXPLICIT = re.compile(r'AXVM_TEST_FAILED|VIRQ_TEST_FAILED|AXTEST_SUITE_FAIL|AXTEST_CASE status=fail|LINUX_LOAD_FAILED|SOFTWARE VIRQ FAIL|VCPU_PERF_FAIL|GPIO_SET_ERROR|BENCHER_GPIO_FAILED|BENCHER_FIFO_FAILED|MEASUREMENT_FAILED|panicked at|Kernel panic|Unhandled exception|VIRQ_IRQ_PRESSURE_CLEANUP_FAILED|VIRQ_CONSOLE_INCOMPLETE|runtime trace lost records|capacity exhausted|^Traceback \(most recent call last\):|^Error:|^error:|^subprocess\.CalledProcessError:')
CANDIDATE = re.compile(r'(?i)\b(?:error|failed|failure|panic|exception)\b|(?:errors|dropped|incomplete)=[1-9]\d*')
NONZERO_ERROR = re.compile(r'(?<![A-Za-z0-9_])(?:errors|dropped|incomplete)=([0-9]+)(?= |$)')
RUN = re.compile(r'RunId \{ vm: VmKey \{ vm_id: (\d+), generation: (\d+) \}, generation: (\d+) \}')
CASES = {'AB1': (1, 1, 'sgi'), 'AB0': (0, 1, 'sgi'), '0': (0, 0, 'off')}
POLICIES = ('fair', 'fifo80')


class AuditError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise AuditError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify_file(reference):
    """Hash final ordinary bytes in bounded chunks, rejecting links and changes."""
    path = Path(reference['path'])
    need(path.is_absolute() and path.resolve() == path and not path.is_symlink(), 'absolute non-symlink evidence required: ' + str(path))
    need(not any(p in {'proc', '.git', 'cache'} for p in path.parts), 'forbidden live/cache evidence: ' + str(path))
    before = path.stat()
    need(stat.S_ISREG(before.st_mode) and before.st_size <= 536870912, 'ordinary file/size bound: ' + str(path))
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    after = path.stat()
    need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
         (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'evidence changed during hash: ' + str(path))
    need(before.st_size == reference.get('bytes', reference.get('size')) and digest.hexdigest() == reference['sha256'], 'final SHA/size mismatch: ' + str(path))
    return path


def read_bound(reference):
    path = verify_file(reference)
    raw = path.read_bytes()
    need(len(raw) == reference.get('bytes', reference.get('size')) and sha(raw) == reference['sha256'], 'evidence changed during read')
    return raw


def contract():
    path = HERE / 'source-identities.json'
    raw = path.read_bytes()
    need(sha(raw) == CONTRACT_SHA, 'auditor source contract changed')
    return json.loads(raw)


def load_wire():
    """Execute only the four exact pure functions and their literal constants."""
    need(__debug__, 'optimized Python disables required pure decoder assertions')
    ref = contract()['wire']
    tree = ast.parse(read_bound(ref))
    names = {'checksum', 'memory_sum', 'verify_work', 'decode_data'}
    constants = {'MASK', 'WORK_FIELDS', 'SNAPSHOT_FIELDS', 'SLOT_FIELDS', 'RESULT_FIELDS'}
    nodes = [n for n in tree.body if
             (isinstance(n, ast.FunctionDef) and n.name in names) or
             (isinstance(n, ast.Assign) and all(isinstance(t, ast.Name) and t.id in constants for t in n.targets))]
    need({n.name for n in nodes if isinstance(n, ast.FunctionDef)} == names, 'pure wire definitions missing')
    namespace = {'re': re, 'zlib': zlib}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), ref['path'], 'exec'), namespace)
    return namespace


def fields(row):
    text = row['text'].split(' ', 1)[1] if ' ' in row['text'] else ''
    parts = re.findall(r'([A-Za-z0-9_]+)=(.*?)(?= [A-Za-z0-9_]+=|$)', text)
    need(len({k for k, _ in parts}) == len(parts), 'duplicate field at line ' + str(row['line']))
    return dict(parts)


def num(document, key, signed=False):
    value = document[key]
    need(isinstance(value, str) and re.fullmatch(r'-?(?:0|[1-9][0-9]*)' if signed else r'0|[1-9][0-9]*', value), 'invalid integer ' + key)
    result = int(value)
    need(-MASK <= result <= MASK if signed else 0 <= result <= MASK, 'integer overflow ' + key)
    return result


def expected(document, values):
    for key, value in values.items():
        need(document.get(key) == str(value), 'field ' + key + ': expected ' + str(value) + ', got ' + str(document.get(key)))


class Log:
    def __init__(self, reference, output):
        self.rows = defaultdict(list)
        self.explicit, self.candidates, self.diagnostics, self.partial = [], [], [], []
        self.tool_tails = []
        path = verify_file(reference)
        offset = 0
        with path.open('rb') as source, (output / 'observations.jsonl').open('w') as index, (output / 'data.raw').open('wb') as data, (output / 'diagnostics-errors.raw').open('wb') as errors:
            for number, raw in enumerate(source, 1):
                text = ANSI.sub('', raw.decode('utf-8', errors='replace').rstrip('\r\n'))
                row = dict(line=number, offset=offset, bytes=len(raw), sha256=sha(raw))
                offset += len(raw)
                marker = MARKER.search(text)
                candidate = bool(CANDIDATE.search(text))
                classification = None
                if EXPLICIT.search(text):
                    classification = 'explicit-host-or-guest-failure'
                elif marker and (marker.group().endswith(('_FAIL','_FAILED','_FAILURE')) or marker.group().startswith('VIRQ_FAILURE_')):
                    classification = 'known-protocol-failure'
                elif any(int(m[1]) > 0 for m in NONZERO_ERROR.finditer(text)):
                    classification = 'nonzero-error-counter'
                elif marker and 'DIAGNOSTIC' in marker.group():
                    classification = 'diagnostic-failure'
                elif candidate:
                    # Unknown error prose cannot silently become accepted evidence.
                    classification = 'unclassified-reject'
                candidate |= classification is not None
                if marker:
                    row.update(marker=marker.group(), text=text[marker.start():], prefix=text[:marker.start()])
                    self.rows[row['marker']].append(row)
                    if row['marker'] == 'LINUX_PHASE_DATA':
                        data.write(raw)
                    if 'DIAGNOSTIC' in row['marker'] or row['marker'].startswith('VIRQ_FAILURE_'):
                        self.diagnostics.append(row)
                elif candidate:
                    row.update(marker=None, text=text)
                if not raw.endswith(b'\n'):
                    row.setdefault('marker', None)
                    row.setdefault('text', text)
                    if text.strip():
                        # Retain even a prefix such as LINUX_PHA or unknown bytes.
                        self.partial.append(dict(row, reason='nonempty final bytes without LF; no complete protocol/tool-line contract'))
                    else:
                        self.tool_tails.append(dict(row, classification='allowed-whitespace-tool-tail'))
                if candidate:
                    classified = dict(row, text=text, error_classification=classification,
                                      requires_rejection=True)
                    self.candidates.append(classified)
                    if classification != 'unclassified-reject':
                        self.explicit.append(classified)
                if marker or candidate or not raw.endswith(b'\n'):
                    index.write(json.dumps(row, ensure_ascii=False) + '\n')
                if candidate or (not raw.endswith(b'\n') and text.strip()):
                    errors.write(raw)
        verify_file(reference)

    def select(self, marker, policy=None):
        rows = self.rows[marker]
        return [r for r in rows if fields(r).get('policy') == policy] if policy else rows

    def one(self, marker, policy=None):
        rows = self.select(marker, policy)
        need(len(rows) == 1, f'{marker}/{policy}: expected one, observed {len(rows)}')
        return fields(rows[0])

    def samples(self, marker, policy, key='sample', first=1, count=32):
        rows = self.select(marker, policy)
        parsed = [fields(r) for r in rows]
        ids = [num(r, key) for r in parsed]
        counts = Counter(ids)
        missing = [n for n in range(first, first+count) if n not in counts]
        duplicates = [n for n,c in counts.items() if c > 1]
        need(ids == list(range(first, first + count)), f'{marker}/{policy}: expected {count} ordered IDs, observed {len(ids)}; missing={missing[:4]}, duplicates={duplicates[:4]}, first={ids[:2]}, last={ids[-2:]} (all rows retained in observations.jsonl)')
        return parsed


def decode_real_data(log, wire):
    result = []
    for row in log.rows['LINUX_PHASE_DATA']:
        observation = dict(row, known_answer_errors=[])
        try:
            cookie = int(re.search(r' cookie=([1-9][0-9]*) ', row['text'])[1])
            snapshots, slots, outcome = wire['decode_data'](row['text'], cookie)
            observation['decoded'] = dict(snapshots=snapshots, slots=slots, result=outcome)
            observation['raw_r_segment'] = row['text'].split(' payload=', 1)[1].split(';')[-1]
            for kind, values in [('snapshot', snapshots), ('slot', slots)]:
                for i, value in enumerate(values):
                    try:
                        wire['verify_work'](value)
                    except (AssertionError, ValueError, KeyError) as error:
                        observation['known_answer_errors'].append(dict(kind=kind, index=i, reason=str(error)))
        except (AssertionError, ValueError, KeyError, TypeError) as error:
            observation['decode_error'] = type(error).__name__ + ': ' + str(error)
        result.append(observation)
    return result


def policy_data(log, data, policy):
    plans = log.select('VIRQ_LINUX_PHASE_PLAN', policy)
    need(len(plans) == 1, 'missing/duplicate policy PLAN')
    start = plans[0]['line']
    accepts = log.select('VIRQ_LINUX_PHASE_ACCEPT', policy)
    need(len(accepts) == 1, 'missing/duplicate policy ACCEPT')
    selected = [d for d in data if start < d['line'] < accepts[0]['line']]
    need(len(selected) == 1, 'policy must bind exactly one actual DATA before ACCEPT')
    need('decoded' in selected[0] and not selected[0]['known_answer_errors'], 'DATA parse/known-answer failure')
    return selected[0]['decoded']


def validate_fixture(log, case):
    """Reject extra policy/sample records, including records with unknown policy."""
    for marker, count in {'VIRQ_LINUX_PHASE_CONFIG':2, 'VIRQ_LINUX_PHASE_PLAN':2,
                          'VIRQ_LINUX_PHASE_ACK':2, 'VIRQ_LINUX_PHASE_ACCEPT':2,
                          'LINUX_PHASE_DATA':2, 'LINUX_PHASE_READY':2,
                          'LINUX_LOAD_READY':2, 'LINUX_MEMORY_READY':2,
                          'LINUX_FENCE_READY':2, 'LINUX_PHASE_ARMED':2,
                          'LINUX_FENCE_REPLY':4, 'VIRQ_COUNTER_MAPPING':2,
                          'VIRQ_TASK_SAMPLE':64, 'VIRQ_ISR_SAMPLE':64,
                          'VIRQ_HOST_SAMPLE':64, 'VIRQ_PERIODIC_RELEASE':64,
                          'VIRQ_PHYSICAL_ARM':64, 'VIRQ_CLOCK_SAMPLE':128}.items():
        need(len(log.rows[marker]) == count, f'{marker}: expected {count}, observed {len(log.rows[marker])}')
        if marker.startswith('VIRQ_'):
            need(all(fields(r).get('policy') in POLICIES for r in log.rows[marker]), 'unknown policy in '+marker)
    for marker in ('LINUX_LOAD_READY','LINUX_MEMORY_READY','LINUX_LOAD_PROGRESS'):
        for row in log.rows[marker]:
            owners = [policy for policy in POLICIES
                      if log.select('VIRQ_LINUX_PHASE_CONFIG',policy)[0]['line'] < row['line']
                      < log.select('VIRQ_LINUX_PHASE_ACCEPT',policy)[0]['line']]
            need(len(owners) == 1, 'raw workload observation outside an exact policy generation: '+marker)
    expected(log.one('VIRQ_TASK_CONFIG'), dict(protocol=1, rounds=4096, relative_deadline_ns=10000000, wait_mode='blocked'))
    expected(log.one('VIRQ_RECORDING'), dict(mode='on', scope='recorder_operations', version=2))
    expected(log.one('VIRQ_SOURCE'), dict(kind='physical_timer_ppi'))
    expected(log.one('VIRQ_PLATFORM'), dict(kind='orangepi5plus_rk3588', el=2, cpus=4, physical_ppi=30, scheduler_ppi=26))
    expected(log.one('VIRQ_FREQUENCY_CONFIG'), dict(enabled=1, cpus=4))
    expected(log.one('VIRQ_THERMAL_CONFIG'), dict(enabled=1))
    expected(log.one('VIRQ_LINUX_PHASE_FENCE_CONFIG'), dict(version=1, guest_protocol=2, mode='serial', clock='cntvct_el0'))
    if CASES[case][2] == 'off':
        need(not log.rows['VIRQ_IRQ_PRESSURE_EVENT'] and not log.rows['VIRQ_IRQ_PRESSURE_SUMMARY'], 'off case has pressure activity')
    else:
        need(len(log.rows['VIRQ_IRQ_PRESSURE_SUMMARY']) == 2 and all(fields(r).get('policy') in POLICIES for r in log.rows['VIRQ_IRQ_PRESSURE_EVENT']), 'pressure policy groups missing/unknown')
    return dict(policies=list(POLICIES), actual_tasks=64, actual_DATA=2, recording='on', platform='orangepi5plus_rk3588')


def validate_workload(log, policy, b):
    """Check every actual Guest workload row in its policy transcript order.

    Host defers a console prefix until shutdown. Its Guest rows still retain
    their original order; Host PLAN/ACK print positions are not Guest stages.
    """
    start = log.select('VIRQ_LINUX_PHASE_CONFIG',policy)[0]['line']
    end = log.select('VIRQ_LINUX_PHASE_ACCEPT',policy)[0]['line']
    markers = ('LINUX_LOAD_READY','LINUX_MEMORY_READY','LINUX_LOAD_PROGRESS',
               'LINUX_PHASE_READY','LINUX_FENCE_READY','LINUX_PHASE_ARMED',
               'LINUX_PHASE_DATA','LINUX_FENCE_REPLY')
    rows = sorted((row for marker in markers for row in log.rows[marker]
                   if start < row['line'] < end), key=lambda r:r['line'])
    ready = memory_ready = phase_ready = fence_ready = begin = armed = complete = ended = False
    batches, count, zero_access = 0, 0, 0
    wire = load_wire()
    for row in rows:
        marker = row['marker']
        value = fields(row)
        if marker == 'LINUX_LOAD_READY':
            need(not ready and not batches and row['text'] == 'LINUX_LOAD_READY version=3 guest_cpu=0 batch_iterations=8192 report_batches=256', 'workload readiness protocol mismatch')
            ready = True
        elif marker == 'LINUX_MEMORY_READY':
            need(ready and not memory_ready and not batches and row['text'] == 'LINUX_MEMORY_READY version=1 working_set_bytes=16777216 every_batches=1 chunk_words=8192', 'memory readiness protocol/order mismatch')
            memory_ready = True
        elif marker == 'LINUX_PHASE_READY':
            need(ready and memory_ready and not phase_ready and not batches, 'phase readiness before workload/memory readiness or after progress')
            phase_ready = True
        elif marker == 'LINUX_FENCE_READY':
            need(phase_ready and not fence_ready and not batches, 'fence readiness order mismatch')
            fence_ready = True
        elif marker == 'LINUX_LOAD_PROGRESS':
            need(ready and memory_ready and fence_ready, 'workload progress before readiness')
            need(set(value) == {'batches','checksum','guest_cpu','memory_batches','logical_bytes','memory_checksum'}, 'workload progress field set mismatch')
            current = num(value,'batches')
            need(current > batches and current % 256 == 0 and current <= MASK//8192, 'workload progress missing/reordered or CPU iteration overflow')
            expected(value,dict(guest_cpu=0,checksum=wire['checksum'](current*8192)))
            chunks = 256*b if complete else 0
            expected(value,dict(memory_batches=chunks,logical_bytes=chunks*8192*16,memory_checksum=wire['memory_sum'](chunks)))
            batches = current
            count += 1
            zero_access += chunks == 0
        elif marker == 'LINUX_FENCE_REPLY':
            need(fence_ready and num(value,'cpu_batches') >= batches > 0, 'fence CPU work precedes observed workload progress')
            if value.get('phase') == 'begin':
                need(not begin and not armed and not complete, 'Begin fence order mismatch')
                begin = True
            else:
                need(value.get('phase') == 'end' and complete and not ended, 'End fence before DATA or duplicate End')
                ended = True
        elif marker == 'LINUX_PHASE_ARMED':
            need(begin and not armed and not complete, 'Guest Arm before Begin or duplicate Arm')
            armed = True
        elif marker == 'LINUX_PHASE_DATA':
            need(armed and not complete and not ended, 'Guest DATA before Arm or duplicate DATA')
            complete = True
    need(ready and memory_ready and phase_ready and fence_ready and begin and armed and complete and ended and count > 0, 'incomplete raw workload lifecycle')
    need(b or count == zero_access, 'B off has actual nonzero progress memory access')
    return dict(progress_reports=count,last_cpu_batches=batches,
                actual_zero_access_reports=zero_access,b_enabled=bool(b),
                scope='all actual readiness/progress rows, CPU known answers and pre/post-DATA memory totals; no throughput estimate')


def validate_policy(log, data, policy, case):
    phase, b, _ = CASES[case]
    plan = log.one('VIRQ_LINUX_PHASE_PLAN', policy)
    ack = log.one('VIRQ_LINUX_PHASE_ACK', policy)
    accept = log.one('VIRQ_LINUX_PHASE_ACCEPT', policy)
    config = log.one('VIRQ_LINUX_PHASE_CONFIG', policy)
    expected(config, dict(version=2, enabled=1, phase=phase, b_enabled=b, count=32, chunks_per_burst=8, working_set_bytes=16777216, every_batches=1, planned_window_ns=640000000, source_prewarm_ns=100000000, profile='production'))
    expected(plan, dict(version=2, vm_id=1, phase=phase, b_enabled=b))
    for label in ('vm_id', 'vm_generation', 'run_generation', 'cookie'):
        need(num(plan, label) > 0, 'zero PLAN generation/cookie')
        expected(ack, {label: plan[label]})
        expected(accept, {label: plan[label]})
    need(plan['cookie'] == plan['run_generation'], 'cookie not bound to Linux run generation')
    expected(ack, dict(version=2, request_before_ticks=plan['request_before_ticks'], host_epoch=plan['host_epoch']))
    hz, offset = num(plan, 'frequency_hz'), num(plan, 'virtual_offset_ticks')
    need(hz > 0 and hz % 4000 == 0, 'frequency does not represent exact Host timing bounds')
    period, epoch, host_epoch = num(plan, 'period_ticks'), num(plan, 'guest_epoch'), num(plan, 'host_epoch')
    need(period == hz // 50 and host_epoch == epoch + offset <= MASK and host_epoch % period == 0, 'Linux/Host shared counter grid mismatch')
    accepted, accepted_host, observed = (num(ack, k) for k in ('accepted_guest_ticks', 'accepted_host_ticks', 'ack_observed_ticks'))
    need(accepted_host == accepted + offset and num(plan, 'request_before_ticks') <= accepted_host <= observed and epoch - accepted >= hz and host_epoch - observed >= hz // 2, 'ACK counter map/causal interval/guard')
    config_line = log.select('VIRQ_LINUX_PHASE_CONFIG', policy)[0]['line']
    accept_line = log.select('VIRQ_LINUX_PHASE_ACCEPT', policy)[0]['line']
    for marker, values in [('LINUX_PHASE_READY',dict(version=2, arm_wire_version=1, result_encoding='table36', test_clock=0, frequency=hz, count=32, chunks_per_burst=8, working_set_bytes=16777216)),
                           ('LINUX_FENCE_READY',dict(version=2, clock='cntvct_el0', frequency=hz)),
                           ('LINUX_PHASE_ARMED',dict(version=2, cookie=plan['cookie'], flags=b, phase=phase, epoch=epoch, frequency=hz, period=period, count=32, chunks_per_burst=8, accepted_ticks=accepted))]:
        rows = [fields(r) for r in log.rows[marker] if config_line < r['line'] < accept_line]
        need(len(rows) == 1, 'missing/repeated actual Guest readiness/arm: '+marker)
        expected(rows[0], values)
    mapping = log.one('VIRQ_COUNTER_MAPPING', policy)
    run = RUN.fullmatch(mapping['run'])
    need(run is not None and int(run[1]) == 2 and int(run[2]) > 0 and int(run[3]) > 0, 'invalid RT generation mapping')
    reset = [r for r in log.rows['VIRQ_LIFECYCLE'] if config_line < r['line'] < accept_line and 'stage=after_reset ' in r['text']]
    need(len(reset) == 1 and RUN.search(reset[0]['text']) is not None and RUN.search(reset[0]['text']).group() == run.group(), 'RT counter mapping belongs to a different actual run')
    rt_offset = num(mapping, 'virtual_offset_ticks')
    need(num(mapping, 'guest_frequency_hz') == hz, 'RT/Linux frequency mismatch')
    probes = []
    for label, first in [('before', 1), ('after', 34)]:
        rows = [fields(r) for r in log.select('VIRQ_CLOCK_SAMPLE', policy) if fields(r).get('phase') == label]
        need([num(r, 'sequence') for r in rows] == list(range(first, first + 32)), 'incomplete before/after calibration ' + label)
        for r in rows:
            expected(r, dict(frequency_hz=hz))
            need(num(r, 'host_before') <= num(r, 'guest_ticks') + rt_offset <= num(r, 'host_after'), 'counter probe outside actual RT mapping')
        probes.extend(rows)
    need(len(log.select('VIRQ_CLOCK_SAMPLE', policy)) == 64, 'additional clock probes')
    low = max(num(r, 'host_before') - num(r, 'guest_ticks') for r in probes)
    high = min(num(r, 'host_after') - num(r, 'guest_ticks') for r in probes)
    need(low <= rt_offset <= high and low == num(mapping, 'offset_low', True) and high == num(mapping, 'offset_high', True) and num(mapping, 'probes') == 64, 'RT offset/calibration intersection mismatch')
    tasks = log.samples('VIRQ_TASK_SAMPLE', policy)
    isrs = log.samples('VIRQ_ISR_SAMPLE', policy)
    releases = log.samples('VIRQ_PERIODIC_RELEASE', policy)
    arms = log.samples('VIRQ_PHYSICAL_ARM', policy)
    log.samples('VIRQ_HOST_SAMPLE', policy)
    for task, isr, release, arm in zip(tasks, isrs, releases, arms):
        expected(task, dict(checksum=1853662840))
        expected(isr, dict(frequency_hz=hz))
        expected(arm, dict(intid=30,cpu=0))
        start, end, seen = (num(task, k) for k in ('start_ticks', 'end_ticks', 'observed_ticks'))
        submitted, guest, guest_end, isr_seen = (num(isr, k) for k in ('submit_ticks', 'guest_ticks', 'guest_end_ticks', 'observed_ticks'))
        need(submitted <= isr_seen <= seen and guest <= guest_end <= start <= end and guest + high >= submitted and guest + low <= isr_seen and guest_end + low <= isr_seen and end + low <= seen and start + high >= submitted, 'T6/ISR Host causality failed sample ' + task['sample'])
        due = host_epoch + (num(task, 'sample') - 1) * period
        need(num(release, 'scheduled_ticks') == due and num(release, 'submitted_ticks') == submitted and num(arm, 'due_ticks') >= due, 'RT releases do not use the shared phase grid')
    decoded = policy_data(log, data, policy)
    workload = validate_workload(log,policy,b)
    snapshots, slots, result = decoded['snapshots'], decoded['slots'], decoded['result']
    expected(result, dict(slots=32, production_ok=1, software_ok=1, test_clock=0, cookie=plan['cookie']))
    for i, snapshot in enumerate(snapshots):
        planned, actual = num(snapshot, 'planned'), num(snapshot, 'actual')
        need(planned == epoch + i * 32 * period and planned <= actual <= MASK - offset and actual - planned <= hz // 4000, 'snapshot violates exact 250us Host boundary')
        need(num(snapshot, 'memory_chunks') == (256 * b if i else 0), 'snapshot cumulative chunks mismatch')
    previous_end = num(snapshots[0], 'actual')
    previous_cpu, previous_chunks = num(snapshots[0], 'cpu_batches'), 0
    for i, slot in enumerate(slots):
        planned, start, end, chunks, cpu = (num(slot, k) for k in ('planned', 'start', 'end', 'memory_chunks', 'cpu_batches'))
        need(planned == epoch + i * period + phase * (period // 2) and planned <= start and previous_end <= start <= end <= num(snapshots[1], 'actual') and end <= MASK - offset, 'slot identity/order/Host mapping')
        need(start - planned <= hz // 4000 and end - start <= hz // 250, 'slot violates exact 250us/4ms Host boundary at ' + str(i))
        need(num(slot, 'chunks') == 8 * b and chunks == previous_chunks + 8 * b and previous_cpu <= cpu <= num(snapshots[1], 'cpu_batches'), 'slot cumulative work mismatch')
        if not b:
            expected(slot, dict(chunks=0, memory_chunks=0, memory_checksum=0, logical_read_bytes=0, logical_write_bytes=0))
        previous_end, previous_cpu, previous_chunks = end, cpu, chunks
    actual = num(snapshots[1], 'actual') - num(snapshots[0], 'actual')
    cpu_delta = num(snapshots[1], 'cpu_batches') - num(snapshots[0], 'cpu_batches')
    expected(result, dict(fixed_cpu_batches=cpu_delta, planned_window_ticks=32 * period, actual_window_ticks=actual, window_delta_ticks=actual - 32 * period))
    expected(accept, dict(version=2, phase=phase, b_enabled=b, slots=32, memory_chunks=256*b, logical_read_bytes=16777216*b, logical_write_bytes=16777216*b, planned_window_ticks=32*period, actual_snapshot_ticks=actual, window_delta_ticks=actual-32*period, cpu_batch_delta=cpu_delta, logical_byte_delta=33554432*b, production_ok=1, software_ok=1, test_clock=0, stopped=1, scope='protocol_resources', trace_pending=1, M2='false', Joint='false'))
    begin, end = num(accept, 'begin_guest_ticks'), num(accept, 'end_guest_ticks')
    first_t6 = num(tasks[0], 'start_ticks') + rt_offset
    last_t6 = num(tasks[-1], 'end_ticks') + rt_offset
    need(num(accept, 'first_t6_host_ticks') == first_t6 and num(accept, 'last_t6_host_ticks') == last_t6 and begin + offset <= min(num(snapshots[0], 'actual')+offset, first_t6) and max(num(snapshots[1], 'actual')+offset, last_t6) <= end + offset, 'whole fence does not contain B/T6')
    need(num(accept, 'begin_request_ticks') <= begin + offset <= num(accept, 'begin_observed_ticks') < num(accept, 'end_request_ticks') <= end + offset <= num(accept, 'end_observed_ticks'), 'Begin/End Host fence causal boundary')
    expected(accept, dict(whole_fence_ticks=end-begin))
    # Guest fences are replayed only after shutdown; bind them by policy DATA span.
    fences = [fields(r) for r in log.rows['LINUX_FENCE_REPLY'] if config_line < r['line'] < accept_line]
    need([r.get('phase') for r in fences] == ['begin', 'end'], 'missing/repeated raw Begin/End fence')
    wire = load_wire()
    for r, ticks in zip(fences, (begin, end)):
        expected(r, dict(version=2, ticks=ticks, frequency=hz))
        wire['verify_work'](r)
    need(0 < num(fences[0], 'cpu_batches') <= num(snapshots[0], 'cpu_batches') <= num(snapshots[1], 'cpu_batches') <= num(fences[1], 'cpu_batches'), 'whole-fence CPU work regressed')
    expected(fences[0], dict(memory_chunks=0, logical_read_bytes=0, logical_write_bytes=0))
    expected(fences[1], dict(memory_chunks=256*b, whole_cpu_batches=num(fences[1], 'cpu_batches')-num(fences[0], 'cpu_batches'), whole_ticks=end-begin))
    expected(accept, dict(whole_cpu_batch_delta=num(fences[1], 'cpu_batches')-num(fences[0], 'cpu_batches')))
    after = [r for r in probes if r['phase'] == 'after']
    need(num(after[0], 'host_before') >= num(accept, 'end_observed_ticks'), 'after calibration precedes Linux End/stop chain')
    return dict(frequency_hz=hz, linux_vm_key=[1, num(plan, 'vm_generation')], linux_run=num(plan, 'run_generation'), rt_vm_key=[2, int(run[2])], rt_run=int(run[3]), t6_count=32, workload=workload, bounds=dict(snapshot_late_ticks=hz//4000, slot_late_ticks=hz//4000, slot_duration_ticks=hz//250), coverage=[min(num(snapshots[0], 'actual')+offset, first_t6), max(num(snapshots[1], 'actual')+offset, last_t6)], host_epoch=host_epoch, rt_offset=rt_offset)


def validate_pressure(log, policy, context, case):
    _, _, mode = CASES[case]
    config = log.one('VIRQ_IRQ_PRESSURE_CONFIG')
    hz = context['frequency_hz']
    expected(config, dict(mode=mode, intid=15, sender_cpu=2, target_cpu=0, period_us=2000, period_ticks=hz//500, burst=2, rounds=64, limit=4096, frequency_hz=hz))
    if mode == 'off':
        need(not log.rows['VIRQ_IRQ_PRESSURE_EVENT'] and not log.rows['VIRQ_IRQ_PRESSURE_SUMMARY'], 'A off has actual pressure events/summary')
        return dict(mode='off', actual_events=0)
    summary = log.one('VIRQ_IRQ_PRESSURE_SUMMARY', policy)
    expected(summary, dict(errors=0, skipped_periods=0, joined=1, retired=1))
    count = num(summary, 'handled')
    need(0 < count <= 4096 and num(summary, 'sent') == count and num(summary, 'end_count') > num(summary, 'start_count') > 0 and num(summary, 'end_count') <= count, 'pressure count/capacity mismatch')
    events = log.samples('VIRQ_IRQ_PRESSURE_EVENT', policy, key='sequence', count=count)
    period = hz // 500
    first_due = context['host_epoch'] - hz // 10
    for i, event in enumerate(events):
        expected(event, dict(intid=15, sender_cpu=2, target_cpu=0))
        sequence = i+1
        value = sequence
        for _ in range(64):
            value = (value * 6364136223846793005 + 1) & MASK
        expected(event, dict(checksum=value, scheduled_ticks=first_due+(i//2)*period))
        times = [num(event, k) for k in ('scheduled_ticks', 'sent_ticks', 'handler_start_ticks', 'handler_end_ticks', 'observed_ticks')]
        need(times == sorted(times), 'pressure event causal order')
    low, high = context['coverage']
    need(num(summary, 'window_start_ticks') <= low <= high <= num(summary, 'window_end_ticks'), 'A does not cover all B/T6')
    return dict(mode='sgi', actual_events=count, skipped_periods=0, coverage=context['coverage'])


@lru_cache(maxsize=1)
def runtime_kinds():
    """Use the exact frozen Rust EventKind declaration as the admitted set."""
    source = read_bound(contract()['diagnostics']).decode()
    declaration = re.search(r'pub enum EventKind\s*\{([^}]+)\}',source)
    need(declaration is not None, 'frozen EventKind enum missing')
    variants = re.findall(r'([A-Za-z][A-Za-z0-9_]*)\s*=\s*([0-9]+)\s*,',declaration[1])
    need(variants and len({name for name,_ in variants}) == len(variants), 'invalid frozen EventKind declaration')
    return frozenset(name for name,_ in variants)


def runtime_event(row):
    """Validate one actual event, including the fixed PPI/current-EL route."""
    event = fields(row)
    order = ('cpu','sequence','ticks','kind','thread','value0','value1')
    need(set(event) == set(order), 'runtime event has missing/extra fields')
    need(row['text'] == 'VIRQ_RUNTIME '+' '.join(key+'='+event[key] for key in order), 'runtime event framing/field order differs')
    need(event['kind'] in runtime_kinds(), 'runtime kind is outside frozen EventKind set: '+event['kind'])
    for key in ('cpu','sequence','ticks','thread','value0','value1'):
        num(event,key)
    need(num(event,'cpu') < 4, 'runtime CPU outside fixture')
    if event['kind'] == 'HostIrqEntry':
        expected(event,dict(cpu=0,thread=0,value0=30,value1=1))
    return event


def validate_trace(log):
    frozen = log.one('VIRQ_TRACE_FROZEN')
    expected(frozen, dict(dropped=0, incomplete=0, vm_groups_retired=2))
    count = num(frozen, 'records')
    events = log.rows['VIRQ_RUNTIME']
    need(len(events) == count and count > 0, f'exported runtime count {len(events)} differs from FROZEN {count}')
    runtime, recording = log.one('VIRQ_RUNTIME_SUMMARY'), log.one('VIRQ_RECORDING_SUMMARY')
    expected(runtime, dict(records=count, dropped=0, incomplete=0))
    expected(recording, dict(mode='on', records=count, dropped=0, incomplete=0, stage_observations='available'))
    sequences = defaultdict(list)
    physical, ready = 0, 0
    freeze_line = log.rows['VIRQ_TRACE_FROZEN'][0]['line']
    for row in events:
        need(row['line'] > freeze_line, 'runtime export precedes freeze')
        event = runtime_event(row)
        cpu = num(event, 'cpu')
        need(cpu < 4, 'runtime CPU outside fixture')
        sequences[cpu].append(num(event, 'sequence'))
        for k in ('ticks', 'thread', 'value0', 'value1'):
            num(event, k)
        physical += event.get('kind') == 'HostIrqEntry'
        ready += event.get('kind') == 'ReadyEnqueue'
    for cpu, ids in sequences.items():
        need(ids == list(range(len(ids))), 'runtime CPU sequence missing/repeated at CPU '+str(cpu))
    need(physical == 64 and ready > 0, 'runtime physical IRQ/ready event completeness')
    expected(log.one('VIRQ_READY_SUMMARY'), dict(records=ready))
    return dict(exported=count, physical_irqs=physical, ready_events=ready, admitted_event_kinds=sorted(runtime_kinds()), physical_route=dict(cpu=0,intid=30,context='current_el',value1=1), per_cpu={str(k):len(v) for k,v in sequences.items()})


def validate_lifecycle(log, contexts):
    retired = log.rows['VIRQ_VM_GROUP_RETIRED']
    need(len(retired) == 2, 'two VM retirement groups required')
    need(len(log.rows['SOFTWARE VIRQ COMPLETE']) == 2, 'two actual RT completions required')
    for i, policy in enumerate(POLICIES):
        need(policy in contexts, 'policy evidence incomplete before retirement')
        expected(fields(retired[i]), dict(count=2, empty=1))
        accept = log.select('VIRQ_LINUX_PHASE_ACCEPT', policy)[0]
        need(accept['line'] < retired[i]['line'] < log.rows['VIRQ_TRACE_FROZEN'][0]['line'], 'retirement/ACCEPT/freeze order')
        complete = log.rows['SOFTWARE VIRQ COMPLETE'][i]
        need(complete['text'] == 'SOFTWARE VIRQ COMPLETE streams=1 samples_each=32 total=32' and complete['line'] < accept['line'], 'RT complete shape/order')
        if i:
            need(retired[i-1]['line'] < log.select('VIRQ_LINUX_PHASE_CONFIG', policy)[0]['line'], 'policy generations overlap retirement')
    need(contexts['fair']['linux_vm_key'] != contexts['fifo80']['linux_vm_key'] and contexts['fair']['rt_vm_key'] != contexts['fifo80']['rt_vm_key'], 'VM generations reused across policy groups')
    return dict(groups=2, VMs_per_group=2, source_contract='Progress.finish -> Fixture.stop -> verify_retired(Inactive) -> after calibration; manager.shutdown before group marker')


def validate_suite(log):
    need(not log.explicit and not log.diagnostics and not log.partial and not any(r['requires_rejection'] for r in log.candidates), 'failure/diagnostic/unclassified error candidate or unframed final bytes observed')
    begin = log.one('AXTEST_BEGIN')
    case = log.one('AXTEST_CASE')
    summary = log.one('AXTEST_SUMMARY')
    need(num(begin, 'total') == 1, 'suite does not contain the exact selected case')
    expected(case, dict(status='pass'))
    need('targeted_interrupts_and_host_policy_survive_reset' in log.rows['AXTEST_CASE'][0]['text'], 'wrong AXTEST case')
    expected(summary, {'total': 1, 'pass': 1, 'fail': 0, 'skip': 0})
    need(len(log.rows['AXTEST_SUITE_OK']) == 1 and log.rows['AXTEST_SUITE_OK'][0]['text'] == 'AXTEST_SUITE_OK', 'missing/malformed suite success')
    order = [log.rows[k][0]['line'] for k in ('AXTEST_BEGIN', 'VIRQ_TRACE_FROZEN', 'VIRQ_RUNTIME_SUMMARY', 'AXTEST_CASE', 'AXTEST_SUMMARY', 'AXTEST_SUITE_OK')]
    need(order == sorted(order), 'incomplete/reordered final suite')
    need(not any(r['line'] > order[-1] for marker, rows in log.rows.items() for r in rows if marker.startswith(('VIRQ_', 'LINUX_', 'AXTEST_'))), 'protocol records after final suite')
    return dict(cases=1, pass_count=1, fail_count=0)


def newc(raw):
    """Decode saved newc without extraction to the filesystem."""
    pos, result, regular = 0, {}, set()
    while pos + 110 <= len(raw):
        need(raw[pos:pos+6] == b'070701', 'newc header')
        values = [int(raw[pos+6+i:pos+14+i], 16) for i in range(0, 104, 8)]
        mode, links, size, namesize = values[1], values[4], values[6], values[11]
        pos += 110
        need(namesize > 0 and pos+namesize <= len(raw), 'newc name bounds')
        name_bytes = raw[pos:pos+namesize]
        need(name_bytes[-1:] == b'\0' and b'\0' not in name_bytes[:-1], 'newc name terminator')
        name = name_bytes[:-1].decode('utf-8')
        pos = (pos+namesize+3)&~3
        need(pos+size <= len(raw), 'newc payload bounds')
        data = raw[pos:pos+size]
        pos = (pos+size+3)&~3
        if name == 'TRAILER!!!':
            need(not size and not mode and not any(raw[pos:]), 'newc trailer/tail')
            return result, regular
        p = PurePosixPath(name)
        need(name and str(p) == name and not p.is_absolute() and '..' not in p.parts and name not in result, 'newc unsafe/duplicate path')
        need(stat.S_IFMT(mode) in (stat.S_IFREG, stat.S_IFDIR), 'newc unexpected member type')
        if stat.S_ISREG(mode):
            need(links == 1, 'newc hardlink')
            regular.add(name)
        result[name] = data
    raise AuditError('newc missing trailer')


def fdt(raw):
    """Read FDT properties and reservation tuples for saved FIT/DTB comparison."""
    need(len(raw) >= 40, 'truncated FDT')
    magic, total, off_struct, off_strings, off_reserve, version, compatible, _, size_strings, size_struct = struct.unpack('>10I', raw[:40])
    need(magic == 0xd00dfeed and 17 <= version and compatible <= 17 and total == len(raw), 'FDT header')
    need(off_struct+size_struct <= total and off_strings+size_strings <= total, 'FDT blocks outside bytes')
    strings = raw[off_strings:off_strings+size_strings]
    pos, stack, props, nodes = off_struct, [], {}, set()
    while pos < off_struct+size_struct:
        token = struct.unpack('>I', raw[pos:pos+4])[0]
        pos += 4
        if token == 1:
            end = raw.index(b'\0', pos)
            stack.append(raw[pos:end].decode())
            pos = (end+4)&~3
            nodes.add('/'+'/'.join(stack[1:]))
        elif token == 2:
            need(bool(stack), 'FDT stack underflow')
            stack.pop()
        elif token == 3:
            size, nameoff = struct.unpack('>II', raw[pos:pos+8]); pos += 8
            need(nameoff < len(strings) and pos+size <= off_struct+size_struct, 'FDT property bounds')
            key = strings[nameoff:strings.index(b'\0', nameoff)].decode()
            pair = ('/'+'/'.join(stack[1:]), key)
            need(pair not in props, 'FDT duplicate property')
            props[pair] = raw[pos:pos+size]; pos = (pos+size+3)&~3
        elif token == 4:
            continue
        elif token == 9:
            need(not stack, 'unclosed FDT nodes')
            break
        else:
            raise AuditError('invalid FDT token')
    reservations = []
    pos = off_reserve
    while pos+16 <= total:
        address, size = struct.unpack('>QQ', raw[pos:pos+16]); pos += 16
        if not address and not size:
            return props, nodes, reservations
        reservations.append((address, size))
    raise AuditError('FDT reservation terminator missing')


def validate_artifacts(documents, log, case):
    capture = documents['capture']
    need(capture.get('artifact_chain_complete') is True and capture.get('errors') == [], 'capture use chain incomplete: '+str(capture.get('errors')))
    need(capture.get('capture_phase') == 'post-exit', 'capture timing provenance missing')
    artifacts = capture['artifacts']
    labels = ('host_elf','host_bin','host_fit','host_preset_dtb','host_initramfs','rt_elf','rt_bin','rt_dtb','guest_dtb','linux_kernel','worker','guest_rootfs','linux_build_json','resources','linux_vm_config','rt_vm_config','zephyr_config')
    verified = {}
    for label in labels:
        row = artifacts[label]
        verified[label] = verify_file(dict(path=row['saved'], bytes=row['bytes'], sha256=row['sha256']))
    # Actual producer paths must occur in the exact raw invocation log, not a rebuilt tree.
    patterns = {'host_elf':r'cargo build elf=(\S+)', 'host_bin':r'kernel from: (\S+)', 'host_fit':r'FIT image ok: (\S+)', 'host_preset_dtb':r'Using DTB from: (\S+)'}
    found = {k:set() for k in patterns}
    packaged = set()
    with verify_file(documents['_raw_reference']).open('rb') as source:
        for raw in source:
            text = ANSI.sub('', raw.decode(errors='replace')).rstrip('\r\n')
            for label, pattern in patterns.items():
                match = re.search(pattern, text)
                if match:
                    found[label].add(match[1])
            match = re.fullmatch(r'Axvisor host initramfs (\S+) sha256=([0-9a-f]{64})', text)
            if match:
                packaged.add(match.groups())
    for label, values in found.items():
        need(values == {artifacts[label]['path']}, 'actual log/use-chain path differs: '+label)
    need(packaged == {(artifacts['host_initramfs']['path'], artifacts['host_initramfs']['sha256'])}, 'final packaged Host initramfs SHA/path differs')
    fit_props, fit_nodes, _ = fdt(verified['host_fit'].read_bytes())
    def string(value):
        need(value.endswith(b'\0') and b'\0' not in value[:-1], 'FIT non-scalar string')
        return value[:-1].decode()
    default = '/configurations/'+string(fit_props[('/configurations','default')])
    components = {}
    for label in ('kernel','ramdisk','fdt'):
        node = '/images/'+string(fit_props[(default,label)])
        payload = fit_props[(node,'data')]
        components[label] = payload
        record = capture['fit_components'][label]
        need(sha(payload) == record['sha256'] and len(payload) == record['bytes'], 'FIT component SHA differs')
        verify_file(dict(path=record['saved'], bytes=record['bytes'], sha256=record['sha256']))
        for child in fit_nodes:
            if child.startswith(node+'/hash') and child.count('/') == node.count('/')+1:
                algo = string(fit_props[(child,'algo')])
                need(algo in ('sha1','sha256','crc32'), 'FIT unknown integrity algorithm')
                digest = (zlib.crc32(payload)&0xffffffff).to_bytes(4,'big') if algo == 'crc32' else hashlib.new(algo,payload).digest()
                need(digest == fit_props[(child,'value')], 'FIT supplied integrity hash mismatch')
    need(sha(components['kernel']) == artifacts['host_bin']['sha256'] and sha(components['ramdisk']) == artifacts['host_initramfs']['sha256'], 'FIT selected kernel/ramdisk differs from used artifacts')
    original_props, original_nodes, original_reservations = fdt(verified['host_preset_dtb'].read_bytes())
    embedded_props, embedded_nodes, embedded_reservations = fdt(components['fdt'])
    start = original_props.pop(('/chosen','linux,initrd-start'), None)
    end = original_props.pop(('/chosen','linux,initrd-end'), None)
    if start is not None and end is not None and len(start) in (4,8) and len(end) in (4,8):
        address, finish = int.from_bytes(start,'big'), int.from_bytes(end,'big')
        if finish >= address:
            original_reservations = [r for r in original_reservations if r != (address,finish-address)]
    need(original_props == embedded_props and original_nodes == embedded_nodes and original_reservations == embedded_reservations, 'FIT FDT differs beyond frozen ostool stale-initrd transform')
    host, _ = newc(components['ramdisk'])
    import tomllib
    vms = {}
    for vm in (1,2):
        names = [name for name in host if name.endswith('/configs/vm-'+str(vm)+'.toml')]
        need(len(names) == 1, 'Host embedded VM config missing/ambiguous')
        vms[vm] = tomllib.loads(host[names[0]].decode())
        need(vms[vm]['base']['id'] == vm, 'Host VM ID differs')
    for label, vm, key in [('rt_bin',2,'kernel_path'),('rt_dtb',2,'dtb_path'),('guest_dtb',1,'dtb_path'),('guest_rootfs',1,'ramdisk_path'),('linux_kernel',1,'kernel_path')]:
        need(sha(host[vms[vm]['kernel'][key].lstrip('/')]) == artifacts[label]['sha256'], 'Host embedded payload differs: '+label)
    need(sha(host['tests/vcpu-runtime.toml']) == artifacts['resources']['sha256'], 'Host embedded resources differ')
    rootfs, regular = newc(gzip.decompress(verified['guest_rootfs'].read_bytes()))
    need(regular == {'bin/busybox','bin/ordinary-load','init'}, 'rootfs must contain exactly three ordinary files')
    for name, checksum in [('bin/busybox','a93cdb45dd0b1abddf72c5c4d7c269316243e23d5479b9117c5dafc57805f96d'),('bin/ordinary-load','b9db9b8fc7925bf2c18e2d9edfbd3c0ee10a5a0f57985151e2f7b0073122ffc2'),('init','c45b529e79f820e58926d461eee79595a841d107d78422af15be412eb96df930')]:
        need(sha(rootfs[name]) == checksum, 'rootfs approved identity differs: '+name)
    need(artifacts['worker']['sha256'] == sha(rootfs['bin/ordinary-load']), 'standalone/embedded worker differ')
    resources = tomllib.loads(verified['resources'].read_text())
    phase, b, pressure = CASES[case]
    fixed = dict(samples=32, recording='on', task_enabled=True, task_wait='blocked', task_deadline_ns=10000000, task_rounds=4096, period_us=20000, scenario='linux_memory', source='physical_timer_ppi', linux_memory_bytes=16777216, linux_memory_every=1, linux_fences_enabled=True, linux_phase_enabled=True, linux_phase_offset=phase, linux_phase_b_enabled=bool(b), linux_host_cpu=3, explicit_dtb_enabled=True, guest_gic_layout='rk3588', service_placement='cpu0', irq_context='current_el', irq_service='off', irq_pressure=pressure, irq_pressure_period_us=2000, irq_pressure_burst=2)
    need(all(type(resources.get(k)) is type(v) and resources[k] == v for k,v in fixed.items()), 'actual embedded resources differ from exact case')
    build = json.loads(verified['linux_build_json'].read_text())
    approved = json.loads(read_bound(contract()['worker_build']))
    keys = ('compiler_version','compiler_path','compiler_sha256','working_set_bytes','memory_every_batches','fences_enabled','phase_enabled','phase_test_clock','source_sha256','explicit_dtb','host_cpu','base_profile','kernel_sha256','base_initramfs_sha256','workload_source_sha256','workload_elf_sha256')
    need(all(build[k] == approved[k] for k in keys), 'actual worker source/compiler/build identity differs')
    inputs = json.loads(read_bound(contract()['inputs']))
    guest = Path(inputs['source'])/'virtualization/axvm/tests/guests/linux-load'
    expected_command = [inputs['environment']['VIRQ_LINUX_CC'],'-O2','-static','-std=c11','-Wall','-Wextra','-Werror',str(guest/'workload.c'),str(guest/'phase.c'),'-o',str(Path(inputs['target'])/'axbuild/axvm/vcpu-runtime/linux/ordinary-load'),'-DLINUX_MEMORY_BYTES=16777216ULL','-DLINUX_MEMORY_EVERY=1','-DLINUX_FENCES=1','-DLINUX_PHASE=1','-DLINUX_PHASE_TEST_CLOCK=0']
    need(build['command'] == expected_command and build['kernel_sha256'] == artifacts['linux_kernel']['sha256'], 'actual worker compile flags/kernel chain differ')
    need(build['dtb_sha256'] == artifacts['guest_dtb']['sha256'] and build['initramfs_sha256'] == artifacts['guest_rootfs']['sha256'], 'actual worker build DTB/rootfs differs')
    return dict(artifact_chain_complete=True, saved_artifacts=len(verified), capture_phase='post-exit', boot_before_identity_verified=False, fit_default=default, scope='actual packaging log and selected FIT/embedded byte chain; no pre-boot observation claimed')


def validate_source(documents, handoff):
    references = contract()
    source_manifest = json.loads(read_bound(references['source_manifest']))
    inputs = json.loads(read_bound(references['inputs']))
    freeze = json.loads(read_bound(references['freeze']))
    need(references['source_manifest']['sha256'] == SOURCE_SHA and references['freeze']['sha256'] == FREEZE_SHA, 'auditor candidate binding differs')
    for name, ref in references.items():
        verify_file(ref)
        path = Path(ref['path'])
        if path.is_relative_to(Path(inputs['source'])):
            need(source_manifest[str(path.relative_to(inputs['source']))] == ref['sha256'], 'specific source differs from approved 702')
    need(handoff.get('source_702_sha256', handoff.get('normal702_sha256')) == SOURCE_SHA and handoff.get('tools_freeze_sha256', handoff.get('freeze_sha256')) == FREEZE_SHA, 'handoff is not bound to new capacity-v2 source/freeze')
    need(handoff['files']['freeze_manifest']['sha256'] == FREEZE_SHA and handoff['files']['frozen_inputs']['sha256'] == references['inputs']['sha256'], 'run supplied older/different freeze/inputs')
    need(freeze['native_once.py']['sha256'] == references['driver_source']['sha256'] and freeze['capture_native.py']['sha256'] == references['capture_source']['sha256'], 'production driver/capture source not frozen')
    command = documents['actual_command']
    environment = dict(inputs['environment'])
    environment.update(next(row['environment'] for row in inputs['cases'] if row['id'] == handoff['case_id']))
    need(command['cwd'] == inputs['source'] and command['argv'] == inputs['argv'] and command['environment'] == environment, 'actual cwd/argv/full environment differs from approved case')
    return dict(source_702_sha256=SOURCE_SHA, tools_freeze_sha256=FREEZE_SHA, specific_source_files=len(references), exact_case_environment=True)


def validate_run_identity(documents, handoff):
    """Bind the original launch, child wait and tool completion to one case.

    Identity is independent of success: a genuinely failed run can have a
    complete identity chain. Zero exits never substitute for this linkage.
    All documents are loaded through the final handoff's exact byte references.
    """
    case = handoff['case_id']
    run, wait = documents['run_result'], documents['root_wait']
    launch, completion = documents['root_launch'], documents['root_tool_completion']
    command, approval, inputs = documents['actual_command'], documents['approval'], documents['frozen_inputs']
    references = handoff['files']
    for label, document in [('run_result',run),('root_wait',wait),('root_launch',launch),('approval',approval)]:
        need(document.get('case_id') == case and case in CASES, 'different/missing case in '+label)
    need(references['frozen_inputs']['sha256'] == contract()['inputs']['sha256'] and
         references['freeze_manifest']['sha256'] == FREEZE_SHA, 'receipt input/freeze binding differs')
    environment = dict(inputs['environment'])
    environment.update(next(row['environment'] for row in inputs['cases'] if row['id'] == case))
    need(command['cwd'] == inputs['source'] and command['argv'] == inputs['argv'] and
         command['environment'] == environment, 'actual xtask command does not belong to exact case')
    need(approval['environment'] == environment and approval['argv'] == inputs['argv'] and
         approval['source_702_sha256'] == SOURCE_SHA and
         approval['candidate_manifest_sha256'] == FREEZE_SHA and
         approval['inputs_sha256'] == references['frozen_inputs']['sha256'], 'approval does not bind exact case/source/freeze/input')
    approval_sha = references['approval']['sha256']
    need(command['approval_sha256'] == launch['approval_sha256'] == approval_sha,
         'actual command/launch approval identity differs')
    expected_driver = ['/usr/bin/python3','-B',str(Path(inputs['execution_tools_root'])/'native_once.py'),
        '--run',case,'--approved-manifest',FREEZE_SHA,'--approval',references['approval']['path'],
        '--approval-sha256',approval_sha,'--source-manifest-sha',SOURCE_SHA]
    need(launch['argv'] == expected_driver and launch['driver']['argv'] == expected_driver and
         wait['driver']['argv'] == expected_driver, 'driver argv does not bind exact run/source/approval/freeze')
    need(launch['cwd'] == inputs['repo_root'] and launch['environment'] == inputs['environment'],
         'driver launch cwd/base environment differs from frozen producer')

    def process_identity(document, label):
        row = document[label]
        need(all(type(row[key]) is int and row[key] > 0 for key in ('pid','pgid')) and
             num(row,'starttime') > 0, 'missing/invalid original process identity: '+label)
        need(isinstance(row['argv'],list) and row['argv'] and
             all(isinstance(arg,str) and arg for arg in row['argv']), 'invalid original process argv: '+label)
        # The retained state snapshot may differ; PID/starttime/argv may not.
        return {key:row[key] for key in ('pid','pgid','starttime','argv')}

    driver = process_identity(launch,'driver')
    supervisor = process_identity(launch,'supervisor')
    need(driver == process_identity(wait,'driver') and supervisor == process_identity(wait,'supervisor'),
         'launch/wait original driver or supervisor identity differs')
    need(type(wait['driver_pid_from_Popen']) is int and wait['driver_pid_from_Popen'] == driver['pid'] and
         driver['pid'] != supervisor['pid'], 'wait does not identify the original direct Popen child')
    need(launch['wait_method'] == wait['wait_method'] and 'Popen.wait' in wait['wait_method'],
         'original direct-child wait method missing/different')
    need(re.fullmatch(r'[0-9a-f]{64}',launch['supervisor_source_sha256']) is not None and
         launch['supervisor_source_sha256'] == wait['supervisor_source_sha256'], 'supervisor source identity differs')
    need(wait['launch_sha256'] == references['root_launch']['sha256'] and
         wait['run_result_sha256'] == references['run_result']['sha256'], 'wait is detached from exact launch/run-result bytes')
    # The completion is the original tool-session attestation. Its receipt SHA
    # links that session to this wait and, transitively, to this exact launch.
    need(completion['driver_Popen_wait_receipt_sha256'] == references['root_wait']['sha256'],
         'original tool completion is detached from exact child wait')
    need(type(completion['original_unified_exec_session']) is int and completion['original_unified_exec_session'] > 0 and
         isinstance(completion['completion_tool_chunk'],str) and completion['completion_tool_chunk'],
         'original tool session/chunk missing')
    driver_exits = [run['driver_return_code'],wait['driver_wait_exit'],
                    completion['driver_Popen_wait_from_own_parent'],handoff['actual_driver_wait_exit']]
    need(all(type(value) is int for value in driver_exits) and len(set(driver_exits)) == 1,
         'driver completion disagrees with original Popen wait')
    root_exit = completion['actual_unified_exec_exit']
    need(type(root_exit) is int and type(handoff['actual_root_wait_exit']) is int and root_exit == handoff['actual_root_wait_exit'],
         'Root exit disagrees with original tool-session completion')
    if 'outer_wait_exit' in wait:
        need(type(wait['outer_wait_exit']) is int and wait['outer_wait_exit'] == root_exit, 'Root wait/completion exit differs')
    need(type(run['xtask_wait_exit']) is int and type(handoff['actual_xtask_wait_exit']) is int and run['xtask_wait_exit'] == handoff['actual_xtask_wait_exit'],
         'xtask exit disagrees with final same-run binding')
    return dict(case_id=case,driver=driver,supervisor=supervisor,
                supervisor_source_sha256=launch['supervisor_source_sha256'],
                root_completion_session=completion['original_unified_exec_session'],
                root_completion_chunk=completion['completion_tool_chunk'],root_wait_exit=root_exit,
                xtask_wait_exit=run['xtask_wait_exit'],driver_wait_exit=driver_exits[0],
                scope='same-run identity only; numerical success and release remain separate gates')


def validate_exit(documents, handoff):
    identity = validate_run_identity(documents,handoff)
    run, wait = documents['run_result'], documents['root_wait']
    need(run.get('xtask_wait_exit') == 0 and run.get('driver_return_code') == 0 and wait.get('driver_wait_exit') == 0, 'actual xtask/driver Popen wait not all zero')
    need(identity['root_wait_exit'] == 0, 'original Root tool-session completion missing/nonzero')
    need('Popen.wait' in wait.get('wait_method',''), 'Root wait is not bound to original Popen child')
    need(handoff.get('forced_stop') is False and handoff.get('forced_signals') == [] and not run.get('outer_timeout') and run.get('cleanup',{}).get('signals') == [] and run.get('cleanup',{}).get('owned_group_empty') is True, 'forced stop/timeout/unknown owned group')
    need(run.get('tool_errors') == [] and run.get('release') == 'explicit-finalize-success', 'actual explicit release is unverified: '+str(run.get('release')))
    refs = contract()
    mod = read_bound(refs['ostool_mod']).decode()
    session = read_bound(refs['ostool_session']).decode()
    need('finalize_session' in mod and 'session.release().await' in mod and 'pub async fn release' in session, 'fixed ostool explicit release contract not found')
    need(wait.get('run_result_sha256') == handoff['files']['run_result']['sha256'], 'actual wait/run-result identity differs')
    return dict(xtask_wait_exit=0, driver_wait_exit=0, root_wait_exit=0, root_completion_session=identity['root_completion_session'], release='explicit-finalize-success', independent_board_tool_wait=run.get('independent_board_tool_wait'), scope='release inferred only from same-run actual unforced zero exits and exact frozen ostool explicit finalize/release propagation')


def audit(handoff_path, handoff_sha256, output):
    raw = Path(handoff_path).read_bytes()
    need(sha(raw) == handoff_sha256, 'Root handoff SHA differs')
    handoff = json.loads(raw)
    need(handoff.get('state') == 'final' and handoff.get('case_id') in CASES, 'only final exact AB1/AB0/0 handoff allowed')
    output = Path(output).absolute()
    need(output.resolve() == output and output.is_relative_to(HERE) and output != HERE and not output.exists(), 'output must be a fresh ordinary auditor child directory')
    output.mkdir()
    (output / 'handoff.json').write_bytes(raw)
    report = dict(schema_version=1, case_id=handoff['case_id'], scope='complete native normal-function audit only; no performance/phase-overlap/I_AB claim', handoff_sha256=handoff_sha256, auditor_sha256=sha(Path(__file__).read_bytes()), full_function_passed=False, source_contract_sha256=CONTRACT_SHA, input_references=handoff['files'], gates=[], data=[], unverified=[], M2=False, Joint=False, goal_complete=False)
    documents = {}
    def gate(name, function):
        try:
            details = function()
            report['gates'].append(dict(name=name, passed=True, evidence=details))
            return details
        except (OSError, ValueError, KeyError, AssertionError, TypeError, OverflowError, struct.error, IndexError, StopIteration) as error:
            report['gates'].append(dict(name=name, passed=False, reason=type(error).__name__+': '+str(error)))
            return None
    for label in ('capture','run_result','root_wait','actual_command','freeze_manifest','frozen_inputs','approval','root_launch','root_tool_completion'):
        document = gate('bound-document-'+label, lambda label=label: json.loads(read_bound(handoff['files'][label])))
        if document is not None:
            documents[label] = document
            # The report refers to complete bound documents; do not duplicate them.
            report['gates'][-1]['evidence'] = handoff['files'][label]
    documents['_raw_reference'] = handoff['files']['raw']
    gate('source-tool-case-binding', lambda: validate_source(documents, handoff))
    gate('same-run-launch-wait-completion-binding', lambda: validate_run_identity(documents,handoff))
    log = gate('final-raw-bytes', lambda: Log(handoff['files']['raw'], output))
    if log is not None:
        report['gates'][-1]['evidence'] = handoff['files']['raw']
        report.update(first_explicit_failure=log.explicit[0] if log.explicit else None, first_error_candidate=log.candidates[0] if log.candidates else None, explicit_failures=log.explicit, diagnostics=log.diagnostics, error_candidates=log.candidates, error_candidate_policy='all candidates classified; unknown error prose rejects pending a source-bound normal contract', protocol_partial_tails=log.partial, allowed_tool_tails=log.tool_tails, marker_counts={k:len(v) for k,v in log.rows.items()})
        gate('complete-exact-fixture-and-policy-records', lambda: validate_fixture(log, handoff['case_id']))
        wire = gate('pure-wire-source', load_wire)
        if wire is not None:
            report['gates'][-1]['evidence'] = dict(reference=contract()['wire'], extracted_functions=['checksum','memory_sum','verify_work','decode_data'], excluded='all imports, Worker, CLI and target execution')
            report['data'] = decode_real_data(log, wire)
        gate('two-complete-raw-DATA', lambda: need(len(report['data']) == 2 and all('decoded' in d and not d['known_answer_errors'] for d in report['data']), 'exactly two decoded actual DATA/R with known answers required'))
        contexts = {}
        for policy in POLICIES:
            context = gate('policy-protocol-'+policy, lambda policy=policy: validate_policy(log, report['data'], policy, handoff['case_id']))
            if context is not None:
                contexts[policy] = context
                gate('pressure-'+policy, lambda policy=policy, context=context: validate_pressure(log, policy, context, handoff['case_id']))
            else:
                report['unverified'].append('pressure-'+policy+': complete policy counter context unavailable')
        gate('single-global-zero-loss-complete-export', lambda: validate_trace(log))
        gate('two-complete-retirement-groups', lambda: validate_lifecycle(log, contexts))
        gate('full-suite-no-additional-failure-or-tail', lambda: validate_suite(log))
        gate('actual-artifact-use-chain', lambda: validate_artifacts(documents, log, handoff['case_id']))
    else:
        report['unverified'].append('all raw protocol, counter, timing, trace, pressure, lifecycle and suite gates')
    run = documents.get('run_result', {})
    wait = documents.get('root_wait', {})
    completion = documents.get('root_tool_completion',{})
    report['exit_release'] = dict(xtask_wait_exit=run.get('xtask_wait_exit'), driver_return_code=run.get('driver_return_code'), driver_wait_exit=wait.get('driver_wait_exit'), root_wait_exit=completion.get('actual_unified_exec_exit'), root_completion_session=completion.get('original_unified_exec_session'), root_completion_chunk=completion.get('completion_tool_chunk'), release=run.get('release','unknown'), independent_board_tool_wait=run.get('independent_board_tool_wait'), forced_signals=handoff.get('forced_signals'), cleanup=run.get('cleanup'))
    gate('actual-exits-and-frozen-explicit-release', lambda: validate_exit(documents, handoff))
    report['full_function_passed'] = bool(report['gates']) and all(g['passed'] for g in report['gates']) and not report['unverified']
    report['unverified'].extend(g['name']+': '+g['reason'] for g in report['gates'] if not g['passed'])
    report['other_case_status'] = {case:'not audited by this report' for case in CASES if case != handoff['case_id']}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handoff', type=Path, required=True)
    parser.add_argument('--handoff-sha256', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit(args.handoff, args.handoff_sha256, args.output_dir)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, 'AUDIT_INPUT_REJECTED '+str(error)+'\n')
    print(json.dumps(dict(case_id=report['case_id'], full_function_passed=report['full_function_passed'], failed_gates=[g['name'] for g in report['gates'] if not g['passed']], report=str(args.output_dir/'report.json'))))
    return 0 if report['full_function_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
