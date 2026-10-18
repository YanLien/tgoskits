#!/usr/bin/env python3
"""Serial hardware/absence/default checks; preserve every failed or accepted boot."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

archive=Path(__file__).resolve().parent
repo=archive.parent.parent
analysis=repo/'virtualization/axvm/tests/analysis'
plan_path=archive/'configs/thermal-check-plan.json'
assert not plan_path.exists(),'Inspect any existing plan; do not restart it'
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
roots=('virtualization/axvm/tests','virtualization/axvm/src','drivers/ax-driver')
sources={str(p.relative_to(repo)):digest(p) for tree in roots for p in (repo/tree).rglob('*')
         if p.is_file() and p.suffix in ('.rs','.py','.c','.h','.toml','.txt','.dts','.overlay') and '__pycache__' not in p.parts}
sources['virtualization/axvm/Cargo.toml']=digest(repo/'virtualization/axvm/Cargo.toml')
sources['Cargo.lock']=digest(repo/'Cargo.lock')
runs=[dict(name='thermal-qemu-unavailable-32',runtime='qemu',scenario='linux_cpu',pressure='off',thermal='enabled',expected_rejection=True),
      dict(name='thermal-board-memory-sgi-32',runtime='board',scenario='linux_memory',pressure='sgi',thermal='enabled'),
      dict(name='thermal-qemu-disabled-32',runtime='qemu',scenario='linux_cpu',pressure='off',thermal='disabled')]
controls={str(p.relative_to(repo)):digest(p) for p in (Path(__file__),archive/'run-thermal-timechain.sh',archive/'capture-thermal-driver.py',archive/'capture-periodic.py')}
plan=dict(runs=runs,source_sha256=sources,control_sha256=controls,
          scope='Directed thermal provider and original VM functionality checks; not a cost or interference estimate',M1=False,M2=False)
plan_path.write_text(json.dumps(plan,indent=2)+'\n')
state=dict(controller_pid=os.getpid(),started_unix=time.time(),terminal=False,success=False,completed=[],active_run=None)

def save():
    (archive/'results/thermal-check-status.json').write_text(json.dumps(state,indent=2)+'\n')

def check_sources():
    assert all(digest(repo/p)==h for p,h in sources.items()),'sources changed during cohort'
    assert all(digest(repo/p)==h for p,h in controls.items()),'control changed during cohort'

save()
try:
    for run in runs:
        check_sources()
        name=run['name'];state['active_run']=name;save()
        print('THERMAL_CHECK_BEGIN '+name,flush=True)
        result=subprocess.run(['sh',str(archive/'run-thermal-timechain.sh'),name,run['runtime'],run['scenario'],run['pressure'],run['thermal']],cwd=repo)
        check_sources()
        provenance=json.loads((archive/'configs'/name/'provenance.json').read_text())
        assert result.returncode==provenance['exit_code']
        if run.get('expected_rejection'):
            raw=(archive/'raw'/(name+'.log')).read_text(errors='replace')
            assert result.returncode!=0
            assert 'VIRQ_THERMAL_CONFIG enabled=1 ' in raw and 'AXVM_TEST_FAILED' in raw
            assert 'required SoC temperature unavailable' in raw,raw[-4000:]
            assert not any(marker in raw for marker in ('VIRQ_HOST_SAMPLE ','VIRQ_ISR_SAMPLE ','VIRQ_PHYSICAL_ARM ','VIRQ_LINUX_BOOT ','VIRQ_THERMAL_SAMPLE '))
            accepted=False
        else:
            assert result.returncode==0
            with (archive/'raw'/(name+'-analysis.log')).open('w') as stream:
                subprocess.run(['sh',str(archive/'replay-throughput.sh'),name],cwd=repo,check=True,stdout=stream,stderr=subprocess.STDOUT)
                for kind in ('stages','thermal'):
                    subprocess.run(['python3',str(analysis/('analyze_virq_'+kind+'.py')),str(archive/'results'/name/'analysis-input.log'),
                                    '--output-dir',str(archive/'results'/name/kind)],cwd=repo,check=True,stdout=stream,stderr=subprocess.STDOUT)
            summary=json.loads((archive/'results'/name/'thermal/summary.json').read_text())
            assert summary['task_observations']==64 and summary['cpu_frequency_hz'] is None
            assert summary['observations_available']==(run['thermal']=='enabled')
            accepted=True
        state['completed'].append(dict(name=name,measurement_accepted=accepted,expected_rejection=not accepted));state['active_run']=None;save()
        print(f'THERMAL_CHECK_OK name={name} measurement_accepted={int(accepted)}',flush=True)
    state.update(terminal=True,success=True,finished_unix=time.time());save()
    print('THERMAL_CHECKS_DONE accepted_boots=2 expected_rejected_boots=1 task_observations=128 snapshots=4',flush=True)
except BaseException as error:
    state.update(terminal=True,success=False,error=repr(error),finished_unix=time.time());save()
    raise
