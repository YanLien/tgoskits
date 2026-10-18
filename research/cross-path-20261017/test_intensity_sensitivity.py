"""Protect assigned pressure, complete sampling and paired sensitivity bounds."""
import copy
from collections import Counter
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

try:
    import intensity_sensitivity as subject
except ModuleNotFoundError as error:
    if error.name != 'intensity_sensitivity':
        raise
    subject = None


class IntensitySensitivity(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(subject, 'the intensity acceptance and pairing boundary is not implemented')

    def test_only_validated_assigned_intensity_is_removed_from_fixed_identity(self):
        def inputs(period, every, condition):
            memory = condition in ('B', 'AB')
            return (dict(fixture=dict(irq_pressure_period_us=period, irq_pressure_burst=2,
                                      linux_memory_every=every if memory else 1,
                                      linux_host_cpu=3, explicit_dtb_enabled=True,
                                      task_rounds=4096),
                         environment=[f'VIRQ_IRQ_PRESSURE_PERIOD_US={period}',
                                      f'VIRQ_LINUX_MEMORY_EVERY={every}', 'VIRQ_SAMPLES=32'],
                         normalized_linux_vm=dict(phys_cpu_sets=[8])),
                    dict(host_cpu=3, working_set_bytes=16777216 if memory else 0,
                         memory_every_batches=every if memory else 1, fences_enabled=True,
                         compiler_version='fixed compiler', base_profile='registry-v0.0.14',
                         kernel_sha256='kernel', base_initramfs_sha256='base',
                         workload_source_sha256='worker'))

        reference, linux = inputs(2000, 1, 'B')
        canonical = subject.normalize_identity(reference, linux, 'reference', 'B')
        for name, period, every, condition in [('irq2x', 1000, 1, 'AB'),
                                               ('memory_sparse', 2000, 8, 'B'),
                                               ('memory_sparse', 2000, 8, '0')]:
            fixed, peer = inputs(period, every, condition)
            before = copy.deepcopy(fixed)
            self.assertEqual(subject.normalize_identity(fixed, peer, name, condition), canonical)
            self.assertEqual(fixed, before)
            broken = copy.deepcopy(fixed)
            broken['fixture']['linux_memory_every'] = 3
            with self.assertRaises(ValueError):
                subject.normalize_identity(broken, peer, name, condition)
        for modify in (lambda f, p: f['fixture'].update(irq_pressure_period_us=500),
                       lambda f, p: f['fixture'].update(irq_pressure_burst=4),
                       lambda f, p: p.update(memory_every_batches=8),
                       lambda f, p: f['environment'].append('VIRQ_LINUX_MEMORY_EVERY=8')):
            fixed, peer = copy.deepcopy((reference, linux))
            modify(fixed, peer)
            with self.assertRaises(ValueError):
                subject.normalize_identity(fixed, peer, 'reference', 'B')
        changed = copy.deepcopy(reference)
        changed['fixture']['task_rounds'] = 8192
        self.assertNotEqual(subject.normalize_identity(changed, linux, 'reference', 'B'), canonical)
        changed = copy.deepcopy(reference)
        changed['normalized_linux_vm']['phys_cpu_sets'] = [2]
        self.assertNotEqual(subject.normalize_identity(changed, linux, 'reference', 'B'), canonical)
        changed_linux = dict(linux, compiler_version='changed compiler')
        self.assertNotEqual(subject.normalize_identity(reference, changed_linux, 'reference', 'B'), canonical)

    def test_wrapper_rejects_existing_outputs_before_any_preparation_or_board_request(self):
        script = Path(subject.__file__).with_name('run-intensity-timechain.sh').read_text()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root/'research/cross-path-20261017'
            archive.mkdir(parents=True)
            tools = root/'fake-tools'
            tools.mkdir()
            preparation = root/'unexpected-preparation'
            board = root/'unexpected-board-request'
            # Only relocate the fixed deployment root; execute the actual guards.
            deployed = root/'run.sh'
            deployed.write_text(script.replace('cd /home/yanlien/Program/hypervisor/tgoskits\n',
                                               'cd '+shlex.quote(str(root))+'\n'))
            for name, body in [('python3', 'exit 0'),
                               ('mkdir', 'touch '+shlex.quote(str(preparation))+'\nexit 73'),
                               ('cargo', 'touch '+shlex.quote(str(board))+'\nexit 74')]:
                path = tools/name
                path.write_text('#!/bin/sh\n'+body+'\n')
                path.chmod(0o755)
            for kind in ('raw', 'configs', 'results'):
                (archive/kind).mkdir()
            for kind in ('raw', 'configs', 'results'):
                name = 'existing-'+kind
                existing = archive/kind/(name+'.log' if kind == 'raw' else name)
                if kind == 'raw':
                    existing.write_text('existing capture')
                else:
                    existing.mkdir()
                result = subprocess.run(['sh', str(deployed), name, 'linux_memory', 'sgi', '2000', '1'],
                    env=dict(os.environ, PATH=str(tools)+os.pathsep+os.environ['PATH']), capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(preparation.exists(), 'an existing output reached preparation')
                self.assertFalse(board.exists(), 'an existing output reached board allocation')

    def test_registered_base_bytes_are_checked_before_execution_and_against_build_metadata(self):
        check = getattr(subject, 'check_base_inputs', None)
        self.assertTrue(callable(check), 'base input preflight is not implemented')
        with tempfile.TemporaryDirectory(prefix='.intensity-base-', dir=subject.REPO) as temporary:
            root = Path(temporary)
            base = {}
            for field in ('kernel_sha256', 'base_initramfs_sha256'):
                path = root/field
                path.write_bytes(field.encode())
                base[field] = dict(path=str(path.relative_to(subject.REPO)),
                                   sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            plan = dict(base_inputs=base)
            linux = {field: value['sha256'] for field, value in base.items()}
            check(plan, linux)
            with self.assertRaises(ValueError):
                check(plan, dict(linux, kernel_sha256='changed'))
            (root/'kernel_sha256').write_bytes(b'changed in place')
            with self.assertRaises(ValueError):
                check(plan, linux)

    def test_complete_accepted_macroblocks_bind_order_membership_and_all_strata(self):
        plan = subject.design_plan()
        runs = subject.registered_runs(plan)
        self.assertEqual(len({run['name'] for run in runs}), 96)
        for stratum in subject.STRATA:
            selected = [r for r in runs if r['stratum'] == stratum]
            for position in range(1, 5):
                self.assertEqual(Counter(r['condition'] for r in selected if r['position'] == position),
                                 {'0': 2, 'A': 2, 'B': 2, 'AB': 2})
        state = dict(terminal=True, success=True, plan_sha256='pinned',
                     completed=[dict(r, tasks=64) for r in runs])
        self.assertEqual(subject.validate_completed(plan, state, 'pinned'), runs)
        for broken in (dict(state, completed=state['completed'][:-1]),
                       dict(state, completed=state['completed'][1:]+state['completed'][:1]),
                       dict(state, terminal=False), dict(state, plan_sha256='changed'),
                       dict(state, completed=[dict(r, tasks=63) for r in runs])):
            with self.assertRaises(ValueError):
                subject.validate_completed(plan, broken, 'pinned')
        broken = copy.deepcopy(plan)
        broken['blocks'][0]['runs'][0]['stratum'] = 'wrong'
        with self.assertRaises(ValueError):
            subject.registered_runs(broken)

    def test_paired_interaction_change_preserves_macroblock_covariance_and_bounds(self):
        # Every changed interaction is +10 above the reference despite drift.
        reference = [dict(block=i+1, bounds_ns=[v-1, v+1]) for i, v in enumerate((-100, 900, -50, 2000))]
        changed = [dict(block=r['block'], bounds_ns=[r['bounds_ns'][0]+10, r['bounds_ns'][1]+10])
                   for r in reference]
        result = subject.paired_difference(reference, changed, seed=1, resamples=1000)
        self.assertEqual(result['mean_bounds_ns'], [8, 12])
        self.assertEqual(result['bootstrap_95_bounds_ns'], [8, 12])
        reversed_result = subject.paired_difference(changed, reference, seed=1, resamples=1000)
        self.assertEqual(reversed_result['mean_bounds_ns'], [-12, -8])
        self.assertEqual(reversed_result['bootstrap_95_bounds_ns'], [-12, -8])
        for bad in (changed[:-1], changed[::-1], [dict(r, block=1) for r in changed],
                    [dict(r, bounds_ns=[float('nan'), 1]) for r in changed]):
            with self.assertRaises(ValueError):
                subject.paired_difference(reference, bad, seed=1, resamples=1000)

    def test_actual_pressure_rejects_skips_and_wrong_memory_divisor(self):
        peer = dict(scenario='linux_memory', loads={p: dict(host_cpu=3, working_set_bytes=16777216,
                    every_batches=8, stopped=True, runtime_observation=dict(time_window_verified=True))
                    for p in ('fair', 'fifo80')})
        pressure = dict(mode='sgi', period_us=2000, burst=2,
                        policies={p: dict(sent=100, handled=100, skipped_periods=0, joined=True, retired=True)
                                  for p in ('fair', 'fifo80')})
        subject.validate_exposure('memory_sparse', 'AB', peer, pressure)
        for change in ('skip', 'divisor', 'period'):
            load, irq = copy.deepcopy((peer, pressure))
            if change == 'skip':
                irq['policies']['fair']['skipped_periods'] = 1
            elif change == 'divisor':
                load['loads']['fifo80']['every_batches'] = 1
            else:
                irq['period_us'] = 1000
            with self.assertRaises(ValueError):
                subject.validate_exposure('memory_sparse', 'AB', load, irq)


if __name__ == '__main__':
    unittest.main()
