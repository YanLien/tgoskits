#!/usr/bin/env python3
"""Real-record parser rule regressions; never construct a successful Guest/Trace."""
import argparse
import ast
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parents[2]
OLD_HANDOFF = RESEARCH / 'raw/strict-native-phase-v1/AB1-root-final-handoff-v1.json'
TRACE = RESEARCH / 'raw/intensity-v3-b01-irq2x-0-32.log'
TRACE_SHA = 'b7d63e456db20e93756a94f665734afbfb588a69610d24cfa85231bbcc2002f8'
EVIDENCE = []
MODULE = None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def changed_field(raw, key, value):
    changed, count = re.subn(rb'(?<![A-Za-z0-9_])'+key.encode()+rb'=[^ \r\n]+', key.encode()+b'='+str(value).encode(), raw)
    if count != 1:
        raise AssertionError('expected one actual field: '+key)
    return changed


def row_reference(raw, line, offset):
    return dict(line=line, offset=offset, bytes=len(raw), sha256=sha(raw))


def suite_rejection_prefix(module, log):
    """Execute the real suite rejection prefix, before its unrelated suite schema.

    This omits no failure rule: all statements before the first suite lookup are
    selected directly from the implementation AST, with no success markers added.
    """
    tree = ast.parse(Path(module.__file__).read_bytes())
    function = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name == 'validate_suite')
    nodes = []
    for node in function.body:
        if isinstance(node, ast.Assign):
            break
        nodes.append(node)
    namespace = dict(module.__dict__, log=log)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),module.__file__,'exec'),namespace)


def runtime_record_loop(module, row):
    """Execute only the original per-event loop on one recorded event.

    No FROZEN, summary, suite, successful Trace or normal verdict is fabricated.
    The loop and any validators it calls are the actual auditor implementation.
    """
    tree = ast.parse(Path(module.__file__).read_bytes())
    function = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name == 'validate_trace')
    loop = next(n for n in function.body if isinstance(n,ast.For) and isinstance(n.iter,ast.Name) and n.iter.id == 'events')
    namespace = dict(module.__dict__, events=[row], freeze_line=0,
                     sequences=defaultdict(list), physical=0, ready=0)
    exec(compile(ast.Module(body=[loop],type_ignores=[]),module.__file__,'exec'),namespace)


class ReviewRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = MODULE
        handoff_raw = OLD_HANDOFF.read_bytes()
        if sha(handoff_raw) != 'efb44d6c6f98af5c40bf6bd0fd767943468a7c11db19ad6a30304fa13d83ef39':
            raise AssertionError('old final handoff changed')
        handoff = json.loads(handoff_raw)
        cls.reference = handoff['files']['raw']
        cls.raw = cls.module.read_bound(cls.reference)
        cls.wire = cls.module.load_wire()
        cls.work = tempfile.TemporaryDirectory(dir=HERE,prefix='rule-test-')
        cls.root = Path(cls.work.name)
        cls.serial = 0
        cls.original_log = cls.log(cls.raw)
        cls.data = cls.module.decode_real_data(cls.original_log,cls.wire)
        cls.runtime_records = []
        trace_raw = TRACE.read_bytes()
        if sha(trace_raw) != TRACE_SHA:
            raise AssertionError('single actual trace fixture changed')
        offset = 0
        found = set()
        # Match actual LF framing, preserving the source spans of the two rows.
        for line, raw in enumerate(trace_raw.split(b'\n'),1):
            raw += b'\n'
            text = cls.module.ANSI.sub('',raw.decode(errors='replace')).rstrip('\r\n')
            marker = cls.module.MARKER.search(text)
            if marker and marker.group() == 'VIRQ_RUNTIME':
                value = text[marker.start():]
                kind = re.search(r' kind=(\S+)',value)[1]
                if kind in ('Marker','HostIrqEntry') and kind not in found:
                    row = dict(row_reference(raw,line,offset),marker='VIRQ_RUNTIME',text=value,prefix=text[:marker.start()])
                    cls.runtime_records.append(row)
                    found.add(kind)
            offset += len(raw)
            if found == {'Marker','HostIrqEntry'}:
                break
        if found != {'Marker','HostIrqEntry'}:
            raise AssertionError('two actual wire-compatible runtime records missing')

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    @classmethod
    def log(cls, raw):
        cls.serial += 1
        directory = cls.root / str(cls.serial)
        directory.mkdir()
        source = directory / 'fixture.raw'
        source.write_bytes(raw)
        return cls.module.Log(dict(path=str(source),bytes=len(raw),sha256=sha(raw)),directory)

    def actual(self, marker, occurrence=0):
        rows = self.original_log.rows[marker]
        row = rows[occurrence]
        return row, self.raw[row['offset']:row['offset']+row['bytes']]

    def record(self, rule, source, original, mutated, rejected):
        EVIDENCE.append(dict(rule=rule,source=source,
                             original=original.decode(errors='replace'),
                             mutated=mutated.decode(errors='replace'),
                             rejected=rejected,scope='local parser rule only; no normal end-to-end GREEN'))

    def test_failure_candidates_and_unframed_tail_are_rejected(self):
        source, summary = self.actual('VIRQ_IRQ_PRESSURE_SUMMARY')
        data_row, data = self.actual('LINUX_PHASE_DATA')
        cases = [('nonzero-errors',source,summary,changed_field(summary,'errors',1)),
                 ('known-failure-marker',source,summary,summary.replace(b'VIRQ_IRQ_PRESSURE_SUMMARY',b'VIRQ_IRQ_PRESSURE_FAILURE',1)),
                 ('unclassified-error-candidate',source,summary,summary.replace(b'VIRQ_IRQ_PRESSURE_SUMMARY',b'NOTICE failure',1)),
                 ('truncated-protocol-prefix',data_row,data,b'LINUX_PHA')]
        # The intact actual zero-error summary has no failure at this prefix.
        suite_rejection_prefix(self.module,self.log(summary))
        for name, source, original, mutation in cases:
            with self.subTest(rule=name):
                log = self.log(mutation)
                try:
                    suite_rejection_prefix(self.module,log)
                    rejected = False
                except self.module.AuditError:
                    rejected = True
                self.record(name,source,original,mutation,rejected)
                self.assertTrue(rejected,'actual suite rejection prefix silently accepted '+name)
                if log.candidates:
                    self.assertTrue(all(r.get('error_classification') for r in log.candidates),'unclassified error candidate')
                if name == 'truncated-protocol-prefix':
                    self.assertEqual(log.partial[0]['offset'],0)
                    self.assertEqual(log.partial[0]['bytes'],len(mutation))

    def test_entire_raw_workload_protocol_is_checked(self):
        context = self.module.validate_policy(self.original_log,self.data,'fair','AB1')
        self.assertEqual(context['t6_count'],32)
        progress_row, progress = self.actual('LINUX_LOAD_PROGRESS')
        _, late_progress = self.actual('LINUX_LOAD_PROGRESS',6)
        ready_row, ready = self.actual('LINUX_LOAD_READY')
        # v1 did not index MEMORY_READY, so take its real bytes from the same log.
        memory = next(raw for raw in self.raw.split(b'\n') if raw.startswith(b'LINUX_MEMORY_READY '))+b'\n'
        memory_offset = self.raw.index(memory)
        memory_row = row_reference(memory,self.raw[:memory_offset].count(b'\n')+1,memory_offset)
        second_row, second = self.actual('LINUX_LOAD_PROGRESS',1)
        duplicate = changed_field(changed_field(second,'batches',256),'checksum',self.module.fields(progress_row)['checksum'])
        premature = progress
        for key in ('memory_batches','logical_bytes','memory_checksum'):
            value = re.search(rb'(?<!\w)'+key.encode()+rb'=([^ \r\n]+)',late_progress)[1].decode()
            premature = changed_field(premature,key,value)
        cases = [('workload-readiness',ready_row,ready,changed_field(ready,'version',2)),
                 ('memory-readiness',memory_row,memory,changed_field(memory,'every_batches',2)),
                 ('progress-cpu-known-answer',progress_row,progress,changed_field(progress,'checksum',0)),
                 ('progress-guest-cpu',progress_row,progress,changed_field(progress,'guest_cpu',1)),
                 ('progress-monotonic',second_row,second,duplicate),
                 ('progress-memory-before-DATA',progress_row,progress,premature)]
        for name, source, original, mutation in cases:
            with self.subTest(rule=name):
                mutated_raw = self.raw[:source['offset']]+mutation+self.raw[source['offset']+source['bytes']:]
                log = self.log(mutated_raw)
                decoded = self.module.decode_real_data(log,self.wire)
                try:
                    self.module.validate_policy(log,decoded,'fair','AB1')
                    rejected = False
                except (self.module.AuditError,AssertionError):
                    rejected = True
                self.record(name,source,original,mutation,rejected)
                self.assertTrue(rejected,'real policy protocol accepted contradictory '+name)

    def test_runtime_event_schema_and_fixed_physical_route_are_checked(self):
        for row in self.runtime_records:
            runtime_record_loop(self.module,row)
        marker = next(r for r in self.runtime_records if 'kind=Marker ' in r['text'])
        irq = next(r for r in self.runtime_records if 'kind=HostIrqEntry ' in r['text'])
        cases = [('runtime-kind-missing',marker,re.sub(r' kind=\S+','',marker['text'])),
                 ('runtime-kind-closed-set',marker,marker['text'].replace('kind=Marker','kind=Unknown')),
                 ('runtime-field-set',marker,marker['text']+' ignored=1'),
                 ('runtime-intid',irq,re.sub(r'value0=\d+','value0=31',irq['text'])),
                 ('runtime-context',irq,re.sub(r'value1=\d+','value1=2',irq['text'])),
                 ('runtime-irq-cpu',irq,re.sub(r'cpu=\d+','cpu=1',irq['text']))]
        for name, source, mutation in cases:
            with self.subTest(rule=name):
                changed = dict(source,text=mutation)
                try:
                    runtime_record_loop(self.module,changed)
                    rejected = False
                except self.module.AuditError:
                    rejected = True
                self.record(name,dict(path=str(TRACE),sha256=TRACE_SHA,span=source),source['text'].encode(),mutation.encode(),rejected)
                self.assertTrue(rejected,'actual runtime record loop accepted '+name)
        source, arm = self.actual('VIRQ_PHYSICAL_ARM')
        for key, value in [('intid',31),('cpu',1)]:
            with self.subTest(arm=key):
                mutation = changed_field(arm,key,value)
                mutated_raw = self.raw[:source['offset']]+mutation+self.raw[source['offset']+source['bytes']:]
                log = self.log(mutated_raw)
                try:
                    self.module.validate_policy(log,self.module.decode_real_data(log,self.wire),'fair','AB1')
                    rejected = False
                except self.module.AuditError:
                    rejected = True
                self.record('arm-'+key,source,arm,mutation,rejected)
                self.assertTrue(rejected,'actual policy gate accepted wrong ARM '+key)


def main():
    global MODULE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auditor',type=Path,default=HERE/'audit.py')
    parser.add_argument('--evidence',type=Path,required=True)
    args, remaining = parser.parse_known_args()
    spec = importlib.util.spec_from_file_location('reviewed_auditor',args.auditor)
    MODULE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULE)
    program = unittest.main(argv=[__file__]+remaining,exit=False)
    payload = dict(auditor=dict(path=str(args.auditor.resolve()),sha256=sha(args.auditor.read_bytes())),
                   old_raw_reference=json.loads(OLD_HANDOFF.read_text())['files']['raw'],
                   trace_fixture=dict(path=str(TRACE),sha256=TRACE_SHA),
                   tests_run=program.result.testsRun,failures=len(program.result.failures),
                   errors=len(program.result.errors),observations=EVIDENCE,
                   normal_end_to_end_GREEN=False,scope='actual parser rule regressions only; no normal verdict or successful Guest/Trace constructed')
    with args.evidence.open('x') as out:
        out.write(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    return 0 if program.result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
