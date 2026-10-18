#!/usr/bin/python3
"""Bind completed original tool evidence without converting failures to success."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json

ROOT = Path('/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017')
OUT = ROOT / 'raw/strict-native-phase-v3'
TOOLS = Path('/tmp/crosspath-native-cache-v3-tools-jrhcn15t')


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reference(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('evidence is not an ordinary file: ' + str(path))
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path)}


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-tool-session', type=int, choices=[77494], required=True)
    parser.add_argument('--actual-tool-exit', type=int, required=True)
    parser.add_argument('--completion-chunk', required=True)
    args = parser.parse_args()
    initial = read(OUT / 'AB1-original-tool-session-v1.json')
    if initial['original_unified_exec_session'] != args.original_tool_session:
        raise ValueError('original tool session differs')
    # Root supplies these two values only after receiving the original tool's
    # terminal result. Process absence or a successful Guest line is insufficient.
    if not args.completion_chunk:
        raise ValueError('actual terminal tool chunk is required')
    wait_path = OUT / 'AB1-root-wait.json'
    wait = read(wait_path)
    result_path = OUT / 'AB1/run-result.json'
    run = read(result_path) if result_path.is_file() else {}
    completion_path = OUT / 'AB1-root-supervisor-completion-v1.json'
    save(completion_path, {
        'actual_unified_exec_exit': args.actual_tool_exit,
        'completion_tool_chunk': args.completion_chunk,
        'driver_Popen_wait_from_own_parent': wait.get('driver_wait_exit'),
        'driver_Popen_wait_receipt_sha256': digest(wait_path),
        'original_unified_exec_session': args.original_tool_session,
        'observed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope': 'original exact tool completion; never inferred from proc absence',
    })
    paths = {
        'raw': OUT / 'AB1/xtask.log',
        'run_result': result_path,
        'capture': OUT / 'AB1/capture.json',
        'actual_command': OUT / 'AB1/actual-command.json',
        'root_wait': wait_path,
        'root_launch': OUT / 'AB1-root-launch.json',
        'root_tool_completion': completion_path,
        'approval': OUT / 'AB1-root-approval-v1.json',
        'host_preflight': OUT / 'AB1-host-preflight-v1.json',
        'frozen_inputs': TOOLS / 'inputs.json',
        'freeze_manifest': TOOLS / 'freeze-manifest.json',
        'primary_delivery': ROOT / 'results/intensity-v3-final-delivery.json',
        'task1_Spec': ROOT / 'results/strict-native-cache-v3-task1-spec-review-v1.json',
        'task1_Quality': ROOT / 'results/strict-native-cache-v3-task1-quality-review-v1.json',
        'task1_acceptance': ROOT / 'results/strict-native-cache-v3-task1-root-acceptance-v1.json',
        'wrapper_review': ROOT / 'results/strict-native-cache-v3-AB1-wrapper-inheritance-review-v1.json',
        'normal_auditor_Quality': ROOT / 'results/strict-native-function-audit-v3-quality-review-v1.json',
    }
    missing = [label for label, path in paths.items() if not path.is_file()]
    files = {label: reference(path) for label, path in paths.items() if path.is_file()}
    signals = run.get('cleanup', {}).get('signals')
    handoff = {
        'schema_version': 1, 'state': 'final', 'case_id': 'AB1',
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope': 'actual final evidence; pending independent complete normal-function audit',
        'source_702_sha256': read(TOOLS / 'inputs.json')['normal702_sha256'],
        'tools_freeze_sha256': digest(TOOLS / 'freeze-manifest.json'),
        'actual_xtask_wait_exit': run.get('xtask_wait_exit'),
        'actual_driver_wait_exit': wait.get('driver_wait_exit'),
        'actual_root_wait_exit': args.actual_tool_exit,
        'forced_stop': bool(signals) if isinstance(signals, list) else None,
        'forced_signals': signals,
        'artifact_chain_complete': run.get('artifact_chain_complete'),
        'release': run.get('release', 'unknown'),
        'case_quota_consumed': (TOOLS / 'AB1.once').is_file(),
        'later_cases_unexecuted': [case for case in ('AB0', '0')
                                   if not (TOOLS / (case + '.once')).exists()
                                   and not (OUT / case).exists()],
        'files': files, 'missing_evidence': missing,
        'normal_function_passed': False, 'M2': False, 'Joint': False, 'goal_complete': False,
    }
    path = OUT / 'AB1-root-final-handoff-v1.json'
    save(path, handoff)
    print(json.dumps({'path': str(path), 'sha256': digest(path),
                      'bound_files': len(files), 'missing_evidence': missing,
                      'actual_root_wait_exit': args.actual_tool_exit}, sort_keys=True))


if __name__ == '__main__':
    main()
