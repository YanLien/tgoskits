#!/usr/bin/env python3
"""Narrow real-evidence rejection and decoder tests; no synthetic success log."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
OLD = HERE.parents[1] / 'strict-native-phase-v1/AB1-root-final-handoff-v1.json'


class ActualEvidenceTests(unittest.TestCase):
    def setUp(self):
        path = HERE / 'audit.py'
        if not path.exists():
            self.fail('source-bound normal auditor is not implemented')
        spec = importlib.util.spec_from_file_location('normal_audit', path)
        self.audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.audit)

    def test_saved_failed_run_remains_rejected_and_real_wire_is_preserved(self):
        raw = OLD.read_bytes()
        with tempfile.TemporaryDirectory(dir=HERE, prefix='tool-test-') as tmp:
            report = self.audit.audit(OLD, hashlib.sha256(raw).hexdigest(), Path(tmp) / 'out')
        self.assertFalse(report['full_function_passed'])
        self.assertTrue(any('19839' in str(g) for g in report['gates'] if not g['passed']))
        self.assertEqual(len(report['data']), 2)
        self.assertTrue(all(len(d['decoded']['snapshots']) == 2 and
                            len(d['decoded']['slots']) == 32 and
                            not d['known_answer_errors'] for d in report['data']))
        self.assertEqual(report['exit_release']['release'], 'unknown')

    def test_real_data_crc_damage_is_rejected(self):
        handoff = json.loads(OLD.read_text())
        wire = self.audit.load_wire()
        with Path(handoff['files']['raw']['path']).open('rb') as source:
            for raw in source:
                text = self.audit.ANSI.sub('', raw.decode(errors='replace')).rstrip('\r\n')
                if text.startswith('LINUX_PHASE_DATA '):
                    break
            else:
                self.fail('saved real DATA missing')
        cookie = int(text.split('cookie=', 1)[1].split()[0])
        wire['decode_data'](text, cookie)
        damaged = text.replace('crc32=', 'crc32=1', 1)
        with self.assertRaises(AssertionError):
            wire['decode_data'](damaged, cookie)


if __name__ == '__main__':
    unittest.main()
