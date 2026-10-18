#!/usr/bin/env python3
"""Prepare the separately identified offline cache-v3 candidate; never starts a target."""
import ast
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

sys.dont_write_bytecode = True

R = Path('/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017')
OUT = R/'raw/strict-native-phase-v3/task1'
OLD = Path('/tmp/crosspath-native-capacity-v2-tools-ksjtks3x')
PARENT = Path('/tmp/crosspath-native-capacity-v2-src-z2au9vz8')
TEMPLATE = Path('/tmp/strict-native-phase-tools-kevemo32/cache/vcpu-runtime-cache')
NORMAL_SHA = '0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb'
ORDINARY_SHA = 'f4bd9bb6dadd056e35faa2b3243a1be410a588f531f6bceb7d71c89e520e3c86'
CAPTURE_SHA = 'e1e573ed9ecd8a1dd77c80d6a06fff3739e4fa8114815cc2b6b5c826206a14b2'
GIT_DIRS = ['branches','objects/info','refs','refs/heads','refs/tags']


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def ident(path):
    p = Path(path); before = p.lstat()
    if stat.S_ISLNK(before.st_mode):
        return {'type':'symlink','target':os.readlink(p)}
    assert stat.S_ISREG(before.st_mode), str(p)
    result = {'bytes':before.st_size,'mode':stat.S_IMODE(before.st_mode),'sha256':sha(p)}
    assert stamp(p) == stamp_value(before), str(p)
    return result


def stamp_value(s):
    return [s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode]


def stamp(path):
    return stamp_value(Path(path).lstat())


def save(path, value):
    Path(path).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')


def load(path):
    return json.loads(Path(path).read_text())


def inventory(root, exclude_cache=False):
    members, directories, stamps = {}, {}, {}
    assert stat.S_ISDIR(root.lstat().st_mode) and not root.is_symlink(), str(root)
    for directory, children, files in os.walk(root,followlinks=False):
        d = Path(directory); rel = str(d.relative_to(root))
        directories[rel] = stat.S_IMODE(d.lstat().st_mode)
        stamps[rel] = stamp(d)
        if exclude_cache and d == root:
            children[:] = [x for x in children if x != 'cache']
        for name in files+[x for x in children if (d/x).is_symlink()]:
            p = d/name; rel = str(p.relative_to(root))
            members[rel] = ident(p); stamps[rel] = stamp(p)
    return dict(sorted(members.items())),dict(sorted(directories.items())),dict(sorted(stamps.items()))


def assert_members(actual, expected, runtime=()):
    assert set(expected) <= set(actual), ('missing',sorted(set(expected)-set(actual)))
    assert set(actual)-set(expected) <= set(runtime), ('extra',sorted(set(actual)-set(expected)))
    changed = [k for k,v in expected.items() if actual[k] != v]
    assert not changed, ('changed',changed[:30])


def paths():
    return {k:Path(v) if k in ('source','tools','target') else v for k,v in load(OUT/'paths.json').items()}


def protected():
    selected = [OLD/'native_once.py',OLD/'capture_native.py',OLD/'inputs.json',OLD/'freeze-manifest.json',OLD/'AB1.once',
                R/'design/phase2-native-cache-topology-v3-plan.md',R/'results/strict-native-cache-v3-design-plan-review-v1.json',
                R/'results/strict-native-trace-capacity-v2-AB1-prepare-failure-v1.json']
    selected += [p for p in (OLD/'evidence').rglob('*') if p.is_file()]
    for subtree in ['raw/strict-native-phase-v2/zephyr-git-readonly-diagnosis-v1','raw/strict-native-phase-v2/AB1']:
        selected += [p for p in (R/subtree).rglob('*') if p.is_file()]
    selected += [R/'raw/strict-native-phase-v1/AB1'/n for n in ['run-result.json','capture.json','actual-command.json']]
    return {str(p):ident(p) for p in sorted(set(selected))}


def command(name, argv, cwd, env, timeout=None, owned=False):
    start_ns = time.time_ns(); start = time.monotonic(); child = None; code = None
    receipt = {'argv':argv,'cwd':str(cwd),'environment':env,'environment_source':'empty inherited environment; exact recorded whitelist',
               'start_unix_ns':start_ns,'timeout_seconds':timeout,'start_new_session':owned}
    with (OUT/(name+'.stdout')).open('wb') as stdout, (OUT/(name+'.stderr')).open('wb') as stderr:
        try:
            child = subprocess.Popen(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=owned)
            receipt['pid'] = child.pid
            if owned:
                sys.path.insert(0,str(OLD))
                import native_once as controller
                receipt['owned_record_at_spawn'] = controller.process_record(child.pid)
            code = child.wait(timeout=max(0.001,timeout-(time.monotonic()-start)) if timeout is not None else None)
        except BaseException as error:
            receipt['exception'] = type(error).__name__+': '+str(error)
            if child is not None and owned:
                # Ordinary successful preparation never reads /proc. Only a real exception
                # activates the unchanged parent's exact token/PGID cleanup guard.
                try:
                    recorded = controller.process_record(child.pid)
                    initial = receipt['owned_record_at_spawn']
                    assert recorded['starttime']==initial['starttime'] and recorded['pgid']==initial['pgid']==child.pid
                    known_exec=[str(Path(env['VIRQ_CACHE_DIR'])/'venv/bin/python3'),str(Path(cwd)/argv[1]),*argv[2:]]
                    assert recorded['argv'] in (argv,known_exec),recorded['argv']
                    receipt['owned_record_on_exception'] = recorded
                    receipt['cleanup'] = controller.cleanup_owned(child,recorded,env['STRICT_NATIVE_RUN_TOKEN'])
                except BaseException as cleanup_error:
                    receipt['cleanup_error'] = type(cleanup_error).__name__+': '+str(cleanup_error)
                finally:
                    if child.poll() is not None:
                        code = child.wait()
            raise
        finally:
            receipt.update(actual_Popen_wait=code,end_unix_ns=time.time_ns(),elapsed_seconds=time.monotonic()-start,
                           stdout=ident(OUT/(name+'.stdout')),stderr=ident(OUT/(name+'.stderr')))
            save(OUT/(name+'.receipt.json'),receipt)
    print(name,'actual_wait=',code,flush=True)
    assert code == 0, (name,code)
    return receipt


def prepare(resume=False):
    if resume:
        p=paths(); source=p['source']; tools=p['tools']; target=p['target']
        ordinary=load(OLD/'evidence/ordinary-identities.json')
        stamps=load(OUT/'parent-source-stamps.before.json')
        assert all(stamp(PARENT/k)==v for k,v in stamps.items()), 'parent source changed'
        actual,dirs,partial_stamps=inventory(source)
        assert set(actual)<=set(ordinary)
        assert all(v==ordinary[k] for k,v in actual.items())
        save(OUT/'source-partial-before-resume.json',{'members':actual,'directories':dirs,'all_partial_members_exact_parent':True})
        assert not list(tools.iterdir()) and not list(target.iterdir())
    else:
        assert not (OUT/'paths.json').exists(), 'candidate already created'
        for path,expected in [(R/'design/phase2-native-cache-topology-v3-plan.md','5e355eb109871df9791d85953ff158dbe54b7416f615aea5a27b3d866e8eeb7d'),
                              (R/'results/strict-native-cache-v3-design-plan-review-v1.json','8230304f179eac906d642078521b1813f4e30d9dabc8e7b06c80b3c5a64d7a9d'),
                              (OLD/'freeze-manifest.json','6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9'),
                              (OLD/'capture_native.py',CAPTURE_SHA),
                              (OLD/'evidence/ordinary-identities.json',ORDINARY_SHA),(OLD/'evidence/sources-702.json',NORMAL_SHA)]:
            assert sha(path) == expected,str(path)
        save(OUT/'protected.before.json',protected())
        space = shutil.disk_usage(OUT)
        save(OUT/'space.before.json',{'total':space.total,'used':space.used,'free':space.free,'archive_budget_bytes':1073741824,'time_ns':time.time_ns()})
        ordinary = load(OLD/'evidence/ordinary-identities.json'); normal = load(OLD/'evidence/sources-702.json')
        assert len(ordinary)==9642 and len(normal)==702
        actual,dirs,stamps = inventory(PARENT)
        assert_members(actual,ordinary)
        assert all(actual[k]['sha256']==v for k,v in normal.items())
        save(OUT/'parent-source-stamps.before.json',stamps)
        source = Path(tempfile.mkdtemp(prefix='crosspath-native-cache-v3-src-'))
        tools = Path(tempfile.mkdtemp(prefix='crosspath-native-cache-v3-tools-'))
        target = Path(tempfile.mkdtemp(prefix='crosspath-native-cache-v3-target-'))
        save(OUT/'paths.json',{'source':str(source),'tools':str(tools),'target':str(target),'hardware_started':0,'qemu_started':0,'target_initial_members':[]})
        print('NEW_PATHS',json.dumps(load(OUT/'paths.json')),flush=True)
    for name,row in ordinary.items():
        assert not any(x in ('.git','target','__pycache__') for x in Path(name).parts),name
        assert Path(name).parts[0]!='cache',name
        dest=source/name; dest.parent.mkdir(parents=True,exist_ok=True)
        assert row.get('type')!='symlink'
        if dest.exists():
            assert ident(dest)==row,name
        else:
            shutil.copy2(PARENT/name,dest)
    shutil.copytree(OLD/'evidence',tools/'evidence',symlinks=True)
    for name in ['native_once.py','capture_native.py']:
        shutil.copy2(OLD/name,tools/name)
    text=(tools/'native_once.py').read_text(); token="ARCHIVE/'raw/strict-native-phase-v2'"
    assert text.count(token)==1
    new=text.replace(token,"ARCHIVE/'raw/strict-native-phase-v3'")
    (tools/'native_once.py').write_text(new)
    (OUT/'native_once.py.patch').write_text(''.join(difflib.unified_diff(text.splitlines(True),new.splitlines(True),fromfile='native_once.py.v2',tofile='native_once.py.v3')))
    inputs=load(OLD/'inputs.json')
    for key,value in [('source',source),('target',target),('execution_tools_root',tools)]:
        inputs[key]=str(value)
    for key in ['AXBUILD_TARGET_DIR','CARGO_TARGET_DIR']:
        inputs['environment'][key]=str(target)
    for key,sub in [('CARGO_HOME','cargo'),('VIRQ_CACHE_DIR','vcpu-runtime-cache'),('CCACHE_DIR','ccache')]:
        inputs['environment'][key]=str(tools/'cache'/sub)
    save(tools/'inputs.json',inputs)
    parent_cache={}; before={}
    for manifest,sub in [('cache-identities.json','vcpu-runtime-cache'),('cargo-cache-identities.json','cargo')]:
        expected=load(OLD/'evidence'/manifest); root=OLD/'cache'/sub
        actual,dirs,stamps=inventory(root)
        runtime=inputs['cache_policy']['cargo_runtime_files'] if sub=='cargo' else {}
        assert_members(actual,expected,runtime)
        if sub=='cargo':
            assert all(not os.path.lexists(root/n) for n in inputs['cache_policy']['cargo_forbidden_roots'])
        parent_cache[sub]={'immutable_count':len(expected),'immutable_manifest':ident(OLD/'evidence'/manifest),
                           'runtime':{k:v for k,v in actual.items() if k not in expected},'directories':len(dirs),'all_immutable_match':True,
                           'files_bytes':sum(v.get('bytes',0) for v in actual.values())}
        before[sub]=stamps
        shutil.copytree(root,tools/'cache'/sub,symlinks=True)
        print('cache copy complete',sub,len(actual),'members',flush=True)
    save(OUT/'parent-cache-verification.before.json',parent_cache)
    save(OUT/'parent-cache-stamps.before.json',before)
    save(OUT/'cargo-bookkeeping.before.json',parent_cache['cargo']['runtime'])
    (tools/'cache/ccache').mkdir()
    observed={}
    for rel in GIT_DIRS:
        template=TEMPLATE/'zephyr/.git'/rel
        assert stat.S_ISDIR(template.lstat().st_mode) and not template.is_symlink()
        assert stat.S_IMODE(template.lstat().st_mode)==0o775
        allowed={'heads','tags'} if rel=='refs' else set()
        assert {p.name for p in template.iterdir()}==allowed,(rel,list(template.iterdir()))
        observed[rel]={'path':str(template),'mode':0o775,'children':sorted(allowed),'stamp':stamp(template)}
        dest=tools/'cache/vcpu-runtime-cache/zephyr/.git'/rel
        assert not dest.exists(),str(dest)
        dest.mkdir(mode=0o775); dest.chmod(0o775)
    save(OUT/'restored-git-directories.json',{'template_observed_readonly':observed,'new_cache_only':True,'mode':0o775,'added':GIT_DIRS})
    save(OUT/'source-copy.json',{'ordinary_files':9642,'source702':702,'ordinary_manifest_sha256':ORDINARY_SHA,'source702_manifest_sha256':NORMAL_SHA,'copy_exact_ordinary_inputs_only':True})
    print('prepared isolated source/cache/tools/target',flush=True)


def relocate():
    p=paths(); source=p['source']; tools=p['tools']; root=tools/'cache/vcpu-runtime-cache'
    parent=load(OLD/'evidence/cache-identities.json')
    approved=load(R/'raw/strict-native-phase-v2/task1/cache-relocation.json')
    names=sorted(row['path'] for row in approved['changes'])
    assert len(names)==13
    prefix=str(OLD/'cache/vcpu-runtime-cache/venv'); replacement=str(root/'venv'); changes=[]
    for rel in names:
        path=root/rel; text=path.read_text(); before=ident(path)
        assert prefix in text,rel
        new=text.replace(prefix,replacement); path.write_text(new)
        assert ident(path)['mode']==before['mode']==parent[rel]['mode']
        changes.append({'path':rel,'old':before,'new':ident(path),'diff':''.join(difflib.unified_diff(text.splitlines(True),new.splitlines(True),fromfile=rel+'.v2',tofile=rel+'.v3'))})
    save(OUT/'cache-relocation.json',{'old_prefix':prefix,'new_prefix':replacement,'changed_count':13,'changes':changes,'scope':'exact inherited 13 venv/bin entries and pyvenv.cfg; no other bytes rewritten'})
    (OUT/'cache-relocation.patch').write_text(''.join(row['diff'] for row in changes))
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
    probe="import sys,json,hashlib,pathlib,cmake; binary=pathlib.Path(cmake.CMAKE_BIN_DIR)/'cmake'; print(json.dumps({'sys_executable':sys.executable,'sys_prefix':sys.prefix,'base_prefix':sys.base_prefix,'interpreter_realpath':str(pathlib.Path(sys.executable).resolve()),'cmake_module':cmake.__file__,'CMAKE_BIN_DIR':cmake.CMAKE_BIN_DIR,'cmake_binary':str(binary),'cmake_binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()},sort_keys=True))"
    command('cache-python-probe',[str(root/'venv/bin/python3'),'-B','-c',probe],source,env)
    result=load(OUT/'cache-python-probe.stdout')
    for key in ['sys_prefix','cmake_module','CMAKE_BIN_DIR','cmake_binary']:
        assert Path(result[key]).resolve().is_relative_to(root.resolve()),(key,result[key])
    assert Path(result['interpreter_realpath']).is_relative_to('/usr/bin')
    save(OUT/'host-python-identity.json',{'realpath':result['interpreter_realpath'],'identity':ident(result['interpreter_realpath'])})
    command('cache-cmake-direct',[str(root/'venv/bin/cmake'),'--version'],source,env)
    save(OUT/'cache-production-entry-link.json',{'probe':result,'direct_entry':ident(root/'venv/bin/cmake'),'module':ident(result['cmake_module']),'cleared':['PYTHONPATH','PYTHONHOME'],'production_prepare':ident(source/'virtualization/axvm/tests/guests/virq/prepare.py')})
    command('zephyr-git-revparse',['git','-C',str(root/'zephyr'),'rev-parse','HEAD'],source,env)
    assert (OUT/'zephyr-git-revparse.stdout').read_text()=='32229d0b6cc60a1906307311b8e79ec483ad1e88\n'
    command('zephyr-git-status',['git','-C',str(root/'zephyr'),'status','--porcelain'],source,{**env,'GIT_OPTIONAL_LOCKS':'0'})
    assert (OUT/'zephyr-git-status.stdout').read_bytes()==b''
    print('real relocated Python/CMake and pinned clean Git entries verified',flush=True)


def host_prepare():
    p=paths(); source=p['source']; tools=p['tools']; root=tools/'cache/vcpu-runtime-cache'
    inputs=load(tools/'inputs.json'); env={**inputs['environment'],**next(x['environment'] for x in inputs['cases'] if x['id']=='AB1')}
    # The original controller's sole ownership variable is the only extra key.
    env['STRICT_NATIVE_RUN_TOKEN']=uuid.uuid4().hex
    spec=importlib.util.spec_from_file_location('candidate_prepare',source/'virtualization/axvm/tests/guests/virq/prepare.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    signature=hashlib.sha256('\n'.join(module.PINNED_PYTHON_PACKAGES).encode()).hexdigest()
    assert (root/'venv/requirements.sha256').read_text().strip()==signature
    for rel in ['venv/bin/python3','venv/bin/cmake','venv/bin/ninja','zephyr/CMakeLists.txt',f'toolchain/{module.TOOLCHAIN_ROOT_NAME}/bin/aarch64-none-elf-gcc']:
        assert (root/rel).is_file(),rel
    for path,row in inputs['external_inputs'].items():
        assert ident(Path(path).resolve())==row,path
    assert not list(p['target'].iterdir())
    save(OUT/'host-prepare-preconditions.json',{'all_existing_inputs_ready':True,'requirements_signature':signature,'no_install_clone_fetch_download_path_needed':True,
         'argv':['python3','virtualization/axvm/tests/guests/virq/prepare.py','--linux-peer'],'cwd':str(source),'environment':env,
         'environment_delta_from_parent_AB1':'only five candidate paths plus original STRICT_NATIVE_RUN_TOKEN ownership marker','budget_seconds':300,'hardware_started':0,'qemu_started':0})
    command('host-prepare',['python3','virtualization/axvm/tests/guests/virq/prepare.py','--linux-peer'],source,env,timeout=300,owned=True)
    stdout=(OUT/'host-prepare.stdout').read_text(); stderr=(OUT/'host-prepare.stderr').read_text()
    assert all(token not in stdout+stderr for token in ['[virq] creating build virtualenv','[virq] cloning Zephyr','[virq] downloading','[virq] unpacking']), 'unexpected new input path'
    out=p['target']/'axbuild/axvm/vcpu-runtime'
    required=['guest/zephyr/zephyr.elf','guest/zephyr/zephyr.bin','guest/zephyr/zephyr.dtb','guest/zephyr/zephyr.dts','guest/zephyr/.config',
              'resources/tests/vcpu-runtime.toml','vm.toml','linux/ordinary-load','linux/build.json','linux/initramfs.cpio.gz','linux/linux.kernel','linux/vm.toml','linux/machine.dtb']
    artifacts={rel:ident(out/rel) for rel in required}
    assert artifacts['linux/ordinary-load']['sha256']=='b9db9b8fc7925bf2c18e2d9edfbd3c0ee10a5a0f57985151e2f7b0073122ffc2'
    assert artifacts['linux/linux.kernel']['sha256']==inputs['external_inputs'][env['VIRQ_LINUX_KERNEL']]['sha256']
    save(OUT/'host-prepare-artifacts.json',{'output':str(out),'artifacts':artifacts,'linux_build':load(out/'linux/build.json'),'resource_text':(out/'resources/tests/vcpu-runtime.toml').read_text(),'hardware_started':0,'qemu_started':0,'normal_host_validation':False})
    print('complete production host_prepare executed once; known worker unchanged',flush=True)


if __name__=='__main__':
    try:
        {'prepare':prepare,'prepare-resume':lambda:prepare(resume=True),'relocate':relocate,'host-prepare':host_prepare}[sys.argv[1]]()
    except BaseException as error:
        save(OUT/(sys.argv[1]+'.first-error.json'),{'type':type(error).__name__,'message':str(error),'time_ns':time.time_ns(),'stop':True})
        raise
