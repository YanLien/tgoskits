#!/usr/bin/env python3
"""One owned native child per approved case; read-only readiness never starts a target."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import time
import uuid

import capture_native as c

HERE = Path(__file__).resolve().parent
INPUTS = json.loads((HERE/'inputs.json').read_text())
ARCHIVE = Path(INPUTS['research_root'])
REPO = Path(INPUTS['repo_root'])
PROTECTED_PID = 1666583
PRIMARY_SHA = 'b3f1a63d273f4ff918bcd8dbd5acd30ee1fa9d18e56b70b24ee07ac6863fb0c5'


def json_reference(reference, root=ARCHIVE):
    if not re.fullmatch('[0-9a-f]{64}', reference['sha256']):
        raise ValueError('invalid exact reference SHA')
    path = c.safe_file(root, reference['path'])
    if c.digest(path) != reference['sha256']:
        raise ValueError('referenced evidence bytes changed: '+str(path))
    return path, json.loads(path.read_text())


def verify_primary_delivery():
    contract_path = HERE/'evidence/primary-delivery-contract.json'
    if c.digest(contract_path) != INPUTS['primary_contract_sha256']:
        raise ValueError('primary completion contract identity differs')
    contract = json.loads(contract_path.read_text())
    delivery_path = ARCHIVE/contract['future_delivery_path']
    if not delivery_path.exists():
        raise ValueError('PRIMARY_DELIVERY_MISSING: original session 52334 and full96 seal/replay/reviews not delivered')
    delivery_path = c.safe_file(ARCHIVE,contract['future_delivery_path'])
    delivery = json.loads(delivery_path.read_text())
    for key,value in contract['delivery_required_literals'].items():
        if type(delivery.get(key)) is not type(value) or delivery[key] != value:
            raise ValueError('primary delivery literal differs: '+key)
    refs = {}
    required = set()
    for key in contract['delivery_required_references']:
        if key == 'seal':
            continue
        ref = delivery[key]
        fixed = contract['delivery_required_references'][key]
        if isinstance(fixed,dict):
            for field,value in fixed.items():
                if not str(value).startswith('actual') and ref.get(field) != value:
                    raise ValueError('primary fixed evidence reference differs: '+key)
        path,record = json_reference(ref)
        refs[key] = record
        required.add(str(path.relative_to(REPO)))
        for field,value in contract['referenced_JSON_required_literals'].get(key,{}).items():
            if type(record.get(field)) is not type(value) or record[field] != value:
                raise ValueError('primary referenced content differs: '+key+'/'+field)
    plan,status,summary = refs['plan'],refs['status'],refs['summary']
    if (c.digest(ARCHIVE/delivery['plan']['path']) != PRIMARY_SHA or status.get('plan_sha256') != PRIMARY_SHA
            or status.get('terminal') is not True or status.get('success') is not True
            or status.get('controller_pid') != PROTECTED_PID):
        raise ValueError('primary status not successful terminal exact plan/controller')
    if not isinstance(refs['controller_exit'].get('terminal_chunk'),str) or not refs['controller_exit']['terminal_chunk']:
        raise ValueError('original session has no actual successful wait terminal chunk')
    for key,count in [('source_sha256',696),('control_sha256',52),('base_inputs',2)]:
        records = plan[key]
        if len(records) != count:
            raise ValueError('primary registered input count differs: '+key)
        for name,value in records.items():
            relative = value['path'] if isinstance(value,dict) else name
            expected = value['sha256'] if isinstance(value,dict) else value
            if c.digest(c.safe_file(REPO,relative)) != expected:
                raise ValueError('primary registered input changed: '+relative)
    planned = [run for block in plan['blocks'] for run in block['runs']]
    completed = status['completed']
    if len(planned) != 96 or len(completed) != 96:
        raise ValueError('primary complete96 registration missing')
    for expect,actual in zip(planned,completed):
        if any(actual.get(k) != v for k,v in expect.items()) or actual.get('tasks') != 64 or actual.get('task_observations_valid') is not True:
            raise ValueError('primary completed run order/workload differs')
        name = actual['name']
        for relative,expected in [(f'raw/{name}.log',actual['raw_sha256']),
                                  (f'results/{name}/analysis-input.log',actual['analysis_input_sha256'])]:
            p = c.safe_file(ARCHIVE,relative)
            if c.digest(p) != expected:
                raise ValueError('primary raw/analysis evidence differs')
            required.add(str(p.relative_to(REPO)))
        for relative,expected in actual['derived_sha256'].items():
            p = c.safe_file(ARCHIVE,f'results/{name}/'+relative)
            if c.digest(p) != expected:
                raise ValueError('primary derived evidence differs')
            required.add(str(p.relative_to(REPO)))
    for field,expected in [('plan_sha256',PRIMARY_SHA),('status_sha256',delivery['status']['sha256']),
                           ('summary_script_sha256',c.digest(ARCHIVE/'summarize-intensity.py')),
                           ('acceptance_script_sha256',c.digest(ARCHIVE/'intensity_sensitivity.py'))]:
        if summary.get(field) != expected:
            raise ValueError('primary final summary identity differs: '+field)
    sealref = delivery['seal']
    if sealref.get('path_base') != 'repo':
        raise ValueError('primary seal reference needs repo path base')
    seal = c.safe_file(REPO,sealref['path'])
    if not seal.is_relative_to(ARCHIVE) or c.digest(seal) != sealref['sha256']:
        raise ValueError('primary new seal identity differs')
    sealed = {}
    for line in seal.read_text().splitlines():
        if not line:
            continue
        expected,relative = line.split('  ',1)
        if not re.fullmatch('[0-9a-f]{64}',expected) or relative in sealed:
            raise ValueError('unsafe or duplicate primary seal entry')
        path = c.safe_file(REPO,relative)
        if not path.is_relative_to(ARCHIVE) or c.digest(path) != expected:
            raise ValueError('primary sealed artifact differs')
        sealed[relative] = expected
    for filename in ['intensity-v3-run-means.csv','intensity-v3-task-endpoints.csv','intensity-v3-environment.csv','intensity-v3-report.md']:
        required.add(str((ARCHIVE/'results'/filename).relative_to(REPO)))
    for stem in ('interactions','paired-changes','ecdf','throughput'):
        for ext in ('png','pdf'):
            required.add(str((ARCHIVE/'results/figures'/f'intensity-v3-{stem}.{ext}').relative_to(REPO)))
    # Root supplies exact replay evidence references, avoiding guesses about future raw command paths.
    replay = refs['cold_replay_audit']
    for record in replay.get('evidence',[]):
        path = c.safe_file(ARCHIVE,record['path'])
        if c.digest(path) != record['sha256']:
            raise ValueError('primary raw cold replay evidence differs')
        required.add(str(path.relative_to(REPO)))
    if not replay.get('evidence'):
        raise ValueError('primary cold replay raw evidence references missing')
    if not required <= set(sealed):
        raise ValueError('primary new seal lacks complete required delivery evidence')
    for kind in ('Spec','Quality'):
        review = refs[kind]
        bindings = review.get('evidence_sha256',{})
        for key in ('full_audit','cold_replay_audit','status','summary'):
            if bindings.get(delivery[key]['path']) != delivery[key]['sha256']:
                raise ValueError('complete review does not bind actual delivery: '+kind+'/'+key)
    return {'path':str(delivery_path),'sha256':c.digest(delivery_path),'seal_sha256':c.digest(seal)}


def check_ready(expected_source_sha=None):
    if expected_source_sha is not None and expected_source_sha != INPUTS['normal702_sha256']:
        raise ValueError('approved normal702 source SHA differs')
    static = c.verify_static()
    # The primary delivery gate is shared with the real launch path.
    primary = verify_primary_delivery()
    return {'static':static,'primary':primary}


def process_record(pid):
    root = Path('/proc')/str(pid)
    fields = (root/'stat').read_text().rsplit(')',1)[1].split()
    argv = [x.decode(errors='replace') for x in (root/'cmdline').read_bytes().split(b'\0') if x]
    after = (root/'stat').read_text().rsplit(')',1)[1].split()
    if (fields[2],fields[19]) != (after[2],after[19]):
        raise ValueError('process identity changed while reading ownership')
    return {'pid':pid,'pgid':int(after[2]),'starttime':after[19],'state':after[0],'argv':argv}


def cleanup_owned(child, recorded, token):
    """Signal only the exact live owned PGID, never the protected primary controller."""
    group = child.pid
    if group in (os.getpgrp(),PROTECTED_PID) or group <= 1 or recorded['pgid'] != group:
        raise ValueError('refusing unproven/protected process group')
    verified = {}
    cleanup_deadline = time.monotonic()+INPUTS['limits']['cleanup_seconds']
    def prove(initial=False, wait_for_exit=False):
        live = {}
        for proc in Path('/proc').iterdir():
            if time.monotonic()>=cleanup_deadline:
                raise TimeoutError('owned cleanup10 expired; group state unknown')
            if not proc.name.isdigit():
                continue
            try:
                pid = int(proc.name)
                # Avoid reading any original-controller identity while collecting this group.
                if pid == PROTECTED_PID:
                    continue
                actual = process_record(pid)
                if actual['pgid'] != group:
                    continue
                if pid <= 1:
                    raise ValueError('protected process group member')
                if actual['starttime'] != (recorded['starttime'] if pid == group else verified.get(pid,actual)['starttime']):
                    raise ValueError('owned group PID start identity changed')
                if not initial and pid not in verified:
                    raise ValueError('new unproven process appeared during cleanup')
                if actual['state']=='Z':
                    if initial or pid not in verified:
                        raise ValueError('unproven zombie in owned process group')
                    continue
                if wait_for_exit and not actual['argv']:
                    # Exit can remove mm/argv before /proc reports Z. Wait only; never authorize another signal from this state.
                    live[pid] = actual
                    continue
                if not initial and actual['argv'] != verified[pid]['argv']:
                    raise ValueError('owned member argv changed')
                if pid == group and actual['argv'] != recorded['argv']:
                    raise ValueError('owned group leader argv changed')
                if ('STRICT_NATIVE_RUN_TOKEN='+token).encode() not in (proc/'environ').read_bytes().split(b'\0'):
                    raise ValueError('owned group token missing')
                live[pid] = actual
            except (FileNotFoundError,ProcessLookupError):
                continue
        if initial:
            if group not in live and child.poll() is None:
                raise ValueError('neither the exact leader nor its actual completed wait is provable')
            verified.update(live)
        return live
    # A completed leader wait does not prove that its token-bearing process group is empty.
    child.poll()
    if not prove(initial=True):
        return {'signals':[],'child_wait':child.poll(),'owned_group_empty':True,'release':'not-forced-group-empty'}
    signals = []
    for sig,seconds in ((signal.SIGTERM,5),(signal.SIGKILL,5)):
        if not prove():
            break
        os.killpg(group,sig)
        signals.append(sig.name)
        deadline = min(cleanup_deadline,time.monotonic()+seconds)
        while time.monotonic()<deadline:
            child.poll()
            if not prove(wait_for_exit=True):
                return {'signals':signals,'child_wait':child.poll(),'owned_group_empty':True,
                        'release':'unknown-after-forced-stop'}
            time.sleep(0.1)
    return {'signals':signals,'child_wait':child.poll(),'owned_group_empty':not bool(prove()),
            'release':'unknown-after-forced-stop'}


def verify_approval(args,ready):
    if HERE != Path(INPUTS['execution_tools_root']).resolve():
        raise ValueError('formal execution requires the single frozen tools root; copied tools are read-only checks')
    freeze_sha = c.digest(HERE/'freeze-manifest.json')
    if args.approved_manifest != freeze_sha:
        raise ValueError('Root approval must name exact frozen candidate SHA')
    if args.approval is None or not args.approval_sha256 or c.digest(args.approval) != args.approval_sha256:
        raise ValueError('Root exact approval bytes are required')
    approval = json.loads(Path(args.approval).read_text())
    case = next(row for row in INPUTS['cases'] if row['id'] == args.run)
    environment = {**INPUTS['environment'],**case['environment']}
    expected = {'schema_version':1,'case_id':args.run,'candidate_manifest_sha256':freeze_sha,
                'primary_delivery_sha256':ready['primary']['sha256'],'source_702_sha256':INPUTS['normal702_sha256'],
                'ordinary_manifest_sha256':c.digest(HERE/'evidence/ordinary-identities.json'),
                'inputs_sha256':c.digest(HERE/'inputs.json'),'cache_runtime_state':ready['static']['cache_runtime_state'],'argv':INPUTS['argv'],'environment':environment,'limits':INPUTS['limits']}
    if any(approval.get(key) != value for key,value in expected.items()):
        raise ValueError('Root approval differs from this exact native input')
    _,witness = json_reference(approval['host_preflight'])
    if (witness.get('candidate_manifest_sha256') != freeze_sha or witness.get('target') != INPUTS['target']
            or witness.get('no_competing_target_or_board_tools') is not True or witness.get('host_namespace_verified') is not True
            or witness.get('protected_controller_pid') != PROTECTED_PID or not 0 <= time.time()-witness['observed_unix'] <= 60):
        raise ValueError('fresh Root host-namespace target/board ownership witness required')
    position = [row['id'] for row in INPUTS['cases']].index(args.run)
    if position:
        _,previous = json_reference(approval['previous_delivery'])
        if (previous.get('case_id') != INPUTS['cases'][position-1]['id'] or previous.get('full_function_passed') is not True
                or previous.get('xtask_wait_exit') != 0 or previous.get('driver_wait_exit') != 0
                or previous.get('release') != 'explicit-finalize-success' or previous.get('artifact_chain_complete') is not True):
            raise ValueError('previous case complete function/exit/artifact/release required')
        for key in ('Spec','Quality'):
            _,review = json_reference(approval['previous_'+key])
            if review.get('verdict') != 'Approved' or review.get('delivery_sha256') != approval['previous_delivery']['sha256']:
                raise ValueError('previous case exact Spec then Quality approval required')
    return approval,environment


def run_once(args,ready):
    approval,environment = verify_approval(args,ready)
    if any((HERE/(row['id']+'.once')).exists() for row in INPUTS['cases'][[r['id'] for r in INPUTS['cases']].index(args.run):]):
        raise ValueError('case quota consumed or sequence inconsistent')
    target = Path(INPUTS['target'])
    if target.is_symlink():
        raise ValueError('native target is a symlink')
    output = ARCHIVE/'raw/strict-native-phase-v3'/args.run
    if output.exists():
        raise ValueError('native output exists; never restart')
    # Only completed readiness plus exact Root approval may cross this marker/Popen boundary.
    marker = HERE/(args.run+'.once')
    with marker.open('x') as stream:
        stream.write(json.dumps({'approval_sha256':args.approval_sha256,'time_ns':time.time_ns()})+'\n')
    output.mkdir(parents=True)
    c.save_json(output/'actual-command.json',{'cwd':INPUTS['source'],'argv':INPUTS['argv'],'environment':environment,'approval_sha256':args.approval_sha256})
    token = uuid.uuid4().hex
    env = {**environment,'STRICT_NATIVE_RUN_TOKEN':token}
    result = {'case_id':args.run,'xtask_wait_exit':None,'driver_wait_exit':None,'external_functional_audit_exit':None,
              'outer_wait_exit':None,'cache_runtime_before':ready['static']['cache_runtime_state'],'release':'unknown','full_function_passed':False,'tool_errors':[],
              'outer_seconds':920,'outer_start':'before Popen; includes build/request/upload/run','independent_board_tool_wait':None}
    child = None
    recorded = None
    start = time.monotonic()
    try:
        try:
            with (output/'xtask.log').open('wb') as stream:
                child = subprocess.Popen(INPUTS['argv'],cwd=INPUTS['source'],env=env,stdin=subprocess.DEVNULL,
                                         stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
                recorded = process_record(child.pid)
                c.save_json(output/'owned-child.json',{**recorded,'token':token,'expected_argv':INPUTS['argv']})
                try:
                    result['xtask_wait_exit'] = child.wait(timeout=max(0.001,920-(time.monotonic()-start)))
                except subprocess.TimeoutExpired:
                    result['outer_timeout'] = True
                    result['tool_errors'].append('outer920 elapsed; stop remaining cases; release unknown')
        finally:
            # The same one bounded cleanup covers failed waits, timeout races and exceptions after Popen.
            if child is not None:
                try:
                    if recorded is None:
                        raise ValueError('exact child ownership record unavailable')
                    result['cleanup'] = cleanup_owned(child,recorded,token)
                    if result['cleanup'].get('owned_group_empty') is not True:
                        result['tool_errors'].append('owned group emptiness unknown; stop remaining cases')
                    if result['cleanup']['signals']:
                        result['tool_errors'].append('forced owned-group cleanup; release unknown; stop remaining cases')
                except Exception as cleanup_error:
                    result['cleanup'] = {'owned_group_empty':None,'release':'unknown'}
                    result['tool_errors'].append('owned cleanup refused: '+str(cleanup_error))
                result['xtask_wait_exit'] = child.poll()
        if (result['xtask_wait_exit'] == 0 and not result.get('outer_timeout')
                and result.get('cleanup',{}).get('owned_group_empty') is True
                and not result['cleanup']['signals']):
            result['release'] = 'explicit-finalize-success'
        capture_start = time.monotonic()
        def capture_expired(signum,frame):
            raise TimeoutError('fixed30-second evidence capture limit elapsed')
        previous_alarm = signal.signal(signal.SIGALRM,capture_expired)
        signal.alarm(INPUTS['limits']['capture_seconds'])
        try:
            capture = c.capture_native(output,output/'xtask.log',args.run)
            result['artifact_chain_complete'] = capture['artifact_chain_complete']
            result['tool_errors'].extend(capture['errors'])
        except Exception as error:
            result['artifact_chain_complete'] = False
            result['tool_errors'].append('capture failed: '+str(error))
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM,previous_alarm)
        result['capture_elapsed_seconds'] = time.monotonic()-capture_start
        if result['capture_elapsed_seconds'] > INPUTS['limits']['capture_seconds']:
            result['tool_errors'].append('bounded evidence capture exceeded30')
        result['cache_runtime_after'] = c.verify_static()['cache_runtime_state']
    except Exception as error:
        result['tool_errors'].append(str(error))
    result['elapsed_seconds'] = time.monotonic()-start
    result['driver_return_code'] = 0 if result['xtask_wait_exit'] == 0 and not result['tool_errors'] else 1
    # Only the external Root parent can record this driver's actual wait result after process exit.
    result['completion_state'] = 'pending-independent-full-function-audit' if result['driver_return_code'] == 0 else 'failed-stop-remaining'
    c.save_json(output/'run-result.json',result)
    return result['driver_return_code']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-ready',action='store_true')
    mode.add_argument('--run',choices=['AB1','AB0','0'])
    parser.add_argument('--approved-manifest')
    parser.add_argument('--approval',type=Path)
    parser.add_argument('--approval-sha256')
    parser.add_argument('--source-manifest-sha')
    args = parser.parse_args()
    try:
        ready = check_ready(args.source_manifest_sha)
        if args.check_ready:
            print('STRICT_NATIVE_READY '+json.dumps(ready,sort_keys=True))
            return 0
        return run_once(args,ready)
    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as error:
        print('STRICT_NATIVE_NOT_READY: '+str(error),flush=True)
        return 2

if __name__ == '__main__':
    sys.exit(main())
