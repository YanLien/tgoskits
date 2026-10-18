#!/usr/bin/env python3
"""Validate a terminal cohort using actual raw bytes and explicit recorder mode."""
import argparse
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('name')
parser.add_argument('--off', action='store_true')
args = parser.parse_args()
archive = Path(__file__).resolve().parent
repo = archive.parent.parent
analysis = repo/'virtualization/axvm/tests/analysis'
out = archive/'results'/args.name
provenance = json.loads((archive/'configs'/args.name/'provenance.json').read_text())
assert provenance['exit_code'] == 0 and provenance['suite_passed']
raw = archive/'raw'/(args.name+'.log')

def call(command):
    subprocess.run(command, cwd=repo, check=True)

with (archive/'raw'/(args.name+'-analysis.log')).open('w') as stream:
    def saved(command):
        subprocess.run(command, cwd=repo, check=True, stdout=stream, stderr=subprocess.STDOUT)
    if args.off:
        saved(['python3', str(archive/'prepare-analysis-input.py'), str(raw), str(out)])
        log = out/'analysis-input.log'
        saved(['python3', str(analysis/'analyze_virq_probe_cost.py'), str(log), '--output-dir', str(out/'probe_cost')])
        for kind, reason in (('task','disabled recorder cannot establish a complete runtime chain'),
                             ('stages','disabled recorder has no IRQ stage observations')):
            with (out/(kind+'-rejection.log')).open('w') as rejection:
                result = subprocess.run(['python3', str(analysis/('analyze_virq_'+kind+'.py')),
                    str(log), '--output-dir', str(out/('forbidden-'+kind))], cwd=repo,
                    stdout=rejection, stderr=subprocess.STDOUT)
            assert result.returncode != 0 and reason in (out/(kind+'-rejection.log')).read_text()
    else:
        saved(['sh', str(archive/'replay-throughput.sh'), args.name])
        saved(['python3', str(analysis/'analyze_virq_stages.py'), str(out/'analysis-input.log'),
               '--output-dir', str(out/'stages')])
summary = json.loads((out/('probe_cost' if args.off else 'stages')/'summary.json').read_text())
if args.off:
    assert summary['recording_mode'] == 'off' and not summary['complete_chain_accepted']
else:
    assert summary['samples'] == 64 and summary['dropped'] == summary['incomplete'] == 0
print(f'IRQ_STAGES_RUN_OK name={args.name} samples=64 stage_observations={int(not args.off)}')
