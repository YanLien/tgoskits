#!/usr/bin/env python3
"""Verify the recorder-cost checkpoint without claiming M1/M2 complete."""
import hashlib
import json
from pathlib import Path
import subprocess

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads((archive/p).read_text())
report = read('results/recorder-cost-paired-summary.json')
assert report['independent_pairs'] == 4 and report['task_observations'] == 512
assert not report['M1_complete'] and not report['M2_complete']
qemu = read('results/recorder-cost-qemu-audit.json')
assert qemu['same_fixed_inputs'] and qemu['off_complete_chain_rejected']
plan = read('configs/recorder-cost-pair-plan.json')
for key in ('source_sha256','host_source_sha256'):
    assert all(digest(repo/p) == h for p,h in plan[key].items())
fix = read('results/private-ram-patch-audit.json')
assert digest(repo/fix['source']) == fix['after_sha256']
patch = read('results/recorder-cost-patch-audit.json')
assert patch['isolated_apply_matches_live_sources'] and len(patch['changed']) == 6
assert all(digest(repo/p) == h['after_sha256'] for p,h in patch['changed'].items())
assert digest(archive/'run-recorder-pairs.py') == plan['controller_sha256']
assert digest(archive/'run-native-timechain.sh') == plan['wrapper_sha256']
controls = read('results/recorder-cost-controls-patch-audit.json')
assert controls['isolated_apply_matches_live_sources'] and len(controls['changed']) == 1
assert all(digest(repo/p) == h['after_sha256'] for p,h in controls['changed'].items())
assert 'Ran 37 tests' in (archive/'raw/recorder-cost-analysis-tests.log').read_text()
assert '\nOK\n' in (archive/'raw/recorder-cost-analysis-tests.log').read_text()
assert 'disabled recorder with forged completeness' in (archive/'raw/recorder-completeness-red.log').read_text()
assert 'FAILED (failures=1)' in (archive/'raw/recorder-completeness-red.log').read_text()
mutant = (archive/'raw/recorder-nullability-mutant-red.log').read_text()
assert 'AssertionError' in mutant and 'Original SHA256: '+digest(repo/'virtualization/axvm/tests/analysis/analyze_virq_task.py') in mutant
assert digest(archive/'summarize-recorder-pairs.py') == report['summary_script_sha256']
assert 'passed checks: 21, failed checks: 0, skipped checks: 0' in (archive/'raw/recorder-cost-clippy.log').read_text()
assert 'RECORDER_PAIRS_DONE blocks=4 runs=8 task_observations=512' in (archive/'raw/recorder-cost-pair-controller.log').read_text()
paths = sorted(p for p in archive.rglob('*') if p.is_file()
               and p.name != 'SHA256SUMS' and '__pycache__' not in p.parts)
for path in paths:
    if path.suffix == '.json':
        json.loads(path.read_text())
manifest = archive/'SHA256SUMS'
manifest.write_text(''.join(f'{digest(p)}  {p.relative_to(repo)}\n' for p in paths))
result = subprocess.run(['sha256sum','-c',str(manifest)],cwd=repo,
                        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
assert result.returncode == 0, result.stdout
print(f'RECORDER_COST_CHECKPOINT_OK files={len(paths)} board_pairs=4 board_task_observations=512 M1=0 M2=0')
