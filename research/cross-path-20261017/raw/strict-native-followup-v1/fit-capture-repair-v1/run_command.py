#!/usr/bin/env python3
"""Save an exact command, raw output, and its actual Popen.wait result once."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
name, *command = sys.argv[1:]
assert command and name.isidentifier()
paths = {kind: HERE / (name + '.' + kind) for kind in ('stdout', 'stderr', 'execution.json')}
assert not any(path.exists() for path in paths.values()), 'refusing to replace command evidence'
start = time.time_ns()
with paths['stdout'].open('xb') as out, paths['stderr'].open('xb') as err:
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                               env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    actual_wait_exit = process.wait()
record = {'argv': command, 'cwd': str(Path.cwd()), 'actual_Popen_wait_exit': actual_wait_exit,
          'start_time_ns': start, 'end_time_ns': time.time_ns(),
          'stdout': str(paths['stdout']), 'stderr': str(paths['stderr'])}
with paths['execution.json'].open('x') as stream:
    json.dump(record, stream, indent=2, sort_keys=True)
    stream.write('\n')
print(json.dumps(record, sort_keys=True), flush=True)
sys.exit(actual_wait_exit)
