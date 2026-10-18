#!/usr/bin/env python3
"""Run the unchanged formal std profiles in an isolated, focused source copy."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

archive=Path(__file__).resolve().parent
repo=archive.parent.parent
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
work=Path(tempfile.mkdtemp(prefix='thermal-std-',dir='/tmp'))
paths=subprocess.check_output(['git','ls-files','-z'],cwd=repo).decode().split('\0')
for name in paths:
    if not name:
        continue
    source=repo/name
    if not source.exists() and not source.is_symlink():
        continue
    if source.is_dir():
        continue
    dest=work/name;dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,dest,follow_symlinks=False)
new='drivers/ax-driver/src/soc/rockchip/thermal.rs'
shutil.copy2(repo/new,work/new)
whitelist='scripts/test/std_crates.csv'
original_whitelist=(work/whitelist).read_bytes()
(work/whitelist).write_text('package\nax-driver\n')
tracked_sources={str(p.relative_to(repo)):digest(p) for p in (repo/'drivers/ax-driver').rglob('*') if p.is_file() and p.suffix in ('.rs','.toml')}
assert all(digest(work/p)==h for p,h in tracked_sources.items())
metadata=dict(isolated_workspace=str(work),source_sha256=tracked_sources,
    original_main_whitelist_sha256=digest(repo/whitelist), isolated_whitelist='package\nax-driver\n',
    formal_runner_sha256=digest(repo/'scripts/axbuild/src/test/std.rs'),
    command=['cargo','xtask','test'],reason='Formal std runner has no uncommitted package selector; main whitelist is unchanged')
config=archive/'configs/thermal-std-snapshot.json';assert not config.exists()
config.write_text(json.dumps(metadata,indent=2)+'\n')
env=dict(os.environ,CARGO_TARGET_DIR=str(repo/'target/research-thermal-std'))
source=work/new
correct=source.read_text()
needle='    check_tsadc_sampling(mmio, sensor.channel())?;'
assert correct.count(needle)==1
source.write_text(correct.replace(needle,'    write32(mmio, TSADC_AUTO_PERIOD, read32(mmio, TSADC_AUTO_PERIOD).wrapping_add(1));\n'+needle))
try:
    with (archive/'raw/thermal-readonly-mutant-red.log').open('w') as stream:
        stream.write('ISOLATED_MUTANT only: public query writes sampling period; main source unchanged\n');stream.flush()
        red=subprocess.run(['cargo','xtask','test'],cwd=work,env=env,stdout=stream,stderr=subprocess.STDOUT)
    red_log=(archive/'raw/thermal-readonly-mutant-red.log').read_text()
    assert red.returncode!=0 and 'queries must never tighten thresholds' in red_log
finally:
    source.write_text(correct)
assert all(digest(work/p)==h for p,h in tracked_sources.items())
with (archive/'raw/thermal-std-tests-green.log').open('w') as stream:
    green=subprocess.run(['cargo','xtask','test'],cwd=work,env=env,stdout=stream,stderr=subprocess.STDOUT)
assert green.returncode==0
assert all(digest(repo/p)==h for p,h in tracked_sources.items())
assert digest(repo/whitelist)==metadata['original_main_whitelist_sha256']
assert (repo/whitelist).read_bytes()==original_whitelist
metadata.update(red_exit=red.returncode,green_exit=green.returncode,main_sources_unchanged=True,
    red_log_sha256=digest(archive/'raw/thermal-readonly-mutant-red.log'),green_log_sha256=digest(archive/'raw/thermal-std-tests-green.log'))
config.write_text(json.dumps(metadata,indent=2)+'\n')
print('THERMAL_CONTRACT_OK isolated_mutant_rejected=1 formal_profiles=4 main_whitelist_unchanged=1')
