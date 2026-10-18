#!/usr/bin/env python3
"""A planned-arrival fence defect must fail through the actual task CLI."""

import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
analysis = repo/'virtualization/axvm/tests/analysis'
name = sys.argv[1] if len(sys.argv) > 1 else 'throughput-periodic-cpu-32'
raw = archive/'raw'/(name+'.log')
with (archive/'results'/name/'task/samples.csv').open() as stream:
    first = next(csv.DictReader(stream))
due, submitted = int(first['scheduled_release_ticks']), int(first['submit_ticks'])
assert first['policy'] == 'fair' and due + 1 <= submitted
changed, count = re.subn(r'(VIRQ_LINUX_FENCE_SUMMARY policy=fair .*?begin_observed_ticks=)\d+',
                        lambda match: match[1]+str(due+1), raw.read_text(), count=1)
assert count == 1
mutated_log = archive/'raw/throughput-fence-window-mutation.log'
assert not mutated_log.exists()
mutated_log.write_text(changed)
source = (analysis/'analyze_virq_task.py').read_text()
needle = "row.get('scheduled_release_ticks', row['submit_ticks'])"
assert source.count(needle) == 1
mutant = source.replace(needle, "row['submit_ticks']")
with tempfile.TemporaryDirectory(prefix='fence-task-origin-') as directory:
    temporary = Path(directory)
    copied = temporary/'analysis'
    shutil.copytree(analysis, copied, ignore=shutil.ignore_patterns('__pycache__'))
    (copied/'analyze_virq_task.py').write_text(mutant)
    command = [sys.executable, str(analysis/'analyze_virq_task.py'), str(mutated_log),
               '--output-dir', str(temporary/'correct-output')]
    correct = subprocess.run(command, capture_output=True, text=True)
    command[1], command[-1] = str(copied/'analyze_virq_task.py'), str(temporary/'mutant-output')
    broken = subprocess.run(command, capture_output=True, text=True)
    assert correct.returncode == 1 and 'does not cover the critical window' in correct.stderr
    assert broken.returncode == 0, broken.stderr
    summary = json.loads((temporary/'mutant-output/summary.json').read_text())
    assert summary['task_deadline_origin'] == 'scheduled_release'
    result = dict(scope='Synthetic corruption of a real QEMU log; never an accepted measurement',
                  original_cohort=name, original_log_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                  mutated_log_sha256=hashlib.sha256(mutated_log.read_bytes()).hexdigest(),
                  first_scheduled_ticks=due, first_submitted_ticks=submitted,
                  synthetic_begin_observed_ticks=due+1,
                  correct_cli_exit=correct.returncode, correct_cli_stderr=correct.stderr,
                  mutant_cli_exit=broken.returncode,
                  defect='Checking actual submit instead of planned arrival incorrectly credits uncovered arrivals',
                  analysis_sha256=hashlib.sha256(source.encode()).hexdigest(),
                  mutant_sha256=hashlib.sha256(mutant.encode()).hexdigest())
(archive/'results/throughput-fence-window-rejection.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))
