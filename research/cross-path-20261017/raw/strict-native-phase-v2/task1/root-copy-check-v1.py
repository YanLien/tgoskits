#!/usr/bin/python3
"""Root checks an independent tools copy; actual child entries prohibit side effects."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time

R=Path('/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017')
W=R/'raw/strict-native-phase-v2/task1'
OUT=W/'root-copy-v1'
TOOLS=Path('/tmp/crosspath-native-capacity-v2-tools-ksjtks3x')
FREEZE='6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9'
REPORT='74eace0f3fd2a8611fcb49fe981a754bb722104dc89efd737acddf81a5087429'
SPEC='4b3c61913884343e5207fc62b7533d7a38ebe00d9076d1c998f586018785d0d0'

def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def ident(p):
    p=Path(p); s=p.stat()
    return {'sha256':sha(p),'bytes':s.st_size,'mode':stat.S_IMODE(s.st_mode)}

def load(p):
    return json.loads(Path(p).read_text())

def save(p,v):
    with Path(p).open('x') as f:
        json.dump(v,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())

def tree_metadata(root):
    h=hashlib.sha256();count=0
    for p in sorted(root.rglob('*')):
        s=p.lstat();row=[str(p.relative_to(root)),s.st_mode,s.st_size,s.st_mtime_ns]
        h.update(json.dumps(row,separators=(',',':')).encode()+b'\n');count+=1
    return {'entries':count,'metadata_sha256':h.hexdigest()}

def frozen(root,manifest):
    for name,row in manifest.items():
        p=root/name
        assert not p.is_symlink() and ident(p)==row, name
    assert sha(root/'freeze-manifest.json')==FREEZE

def main():
    report=R/'results/strict-native-trace-capacity-v2-task1.json'
    spec=R/'results/strict-native-trace-capacity-v2-task1-spec-review-v1.json'
    quality=R/'results/strict-native-trace-capacity-v2-task1-quality-review-v1.json'
    assert sha(report)==REPORT and sha(spec)==SPEC
    for review in (spec,quality):
        data=load(review)
        assert data.get('decision')=='PASS', (str(review),'not PASS')
        assert data.get('blockers')==[], (str(review),'blockers')
    assert sha(TOOLS/'freeze-manifest.json')==FREEZE
    inputs=load(TOOLS/'inputs.json');target=Path(inputs['target'])
    assert target.is_dir() and not target.is_symlink()
    assert not any(TOOLS.glob('*.once'))
    assert not any((R/'raw/strict-native-phase-v2'/c).exists() for c in ('AB1','AB0','0'))
    OUT.mkdir()
    manifest=load(TOOLS/'freeze-manifest.json');assert len(manifest)==69
    frozen(TOOLS,manifest)
    copy=Path(tempfile.mkdtemp(prefix='crosspath-native-capacity-v2-root-copy-'))
    for name in [*manifest,'freeze-manifest.json']:
        dest=copy/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(TOOLS/name,dest)
    frozen(copy,manifest)
    assert {str(p.relative_to(copy)) for p in copy.rglob('*') if p.is_file()}==set(manifest)|{'freeze-manifest.json'}
    audit=(W/'readiness-after-assets-v1/AUDITED_ENTRY.py.txt').read_text()
    save(OUT/'entry-identities.json',{'script':ident(__file__),'copy':str(copy),'frozen_members':len(manifest),'freeze_sha256':FREEZE,'task1_report_sha256':REPORT,'Spec':{'path':str(spec),'sha256':SPEC},'Quality':{'path':str(quality),'sha256':sha(quality)},'audit_source':ident(W/'readiness-after-assets-v1/AUDITED_ENTRY.py.txt')})
    before=tree_metadata(target);save(OUT/'target-metadata.before.json',before)
    commands=[('ready',['--check-ready'],0,None),('copied-formal-refusal',['--run','AB1','--source-manifest-sha',inputs['normal702_sha256'],'--approved-manifest',FREEZE],2,'formal execution requires the single frozen tools root; copied tools are read-only checks')]
    ready=None
    for label,args,expected,message in commands:
        argv=['/usr/bin/python3','-B','-c',audit,str(copy/'native_once.py'),*args]
        start=time.time_ns()
        with (OUT/(label+'.stdout')).open('xb') as stdout,(OUT/(label+'.stderr')).open('xb') as stderr:
            child=subprocess.Popen(argv,cwd=copy,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'},stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
            pid=child.pid;actual=child.wait()
        save(OUT/(label+'.receipt.json'),{'argv':argv,'cwd':str(copy),'environment':{'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'},'actual_child_pid':pid,'actual_Popen_wait':actual,'start_ns':start,'end_ns':time.time_ns(),'stdout':ident(OUT/(label+'.stdout')),'stderr':ident(OUT/(label+'.stderr'))})
        assert actual==expected,(label,actual)
        output=(OUT/(label+'.stdout')).read_text()
        assert not (OUT/(label+'.stderr')).read_bytes()
        assert 'FORBIDDEN' not in output
        if message is not None:
            assert message in output,output
        else:
            assert output.startswith('STRICT_NATIVE_READY ')
            ready=json.loads(output[len('STRICT_NATIVE_READY '):])
            assert ready['static']['all_match'] and ready['static']['normal702_count']==702
    after=tree_metadata(target);save(OUT/'target-metadata.after.json',after);assert before==after
    frozen(TOOLS,manifest);frozen(copy,manifest)
    assert not any(TOOLS.glob('*.once')) and not any(copy.glob('*.once'))
    assert not any((R/'raw/strict-native-phase-v2'/c).exists() for c in ('AB1','AB0','0'))
    result={'passed':True,'copy':str(copy),'frozen_members':69,'freeze_sha256':FREEZE,'source_702_sha256':inputs['normal702_sha256'],'actual_ready_wait':0,'actual_copied_formal_refusal_wait':2,'copied_formal_execution_approved':False,'target_metadata_unchanged':True,'entry_network_children_writes_signals_forbidden':True,'hardware_started':0,'qemu_started':0,'markers_created':0,'host_service_or_ownership_witness_obtained':False,'normal_host_passed':False,'M2':False,'Joint':False,'goal_complete':False,'actual_ready':ready,'completed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save(OUT/'result.json',result);print(json.dumps({k:v for k,v in result.items() if k!='actual_ready'},sort_keys=True),flush=True)

if __name__=='__main__':
    main()
