#!/usr/bin/python3
"""Root's single AB1 invocation and durable actual wait; frozen runner owns hardware."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import time
import sys
import urllib.request

ROOT = Path('/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017')
OUT = ROOT/'raw/strict-native-phase-v2'
TOOLS = Path('/tmp/crosspath-native-capacity-v2-tools-ksjtks3x')
FREEZE = '6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9'
DELIVERY = 'fe7b8cd40aa21855eaaaedfb0ed92022eac37eed329dc51b06352710d4525bb7'
EXPECTED = {'native_once.py':'88608867d42ce9adbf4aa900dd8da71667b8e1090e3c52c82174c9949f3d21f4',
 'capture_native.py':'e1e573ed9ecd8a1dd77c80d6a06fff3739e4fa8114815cc2b6b5c826206a14b2',
 'inputs.json':'a785de09f1017498360677338ef0f0c4af40a9ed7bc81a9c824c52b58841abbd',
 'freeze-manifest.json':FREEZE}

def sha(p):
    return hashlib.file_digest(Path(p).open('rb'),'sha256').hexdigest()

def save(p, data):
    with p.open('x') as f:
        json.dump(data,f,sort_keys=True,indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def identity(pid):
    p=Path('/proc')/str(pid)
    a=(p/'stat').read_text().rsplit(')',1)[1].split()
    argv=[v.decode(errors='replace') for v in (p/'cmdline').read_bytes().split(b'\0') if v]
    b=(p/'stat').read_text().rsplit(')',1)[1].split()
    if (a[2],a[19]) != (b[2],b[19]):
        raise RuntimeError('process identity changed during read')
    return {'pid':pid,'pgid':int(b[2]),'starttime':b[19],'state':b[0],'argv':argv}

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--acceptance-sha256',required=True)
args=parser.parse_args()

receipt={'schema_version':1,'case_id':'AB1','started_utc':now(),'driver_wait_exit':None,
 'hardware_owned_by':'unchanged frozen native_once.py only','supervisor_source_sha256':sha(__file__)}
try:
    inputs=json.loads((TOOLS/'inputs.json').read_text())
    for name, expected in EXPECTED.items():
        if sha(TOOLS/name) != expected:
            raise RuntimeError('frozen input changed: '+name)
    if sha(ROOT/'results/intensity-v3-final-delivery.json') != DELIVERY:
        raise RuntimeError('completed primary delivery identity changed')
    if any((OUT/case).exists() for case in ('AB1','AB0','0')) or any(TOOLS.glob('*.once')):
        raise RuntimeError('native case or one-shot marker already exists')
    acceptance_path=ROOT/'results/strict-native-trace-capacity-v2-task1-root-acceptance-v1.json'
    if sha(acceptance_path)!=args.acceptance_sha256:
        raise RuntimeError('Root offline acceptance SHA differs')
    acceptance=json.loads(acceptance_path.read_text())
    if (acceptance.get('offline_task1_passed') is not True or acceptance.get('candidate_manifest_sha256')!=FREEZE
            or acceptance.get('hardware_started')!=0):
        raise RuntimeError('current candidate has no complete offline acceptance')
    for ref in acceptance['evidence'].values():
        if sha(ROOT/ref['path'])!=ref['sha256']:
            raise RuntimeError('Root acceptance evidence changed: '+ref['path'])
    copied_path=ROOT/acceptance['evidence']['Root_copy']['path']
    copied=json.loads(copied_path.read_text())
    if copied.get('passed') is not True or copied.get('freeze_sha256')!=FREEZE:
        raise RuntimeError('Root independent copy has not passed')
    # Task1 legitimately populated this exclusive target with xtask Clippy.
    # Its current metadata must match the completed no-write copy check.
    target=Path(inputs['target'])
    if target.is_symlink() or not target.is_dir() or target.stat().st_uid!=os.getuid():
        raise RuntimeError('new owned Clippy target identity is invalid')
    metadata_ref=acceptance['evidence']['Root_copy_metadata']
    metadata_path=ROOT/metadata_ref['path']
    if metadata_path!=copied_path.parent/'target-metadata.after.json' or sha(metadata_path)!=metadata_ref['sha256']:
        raise RuntimeError('Root accepted target metadata identity differs')
    expected_meta=json.loads(metadata_path.read_text())
    metadata_hash=hashlib.sha256();count=0
    for member in sorted(target.rglob('*')):
        st=member.lstat()
        row=[str(member.relative_to(target)),st.st_mode,st.st_size,st.st_mtime_ns]
        metadata_hash.update(json.dumps(row,separators=(',',':')).encode()+b'\n');count+=1
    if {'entries':count,'metadata_sha256':metadata_hash.hexdigest()}!=expected_meta:
        raise RuntimeError('private target changed since Root independent copy check')
    receipt['offline_acceptance_sha256']=args.acceptance_sha256
    receipt['target_preexisting_for_verified_clippy']=True
    receipt['target_metadata_before']=expected_meta
    # This read-only availability snapshot never reserves or releases a board.
    url='http://10.3.10.60:2999/api/v1/board-types'
    with urllib.request.urlopen(url,timeout=10) as response:
        service_raw=response.read(1024*1024+1)
        if response.status!=200 or len(service_raw)>1024*1024:
            raise RuntimeError('board service snapshot status/size refused')
    rows=json.loads(service_raw)
    matches=[row for row in rows if row.get('board_type')=='BallPick-Robot']
    if len(matches)!=1 or type(matches[0].get('available')) is not int or matches[0]['available']<1:
        raise RuntimeError('target board type currently unavailable')
    raw_service=OUT/'AB1-board-service-v1.raw'
    with raw_service.open('xb') as stream:
        stream.write(service_raw);stream.flush();os.fsync(stream.fileno())
    save(OUT/'AB1-board-service-v1.json',{'method':'GET','url':url,'observed_utc':now(),
      'raw_sha256':sha(raw_service),'available':matches[0]['available'],'reserved':False})
    if Path('/proc/1/comm').read_text().strip() != 'systemd':
        raise RuntimeError('actual host init not visible')
    namespace=os.readlink('/proc/self/ns/pid')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if namespace != 'pid:[4026531836]' or boot != '28c780ce-53d7-4ad5-a932-9a85f25b03c9':
        raise RuntimeError('actual host namespace or boot changed')
    stat=os.statvfs('/tmp')
    free=stat.f_bavail*stat.f_frsize
    if free < 8*1024**3:
        raise RuntimeError('less than 8 GiB free before first native build')
    receipt['supervisor']=identity(os.getpid())
    conflicts=[]
    unknown=[]
    checked=0
    tool_names={'cargo','rustc','xtask','ostool','gdb','gdbserver','aarch64-linux-gnu-gdb'}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            comm=(p/'comm').read_text().strip()
            if comm not in tool_names and not comm.startswith('qemu-system'):
                continue
            record=identity(int(p.name))
            cwd=os.readlink(p/'cwd')
            checked+=1
            args=record['argv']
            tool=Path(args[0]).name if args else comm
            board=(tool in {'ostool','gdb','gdbserver','aarch64-linux-gnu-gdb'} or comm.startswith('qemu-system')
                   or ('ktest' in args and 'board' in args))
            private=(cwd.startswith(inputs['source']) or cwd.startswith(inputs['target'])
                     or any(inputs['target'] in a or inputs['source'] in a or str(TOOLS) in a for a in args))
            if record['state'] != 'Z' and (board or private):
                conflicts.append({k:v for k,v in record.items() if k!='argv'}|{'comm':comm,'cwd':cwd})
        except (FileNotFoundError,ProcessLookupError):
            continue
        except PermissionError:
            unknown.append({'pid':int(p.name),'comm':comm,'identity':'unreadable relevant process'})
    if conflicts or unknown:
        save(OUT/'AB1-host-preflight-refusal-v1.json',{'conflicts':conflicts,'unknown':unknown,'time_utc':now()})
        raise RuntimeError('competing target/board tool or unknown relevant identity')
    witness={'schema_version':1,'case_id':'AB1','candidate_manifest_sha256':FREEZE,
      'target':inputs['target'],'no_competing_target_or_board_tools':True,'host_namespace_verified':True,
      'protected_controller_pid':1666583,'pid_namespace':namespace,'boot_id':boot,
      'observed_unix':time.time(),'observed_utc':now(),'relevant_tools_inspected':checked,
      'conflicts':conflicts,'unknown':unknown,'tmp_available_bytes':free,
      'observer':receipt['supervisor'],'scope':'actual-host snapshot; no board allocation or signal'}
    witness_path=OUT/'AB1-host-preflight-v1.json'
    save(witness_path,witness)
    approval={'schema_version':1,'case_id':'AB1','candidate_manifest_sha256':FREEZE,
      'primary_delivery_sha256':DELIVERY,'source_702_sha256':inputs['normal702_sha256'],
      'ordinary_manifest_sha256':sha(TOOLS/'evidence/ordinary-identities.json'),
      'inputs_sha256':EXPECTED['inputs.json'],'cache_runtime_state':copied['actual_ready']['static']['cache_runtime_state'],
      'argv':inputs['argv'],'environment':inputs['environment']|inputs['cases'][0]['environment'],
      'limits':inputs['limits'],'host_preflight':{'path':str(witness_path.relative_to(ROOT)),'sha256':sha(witness_path)}}
    approval_path=OUT/'AB1-root-approval-v1.json'
    save(approval_path,approval)
    argv=['/usr/bin/python3','-B',str(TOOLS/'native_once.py'),'--run','AB1',
      '--approved-manifest',FREEZE,'--approval',str(approval_path),'--approval-sha256',sha(approval_path),
      '--source-manifest-sha',inputs['normal702_sha256']]
    log=OUT/'AB1-native-driver.log'
    with log.open('xb') as stream:
        child=subprocess.Popen(argv,cwd=inputs['repo_root'],env=inputs['environment'],
          stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            receipt['driver_pid_from_Popen']=child.pid
            launch={'schema_version':1,'case_id':'AB1','launched_utc':now(),'argv':argv,'cwd':inputs['repo_root'],
              'environment':inputs['environment'],'driver':identity(child.pid),'supervisor':receipt['supervisor'],
              'approval_sha256':sha(approval_path),'host_preflight_sha256':sha(witness_path),
              'supervisor_source_sha256':receipt['supervisor_source_sha256'],
              'wait_method':"subprocess.Popen.wait on this parent's original direct child"}
            save(OUT/'AB1-root-launch.json',launch)
            receipt['driver']=launch['driver']
            receipt['launch_sha256']=sha(OUT/'AB1-root-launch.json')
        finally:
            # A receipt failure must not detach the actual owned driver.
            receipt['driver_wait_exit']=child.wait()
    receipt['driver_log_sha256']=sha(log)
    result=OUT/'AB1/run-result.json'
    receipt['run_result_sha256']=sha(result) if result.exists() else None
    receipt['case_marker_present']=(TOOLS/'AB1.once').exists()
    receipt['output_present']=(OUT/'AB1').exists()
except Exception as error:
    receipt['error']=type(error).__name__+': '+str(error)
finally:
    receipt['finished_utc']=now()
    receipt['wait_method']="subprocess.Popen.wait on this parent's original direct child"
    save(OUT/'AB1-root-wait.json',receipt)
print(json.dumps(receipt,sort_keys=True),flush=True)
sys.exit(0 if receipt.get('driver_wait_exit')==0 and 'error' not in receipt else 1)
