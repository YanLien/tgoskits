#!/usr/bin/env python3
"""Wait for the existing run plan, then verify frozen analysis and seal once."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
status_path = Path('/tmp/recorder-ops-finalizer-status.json')
assert not status_path.exists(), 'Inspect any existing finalizer; do not restart blindly'
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
state = dict(terminal=False, success=False, phase='waiting_for_existing_run_plan', started_unix=time.time())


def save():
    temporary = status_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2)+'\n')
    temporary.replace(status_path)


save()
try:
    while True:
        try:
            run = json.loads((archive/'results/recorder-ops-status.json').read_text())
        except (OSError, json.JSONDecodeError):
            time.sleep(1)
            continue
        pid = run['controller_pid']
        state['waiting_for_controller_pid'] = pid
        try:
            command = (Path('/proc')/str(pid)/'cmdline').read_bytes()
            alive = b'run-recorder-ops.py' in command
        except FileNotFoundError:
            alive = False
        if run['terminal']:
            assert run['success'], 'run plan failed; no final estimates or sealing attempted'
            if not alive:
                break
        elif not alive:
            raise RuntimeError('controller disappeared without a terminal state; inspect its preserved plan and data')
        time.sleep(1)
    state['phase'] = 'verify_frozen_analysis_then_finalize'
    save()
    frozen = json.loads((archive/'configs/recorder-ops-analysis-code.json').read_text())
    assert all(digest(repo/p) == h for p, h in frozen['source_sha256'].items()), 'analysis implementation changed after its freeze'
    subprocess.run(['python3', str(archive/'finalize-recorder-ops.py')], cwd=repo, check=True)
    state.update(terminal=True, success=True, phase='sealed', finished_unix=time.time())
    save()
    print('RECORDER_OPS_FINALIZER_DONE', flush=True)
except BaseException as error:
    state.update(terminal=True, success=False, error=repr(error), finished_unix=time.time())
    save()
    raise
