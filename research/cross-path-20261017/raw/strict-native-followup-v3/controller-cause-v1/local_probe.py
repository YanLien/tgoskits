#!/usr/bin/env python3
"""Read-only AB1 evidence inventory and narrowly owned local controller probes."""
import ast
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

OUT = Path(__file__).resolve().parent
R = OUT.parents[2]
TOOLS = Path('/tmp/crosspath-native-cache-v3-tools-jrhcn15t')
SOURCE = Path('/tmp/crosspath-native-cache-v3-src-hr23qnrs')
NATIVE = TOOLS / 'native_once.py'
OWN_PID = None
OWNER_CLEANUP = False
AUDIT = {'proc_reads': [], 'root_proc_enumeration': 0, 'blocked_signals': [], 'owner_signals': []}


def save(name, value):
    with (OUT / name).open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write('\n')


def identity(path):
    b = path.read_bytes()
    s = path.stat()
    return {'path': str(path), 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'mtime_ns': s.st_mtime_ns, 'mode': s.st_mode & 0o777}


refs = [p for p in sorted((R / 'raw/strict-native-phase-v3/AB1').rglob('*')) if p.is_file()]
refs += [R / 'raw/strict-native-phase-v3' / n for n in [
    'AB1-root-launch.json', 'AB1-root-wait.json', 'AB1-root-final-handoff-v1.json',
    'AB1-root-supervisor-completion-v1.json', 'AB1-host-terminal-observation-v1.json']]
refs += [TOOLS / n for n in ['native_once.py', 'capture_native.py', 'inputs.json', 'freeze-manifest.json', 'AB1.once']]
refs += [SOURCE / n for n in ['.cargo/config.toml', 'rust-toolchain.toml', 'xtask/Cargo.toml',
    'xtask/src/main.rs', 'scripts/axbuild/src/context/mod.rs']]
before = [identity(p) for p in refs]
save('existing-evidence.before.json', before)

# This one local version command cannot select a project, download a toolchain,
# or touch the failed candidate's Cargo cache or target directory.
scratch = Path(tempfile.mkdtemp(prefix='strict-native-controller-cause-v1-'))
for n in ['cargo-home', 'target', 'cwd']:
    (scratch / n).mkdir()
cargo = Path('/home/yanlien/.cargo/bin/cargo')
rustup = cargo.resolve()
installed = Path('/home/yanlien/.rustup/toolchains/nightly-2026-09-04-x86_64-unknown-linux-gnu/bin/cargo')
env = {k: os.environ[k] for k in ['HOME', 'USER', 'LOGNAME', 'LANG'] if k in os.environ}
env.update({'PATH': '/home/yanlien/.cargo/bin:/usr/bin:/bin',
            'RUSTUP_HOME': '/home/yanlien/.rustup',
            'RUSTUP_TOOLCHAIN': 'nightly-2026-09-04-x86_64-unknown-linux-gnu',
            'RUSTUP_AUTO_INSTALL': '0', 'CARGO_NET_OFFLINE': 'true',
            'CARGO_HOME': str(scratch / 'cargo-home'), 'CARGO_TARGET_DIR': str(scratch / 'target')})
argv = ['/usr/bin/strace', '-f', '-e', 'trace=execve,execveat', '-s', '4096',
        '-o', str(OUT / 'cargo-version.execve.log'), str(cargo), '--version']
with (OUT / 'cargo-version.stdout').open('xb') as out, (OUT / 'cargo-version.stderr').open('xb') as err:
    version = subprocess.Popen(argv, cwd=scratch / 'cwd', env=env,
                               stdin=subprocess.DEVNULL, stdout=out, stderr=err)
    version_pid = version.pid
    version_exit = version.wait(timeout=15)
save('cargo-version.receipt.json', {
    'argv': argv, 'cwd': str(scratch / 'cwd'), 'environment': env,
    'strace_original_Popen_pid': version_pid, 'actual_parent_wait_exit': version_exit,
    'cargo_symlink': {'path': str(cargo), 'link_target': os.readlink(cargo), 'resolved': str(rustup)},
    'binaries': [identity(Path('/usr/bin/strace')), identity(rustup), identity(installed)],
    'scope': 'One installed cargo --version, isolated Cargo home/target/cwd; no project build/test or network request requested.',
    'not_historical_AB1_argv': True})

native_source = NATIVE.read_text()
tree = ast.parse(native_source, filename=str(NATIVE))
selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ['process_record', 'cleanup_owned']]
assert len(selected) == 2


def audit(event, args):
    if event in ['os.listdir', 'os.scandir'] and os.fspath(args[0]) == '/proc':
        AUDIT['root_proc_enumeration'] += 1
        raise PermissionError('Host /proc enumeration prohibited by diagnostic guard')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        path = os.fsdecode(args[0])
        if path.startswith('/proc/'):
            allowed = {f'/proc/{OWN_PID}/{name}' for name in ['stat', 'cmdline', 'environ']}
            if path not in allowed:
                raise PermissionError('Only exact newly owned test child /proc reads allowed')
            AUDIT['proc_reads'].append(path)
    if event == 'os.killpg':
        AUDIT['blocked_signals'].append({'event': event, 'pid': args[0], 'signal': args[1]})
        raise PermissionError('Frozen cleanup signals prohibited by diagnostic guard')
    if event == 'os.kill':
        if not OWNER_CLEANUP or args[0] != OWN_PID:
            AUDIT['blocked_signals'].append({'event': event, 'pid': args[0], 'signal': args[1]})
            raise PermissionError('Only owner exact new test child cleanup is authorized')
        AUDIT['owner_signals'].append({'pid': args[0], 'signal': args[1]})


sys.addaudithook(audit)


class ScopedPath(type(Path())):
    """Restrict frozen cleanup's enumeration to the new test child, without scanning."""
    def iterdir(self):
        if str(self) == '/proc':
            assert OWN_PID is not None
            return iter([ScopedPath('/proc') / str(OWN_PID)])
        return super().iterdir()


namespace = {'Path': ScopedPath, 'os': os, 'time': time, 'signal': signal,
             'INPUTS': {'limits': {'cleanup_seconds': 10}}, 'PROTECTED_PID': 1666583}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(NATIVE), 'exec'), namespace)
process_record = namespace['process_record']
cleanup_owned = namespace['cleanup_owned']

stage1 = """import os, sys, time
from pathlib import Path
root = Path(sys.argv[1])
(root / 'stage1.ready').write_text('ready')
while not (root / 'exec.go').exists():
    time.sleep(0.005)
os.execve(sys.executable, [sys.executable, '-B', str(root / 'stage2.py'), str(root)], dict(os.environ))
"""
stage2 = """import sys, time
from pathlib import Path
root = Path(sys.argv[1])
(root / 'stage2.ready').write_text('ready')
while not (root / 'exit.go').exists():
    time.sleep(0.005)
sys.exit(23)
"""
for name, code in [('stage1.py', stage1), ('stage2.py', stage2)]:
    (scratch / name).write_text(code)
    with (OUT / ('probe-child-' + name)).open('x') as stream:
        stream.write(code)
token = uuid.uuid4().hex
child_env = dict(os.environ)
child_env['STRICT_NATIVE_RUN_TOKEN'] = token
child_argv = ['/usr/bin/python3', '-B', str(scratch / 'stage1.py'), str(scratch)]
with (OUT / 'exec-child.stdout').open('xb') as out, (OUT / 'exec-child.stderr').open('xb') as err:
    child = subprocess.Popen(child_argv, cwd=scratch, env=child_env, stdin=subprocess.DEVNULL,
                             stdout=out, stderr=err, start_new_session=True)
    OWN_PID = child.pid
    recorded = None
    probe = {'child_argv': child_argv, 'scratch': str(scratch), 'actual_parent_wait_exit': None}
    def wait_file(name):
        deadline = time.monotonic() + 5
        while not (scratch / name).exists():
            if time.monotonic() >= deadline:
                raise TimeoutError('own child handshake timed out: ' + name)
            if child.poll() is not None:
                raise RuntimeError('own child exited before handshake: ' + name)
            time.sleep(0.005)
    def token_present():
        return ('STRICT_NATIVE_RUN_TOKEN=' + token).encode() in (Path('/proc') / str(OWN_PID) / 'environ').read_bytes().split(b'\0')
    try:
        wait_file('stage1.ready')
        recorded = process_record(OWN_PID)
        first_token = token_present()
        (scratch / 'exec.go').write_text('go')
        wait_file('stage2.ready')
        after_exec = process_record(OWN_PID)
        second_token = token_present()
        probe.update({'before_exec': recorded, 'after_exec': after_exec,
                      'same_pid_starttime_pgid': all(recorded[k] == after_exec[k] for k in ['pid', 'starttime', 'pgid']),
                      'same_token_present_before_and_after': first_token and second_token,
                      'actual_argv_changed': recorded['argv'] != after_exec['argv'],
                      'pre_cleanup_poll': child.poll()})
        try:
            cleanup_result = cleanup_owned(child, recorded, token)
            probe['cleanup_returned'] = cleanup_result
        except Exception as error:
            probe['cleanup_exception'] = {'type': type(error).__name__, 'message': str(error)}
        probe['post_cleanup_poll'] = child.poll()
        (scratch / 'exit.go').write_text('go')
        probe['actual_parent_wait_exit'] = child.wait(timeout=5)
    finally:
        if child.poll() is None:
            current = process_record(OWN_PID)
            assert recorded is not None
            assert all(current[k] == recorded[k] for k in ['pid', 'starttime', 'pgid'])
            OWNER_CLEANUP = True
            try:
                child.terminate()
                probe['exception_cleanup_actual_wait_exit'] = child.wait(timeout=5)
            finally:
                OWNER_CLEANUP = False

probe.update({'frozen_source': identity(NATIVE),
              'functions': {n.name: {'start_line': n.lineno, 'end_line': n.end_lineno,
                   'source_sha256': hashlib.sha256(ast.get_source_segment(native_source, n).encode()).hexdigest()} for n in selected},
              'function_AST_unmodified': True,
              'test_Path_scope': 'Only /proc enumeration replaced with the exact new owned test PID; process stat/cmdline/environ read from the real kernel.',
              'all_test_child_Popen_waits_real': True, 'not_hardware_exit_evidence': True, 'audit': AUDIT})
save('exec-cleanup.receipt.json', probe)

after = [identity(p) for p in refs]
save('existing-evidence.after.json', after)
unchanged = before == after
assert unchanged, 'Existing evidence/source/tool bytes or metadata changed'
assert version_exit == 0
assert probe['same_pid_starttime_pgid'] and probe['same_token_present_before_and_after']
assert probe['actual_argv_changed']
assert probe['cleanup_exception'] == {'type': 'ValueError', 'message': 'owned group leader argv changed'}
assert probe['pre_cleanup_poll'] is None and probe['post_cleanup_poll'] is None
assert probe['actual_parent_wait_exit'] == 23
assert AUDIT['root_proc_enumeration'] == 0 and not AUDIT['blocked_signals'] and not AUDIT['owner_signals']
save('probe-summary.json', {'all_assertions_passed': True, 'existing_evidence_unchanged': unchanged,
                          'cargo_version_actual_wait_exit': version_exit, 'exec_child_actual_wait_exit': 23,
                          'signals_sent': [], 'host_proc_scans': 0,
                          'original_AB1_PID_read_or_signalled': False})
print(json.dumps({'output': str(OUT), 'all_assertions_passed': True,
                  'existing_references_checked': len(refs), 'cargo_version_actual_wait_exit': version_exit,
                  'exec_child_actual_wait_exit': 23, 'host_proc_scans': 0, 'signals_sent': []}))
