"""Filesystem contracts for the replay comparator, without hardware or synthetic cohorts."""
import copy
import json
import os
import shutil
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

import intensity_replay as replay


class ComparisonContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old, self.new = (self.root / name for name in ('original', 'restored'))
        for archive in (self.old, self.new):
            (archive / 'results/boot/task').mkdir(parents=True)
            (archive / 'raw').mkdir()
            (archive / 'raw/boot.log').write_bytes(b'captured raw\n')
            self.write(archive / 'results/boot/task/summary.json', {'tasks': 64})
            self.write(archive / 'results/boot/analysis-input-provenance.json',
                       {'raw_path': str(archive / 'raw/boot.log'), 'valid': True})
        self.accepted = {'name': 'boot', 'tasks': 64, 'raw_sha256': replay.digest(self.old / 'raw/boot.log'),
                         'derived_sha256': self.hashes(self.old / 'results/boot')}
        self.record = dict(self.accepted, derived_sha256=self.hashes(self.new / 'results/boot'))

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, indent=2) + '\n')

    @staticmethod
    def hashes(folder):
        return {str(p.relative_to(folder)): replay.digest(p) for p in folder.rglob('*.json')}

    def compare_run(self):
        return replay.compare_run(self.old, self.new, self.accepted, self.record)

    def test_run_allows_only_bound_raw_path_and_rejects_data_changes(self):
        evidence = self.compare_run()
        self.assertEqual(evidence['decoder']['new_sha256'], self.record['derived_sha256']['analysis-input-provenance.json'])
        for filename, value in (('task/summary.json', {'tasks': 63}),
                                ('analysis-input-provenance.json', {'raw_path': str(self.new / 'raw/boot.log'), 'valid': False}),
                                ('analysis-input-provenance.json', {'raw_path': '/wrong/raw.log', 'valid': True})):
            with self.subTest(filename=filename, value=value):
                path = self.new / 'results/boot' / filename
                saved = path.read_bytes()
                self.write(path, value)
                self.record['derived_sha256'] = self.hashes(self.new / 'results/boot')
                with self.assertRaises(ValueError):
                    self.compare_run()
                path.write_bytes(saved)
        self.record['derived_sha256'] = self.hashes(self.new / 'results/boot')
        path = self.old / 'results/boot/task/summary.json'
        self.write(path, {'tasks': 63})
        with self.assertRaises(ValueError):
            self.compare_run()

    def test_drifted_sealed_helper_is_rejected_before_import_side_effects(self):
        archive = self.root / 'sealed-archive'
        archive.mkdir()
        for filename in replay.SEALS:
            shutil.copyfile(Path(replay.__file__).parent / filename, archive / filename)
        marker = self.root / 'helper-was-imported'
        helper = archive / 'frozen_replay.py'
        helper.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("EXECUTED")\n')
        controls = {}
        for name in ('factorial_statistics', 'factorial_runner', 'intensity_sensitivity'):
            path = archive / (name + '.py')
            path.write_text('# Minimal trusted orchestration fixture.\n')
            controls[str(replay.RELATIVE / path.name)] = replay.digest(path)
        (archive / 'summarize-intensity.py').write_text('# Import-only fixture.\n')
        command = ('import json,sys; from pathlib import Path; '
                   'sys.path.insert(0, sys.argv[1]); import intensity_replay as replay; '
                   'replay.frozen_modules(Path(sys.argv[2]), json.loads(sys.argv[3]))')
        environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        result = subprocess.run([sys.executable, '-c', command, str(Path(replay.__file__).parent),
                                 str(archive), json.dumps({'control_sha256': controls})],
                                cwd=self.root, env=environment, text=True, capture_output=True)
        self.assertFalse(marker.exists(), 'drifted helper executed before its sealed identity was checked')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('file identity changed:', result.stderr)
        self.assertIn('frozen_replay.py', result.stderr)

    def test_actual_python_entry_and_import_origins_survive_shutdown(self):
        audit = self.root / 'audit'
        records = self.root / 'records'
        audit.mkdir()
        records.mkdir()
        hook = audit / 'sitecustomize.py'
        hook.write_text(replay.AUDIT_HOOK)
        driver = self.root / 'driver.py'
        driver.write_text('import factorial_probe\n')
        imported = self.root / 'factorial_probe.py'
        imported.write_text('VALUE = 1\n')
        options = audit / 'options.json'
        self.write(options, {'root': str(self.root), 'relative': 'unused',
                   'expected': {str(p.relative_to(self.root)): replay.digest(p) for p in (hook, driver, imported)},
                   'records': str(records)})
        environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
        environment.update(PYTHONPATH=str(audit), PYTHONDONTWRITEBYTECODE='1',
                           INTENSITY_REPLAY_AUDIT_OPTIONS=str(options))
        subprocess.run([sys.executable, str(driver)], env=environment, cwd=self.root, check=True,
                       capture_output=True)
        evidence = json.loads(next(records.glob('*.json')).read_text())
        self.assertEqual(evidence['errors'], [])
        self.assertIn('__main__', evidence['modules'])
        self.assertEqual(evidence['modules']['__main__'], {'path': str(driver), 'sha256': replay.digest(driver)})
        self.assertEqual(evidence['modules']['factorial_probe'], {'path': str(imported), 'sha256': replay.digest(imported)})

    def test_full_json_only_accepts_actual_state_decoder_and_pdf_bindings(self):
        proof = self.compare_run()
        for archive in (self.old, self.new):
            self.write(archive / 'results/intensity-v3-status.json', {'completed': [self.accepted], 'offline': archive == self.new})
            (archive / 'results/figure.pdf').write_bytes(b'%PDF representation ' + archive.name.encode())
        old = {'status_sha256': replay.digest(self.old / 'results/intensity-v3-status.json'),
               'accepted_runs': [copy.deepcopy(self.accepted)], 'statistic': 1.25,
               'figures': {'figure.pdf': {'sha256': replay.digest(self.old / 'results/figure.pdf'), 'source_tables_sha256': {}}}}
        new = copy.deepcopy(old)
        new['status_sha256'] = replay.digest(self.new / 'results/intensity-v3-status.json')
        new['accepted_runs'] = [copy.deepcopy(self.record)]
        new['figures']['figure.pdf']['sha256'] = replay.digest(self.new / 'results/figure.pdf')
        original_copy = copy.deepcopy(old)
        replay.compare_summary_json(old, new, self.old, self.new, [proof])
        self.assertEqual(old, original_copy)
        for key, value in (('statistic', 2), ('status_sha256', 'unbound')):
            changed = copy.deepcopy(new)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                replay.compare_summary_json(old, changed, self.old, self.new, [proof])
        changed = copy.deepcopy(new)
        changed['figures']['figure.pdf']['sha256'] = 'unbound'
        with self.assertRaises(ValueError):
            replay.compare_summary_json(old, changed, self.old, self.new, [proof])
        changed = copy.deepcopy(new)
        changed['accepted_runs'][0]['derived_sha256']['analysis-input-provenance.json'] = 'unbound'
        with self.assertRaises(ValueError):
            replay.compare_summary_json(old, changed, self.old, self.new, [proof])


if __name__ == '__main__':
    unittest.main()
