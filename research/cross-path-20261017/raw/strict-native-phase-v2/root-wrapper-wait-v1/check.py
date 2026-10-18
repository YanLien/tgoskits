#!/usr/bin/python3
"""Exercise the actual wrapper Popen block with owned local children and audit failures."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--wrapper',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
raw=args.wrapper.read_bytes();tree=ast.parse(raw)
outer=[n for n in tree.body if isinstance(n,ast.Try)]
assert len(outer)==1
blocks=[n for n in outer[0].body if isinstance(n,ast.With) and any(isinstance(x,ast.Assign) and isinstance(x.value,ast.Call) and isinstance(x.value.func,ast.Attribute) and x.value.func.attr=='Popen' for x in ast.walk(n))]
assert len(blocks)==1
program=compile(ast.Module(body=blocks,type_ignores=[]),str(args.wrapper),'exec')
rows=[]
for fault in ('identity','launch-save'):
    work=Path(tempfile.mkdtemp(prefix='crosspath-root-wrapper-wait-proof-'))
    approval=work/'approval';approval.write_text('local owned child regression only\n')
    witness=work/'witness';witness.write_text('no host or board witness\n')
    children=[];inside=[];receipt={'supervisor':{'scope':'local test parent'},'supervisor_source_sha256':'local regression context'}
    def popen(*a,**kw):
        child=subprocess.Popen(*a,**kw);real_wait=child.wait
        def observed_wait(*wa,**wk):
            code=real_wait(*wa,**wk);inside.append({'pid':child.pid,'actual_Popen_wait':code});return code
        child.wait=observed_wait
        children.append((child,real_wait))
        return child
    def identity(pid):
        if fault=='identity':raise OSError('injected identity receipt error')
        return {'pid_from_actual_Popen':pid,'scope':'local child only'}
    def save(path,data):
        if fault=='launch-save':raise OSError('injected launch save error')
        Path(path).write_text(json.dumps(data))
    def sha(path):
        with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
    namespace={'log':work/'driver.log','subprocess':SimpleNamespace(Popen=popen,DEVNULL=subprocess.DEVNULL,STDOUT=subprocess.STDOUT),
        'argv':['/usr/bin/python3','-B','-c','raise SystemExit(7)'],'inputs':{'repo_root':str(work),'environment':{'PATH':'/usr/bin:/bin'}},
        'identity':identity,'receipt':receipt,'now':time.time,'sha':sha,'approval_path':approval,'witness_path':witness,'OUT':work,'save':save}
    error=None
    try:exec(program,namespace)
    except OSError as e:error=str(e)
    finally:
        cleanup=[{'pid':child.pid,'actual_parent_cleanup_wait':real_wait()} for child,real_wait in children]
    passed=len(children)==1 and len(inside)==1 and inside[0]['actual_Popen_wait']==7 and error==('injected identity receipt error' if fault=='identity' else 'injected launch save error') and receipt.get('driver_wait_exit')==7
    rows.append({'fault':fault,'passed':passed,'preserved_error':error,'wait_inside_actual_wrapper_block':inside,'local_parent_cleanup':cleanup,'driver_receipt_wait':receipt.get('driver_wait_exit')})
report={'passed':all(x['passed'] for x in rows),'scope':'only extracted actual Popen block; real local child exits 7; no hardware/controller/board behavior claimed','wrapper_sha256':hashlib.sha256(raw).hexdigest(),'checks':rows}
with args.output.open('x') as f:json.dump(report,f,indent=2,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
print(json.dumps(report,sort_keys=True))
raise SystemExit(0 if report['passed'] else 1)
