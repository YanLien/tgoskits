#!/usr/bin/env python3
"""Offline capacity-v2 preparation; never launches a hardware or QEMU command."""
import difflib
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

R = Path('/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017')
OUT = R/'raw/strict-native-phase-v2/task1'
OLD = Path('/tmp/strict-native-phase-tools-kevemo32')
PARENT = Path('/tmp/crosspath-strict-native-src-ii_h4jde')
REPO = R.parent.parent
CAPTURE = R/'raw/strict-native-followup-v1/fit-capture-repair-v1/repaired/capture_native.py'
CHANGED = 'virtualization/axvm/src/diagnostics.rs'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def ident(path):
    p = Path(path)
    s = p.lstat()
    if stat.S_ISLNK(s.st_mode):
        return {'type':'symlink', 'target':os.readlink(p)}
    assert stat.S_ISREG(s.st_mode), str(p)
    row = {'bytes':s.st_size, 'mode':stat.S_IMODE(s.st_mode), 'sha256':sha(p)}
    a = p.lstat()
    assert (s.st_ino,s.st_size,s.st_mtime_ns) == (a.st_ino,a.st_size,a.st_mtime_ns), str(p)
    return row


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def load(path):
    return json.loads(Path(path).read_text())


def inventory(root):
    out = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in files + [x for x in dirs if (Path(directory)/x).is_symlink()]:
            p = Path(directory)/name
            out[str(p.relative_to(root))] = ident(p)
    return dict(sorted(out.items()))


def check(root, expected, runtime=()):
    actual = inventory(root)
    assert set(expected) <= set(actual), ('missing', sorted(set(expected)-set(actual)))
    assert set(actual)-set(expected) <= set(runtime), ('extra',sorted(set(actual)-set(expected)))
    changed = [k for k in expected if expected[k] != actual[k]]
    assert not changed, ('changed', changed[:20])
    return actual


def copy_manifest(src, dst, manifest):
    for name, row in manifest.items():
        p, q = src/name, dst/name
        q.parent.mkdir(parents=True, exist_ok=True)
        if row.get('type') == 'symlink':
            q.symlink_to(row['target'])
        else:
            shutil.copy2(p,q)


def command(name, argv, cwd, env):
    before = time.time_ns()
    with (OUT/(name+'.stdout')).open('wb') as stdout, (OUT/(name+'.stderr')).open('wb') as stderr:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        code = child.wait()
    receipt = {'argv':argv,'cwd':str(cwd),'environment':env,'environment_source':'empty inherited environment; explicit whitelist exactly as recorded; Cargo checks use parent inputs with only candidate paths replaced, local probes use their recorded minimal whitelist',
               'pid':child.pid,'actual_Popen_wait':code,'start_unix_ns':before,'end_unix_ns':time.time_ns(),
               'stdout':ident(OUT/(name+'.stdout')),'stderr':ident(OUT/(name+'.stderr'))}
    save(OUT/(name+'.receipt.json'),receipt)
    print(name, 'actual_wait=',code, flush=True)
    return code


def protected():
    paths = [OLD/'native_once.py',OLD/'capture_native.py',OLD/'inputs.json',OLD/'freeze-manifest.json',OLD/'offline-check.py',OLD/'AB1.once',
             R/'design/phase2-native-trace-capacity-v2-design.md',R/'design/phase2-native-trace-capacity-v2-plan.md',R/'design/phase2-native-trace-capacity-v2-plan-v2.md',
             R/'results/strict-native-trace-capacity-v2-design-plan-review-v1.json',R/'results/strict-native-trace-capacity-v2-design-plan-review-v2.json',
             R/'results/strict-native-fit-capture-repair-root-acceptance-v1.json',CAPTURE]
    paths += [p for p in (OLD/'evidence').rglob('*') if p.is_file()]
    paths += [R/'raw/strict-native-phase-v1/AB1'/name for name in ('run-result.json','capture.json','actual-command.json')]
    return {str(p):ident(p) for p in sorted(paths)}


def prepare():
    assert not (OUT/'paths.json').exists(), 'candidate already created'
    assert sha(OLD/'evidence/sources-702.json') == '9e2fe24f40d95cf54390ad476d89c8162e2bfba9e257966a4a2cb3b9c31b918f'
    assert sha(OLD/'evidence/sources-702.tar.gz') == '51e1c5430da0cd4cc3e0538fd925f58da17e093f0e0aea94ae3d7cbc3a4d2b05'
    assert sha(CAPTURE) == 'e1e573ed9ecd8a1dd77c80d6a06fff3739e4fa8114815cc2b6b5c826206a14b2'
    expected = {
        'design/phase2-native-trace-capacity-v2-design.md':'5dbf286e5275dde7f8553de3785835b246f8df6ef7ad2b2e010bbe9357bb3ccd',
        'design/phase2-native-trace-capacity-v2-plan-v2.md':'54a43488604d56ea9bf02b5cdf06d1ab9b6d8bceb4248f91504c00e491534e27',
        'results/strict-native-trace-capacity-v2-design-plan-review-v2.json':'df19eac41e66bbb608ec7ee944bd55aac404ab6629de778ce997529848fae4fd',
        'results/strict-native-fit-capture-repair-root-acceptance-v1.json':'5245d7a61f00710a6e11bb7adf0fc3e9c64a0432aa4ccecfd71931207707a1dc'}
    for rel, value in expected.items():
        assert sha(R/rel) == value, rel
    save(OUT/'protected.before.json', protected())
    space = shutil.disk_usage(OUT)
    save(OUT/'space.before.json', {'total':space.total,'used':space.used,'free':space.free,'archive_budget_bytes':1073741824,'time_ns':time.time_ns()})
    ordinary = load(OLD/'evidence/ordinary-identities.json')
    normal = load(OLD/'evidence/sources-702.json')
    assert len(normal) == 702
    check(PARENT, ordinary)
    assert all(sha(PARENT/k) == v for k,v in normal.items())
    for name in ordinary:
        assert not any(part in ('.git','target','__pycache__') for part in Path(name).parts), name
        assert Path(name).parts[0] != 'cache', name
    source = Path(tempfile.mkdtemp(prefix='crosspath-native-capacity-v2-src-'))
    tools = Path(tempfile.mkdtemp(prefix='crosspath-native-capacity-v2-tools-'))
    target = Path(tempfile.mkdtemp(prefix='crosspath-native-capacity-v2-target-'))
    paths = {'source':str(source),'tools':str(tools),'target':str(target),'hardware_started':0,'target_initial_members':list(target.iterdir())}
    save(OUT/'paths.json', paths)
    print(json.dumps(paths),flush=True)
    copy_manifest(PARENT,source,ordinary)
    check(source,ordinary)
    shutil.copytree(OLD/'evidence',tools/'evidence')
    shutil.copy2(OLD/'native_once.py',tools/'native_once.py')
    shutil.copy2(CAPTURE,tools/'capture_native.py')
    text = (tools/'native_once.py').read_text()
    assert text.count("ARCHIVE/'raw/strict-native-phase-v1'") == 1
    (tools/'native_once.py').write_text(text.replace("ARCHIVE/'raw/strict-native-phase-v1'", "ARCHIVE/'raw/strict-native-phase-v2'"))
    (OUT/'native_once.py.patch').write_text(''.join(difflib.unified_diff(text.splitlines(True),(tools/'native_once.py').read_text().splitlines(True),fromfile='native_once.py.parent',tofile='native_once.py.capacity-v2')))
    inputs = load(OLD/'inputs.json')
    for key in ('source','target','execution_tools_root'):
        inputs[key] = str({'source':source,'target':target,'execution_tools_root':tools}[key])
    for key in ('AXBUILD_TARGET_DIR','CARGO_TARGET_DIR'):
        inputs['environment'][key] = str(target)
    for key, sub in [('CARGO_HOME','cargo'),('VIRQ_CACHE_DIR','vcpu-runtime-cache'),('CCACHE_DIR','ccache')]:
        inputs['environment'][key] = str(tools/'cache'/sub)
    save(tools/'inputs.json',inputs)
    old_cargo = OLD/'cache/cargo'
    old_virq = OLD/'cache/vcpu-runtime-cache'
    cm = load(OLD/'evidence/cargo-cache-identities.json')
    vm = load(OLD/'evidence/cache-identities.json')
    cargo_actual = check(old_cargo, cm, inputs['cache_policy']['cargo_runtime_files'])
    check(old_virq,vm)
    save(OUT/'old-cache-verification.before.json',{'cargo_manifest_sha256':sha(OLD/'evidence/cargo-cache-identities.json'),'virq_manifest_sha256':sha(OLD/'evidence/cache-identities.json'),'cargo_immutable_count':len(cm),'virq_count':len(vm),'cargo_runtime':{k:v for k,v in cargo_actual.items() if k not in cm},'all_immutable_match':True})
    print('old cache fully verified',flush=True)
    copy_manifest(old_cargo,tools/'cache/cargo',cm)
    copy_manifest(old_virq,tools/'cache/vcpu-runtime-cache',vm)
    (tools/'cache/ccache').mkdir()
    check(tools/'cache/cargo',cm)
    check(tools/'cache/vcpu-runtime-cache',vm)
    save(OUT/'cargo-bookkeeping.before.json',{})
    save(OUT/'parent-ordinary-check.json',{'ordinary_files':len(ordinary),'normal702':len(normal),'all_exact':True,'copied_from_exact_manifest_only':True,'excluded_components':['.git','target','cache','__pycache__','old runtime outputs absent from approved ordinary manifest']})
    print('source and private caches copied, verified',flush=True)


def relocate():
    paths = load(OUT/'paths.json'); tools=Path(paths['tools']); source=Path(paths['source'])
    root=tools/'cache/vcpu-runtime-cache'; oldroot=OLD/'cache/vcpu-runtime-cache'
    old_metadata = [p for p in (oldroot/'venv/bin').iterdir() if p.is_file() and not p.is_symlink()]
    old_metadata += [oldroot/'venv/pyvenv.cfg']
    current_prefix = str(oldroot/'venv')
    # Historic origin is a metadata string, never an input directory read.
    historical = '/home/yanlien/Program/hypervisor/tgoskits/target/axbuild/axvm/vcpu-runtime-cache/venv'
    prefixes = {current_prefix:str(root/'venv'),historical:str(root/'venv')}
    hits=[]; changes=[]
    for p in sorted(old_metadata):
        data = p.read_bytes()
        try:
            text=data.decode()
        except UnicodeDecodeError:
            hits.append({'path':str(p.relative_to(oldroot)),'kind':'binary entry; inspected, no text rewrite','sha256':sha(p)})
            continue
        found = [prefix for prefix in prefixes if prefix in text]
        # Discover any other historical absolute venv prefix in eligible metadata.
        import re
        discovered = sorted(set(re.findall(r'/(?:[^\s\'"=;:<>])+?/vcpu-runtime-cache/venv',text)))
        for prefix in discovered:
            if prefix not in prefixes:
                prefixes[prefix]=str(root/'venv')
        found = [prefix for prefix in prefixes if prefix in text]
        if not found:
            continue
        rel=str(p.relative_to(oldroot)); q=root/rel
        new = text
        for prefix in found:
            new=new.replace(prefix,prefixes[prefix])
        before=ident(q)
        q.write_text(new)
        after=ident(q)
        diff=''.join(difflib.unified_diff(text.splitlines(True),new.splitlines(True),fromfile=rel+'.parent',tofile=rel+'.capacity-v2'))
        changes.append({'path':rel,'old':before,'new':after,'old_prefixes':found,'reason':'relocate copied venv execution entry or activation/creation metadata to private candidate cache','diff':diff})
        hits.append({'path':rel,'kind':'relocated execution or metadata','prefixes':found})
    assert any(x['path']=='venv/bin/cmake' for x in changes)
    # The approved scope is exactly bin entries and pyvenv.cfg; all other bytes must remain equal.
    parent = load(OLD/'evidence/cache-identities.json'); actual=inventory(root)
    assert set(actual)==set(parent)
    changed=[k for k in parent if actual[k]!=parent[k]]
    assert sorted(changed)==sorted(x['path'] for x in changes)
    for k in changed:
        assert k.startswith('venv/bin/') or k=='venv/pyvenv.cfg'
        assert actual[k]['mode']==parent[k]['mode']
    for p in list((root/'venv/bin').iterdir())+[root/'venv/pyvenv.cfg']:
        if p.is_file() and not p.is_symlink():
            data=p.read_bytes()
            assert all(old.encode() not in data for old in prefixes), str(p)
    save(OUT/'cache-relocation.json',{'prefix_replacements':prefixes,'scan_scope':'venv/bin ordinary entries plus pyvenv.cfg (activation files are in bin); no other directory rewritten','scanned':[str(p.relative_to(oldroot)) for p in old_metadata],'hits':hits,'changes':changes,'changed_count':len(changes),'all_other_cache_members_unchanged':True,'system_python_links':{k:v for k,v in actual.items() if k.startswith('venv/bin/python') and v.get('type')=='symlink'},'legacy_prefix_elsewhere_policy':'vendored code, site-packages, ELF and provenance content retained byte-identical; no whole-directory replacement'})
    (OUT/'cache-relocation.patch').write_text(''.join(x['diff'] for x in changes))
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
    python=str(root/'venv/bin/python3')
    probe="import sys,json,hashlib,pathlib,cmake; binary=pathlib.Path(cmake.CMAKE_BIN_DIR)/'cmake'; print(json.dumps({'sys_executable':sys.executable,'sys_prefix':sys.prefix,'base_prefix':sys.base_prefix,'interpreter_realpath':str(pathlib.Path(sys.executable).resolve()),'cmake_module':cmake.__file__,'CMAKE_BIN_DIR':cmake.CMAKE_BIN_DIR,'cmake_binary':str(binary),'cmake_binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()},sort_keys=True))"
    assert command('cache-python-probe',[python,'-B','-c',probe],source,env)==0
    result=json.loads((OUT/'cache-python-probe.stdout').read_text())
    for k in ('sys_prefix','cmake_module','CMAKE_BIN_DIR','cmake_binary'):
        assert Path(result[k]).resolve().is_relative_to(root.resolve()), (k,result[k])
    assert Path(result['interpreter_realpath']).is_relative_to('/usr/bin')
    save(OUT/'host-python-identity.json',{'realpath':result['interpreter_realpath'],'identity':ident(Path(result['interpreter_realpath'])),'venv_has_independent_python_binary':False})
    assert command('cache-cmake-direct',[str(root/'venv/bin/cmake'),'--version'],source,env)==0
    module=Path(result['cmake_module'])
    save(OUT/'cache-production-entry-link.json',{'entry':str(root/'venv/bin/cmake'),'entry_identity':ident(root/'venv/bin/cmake'),'entry_text':(root/'venv/bin/cmake').read_text(),'cmake_module':str(module),'module_identity':ident(module),'module_text':module.read_text(),'probe':result,'production_prepare':{'path':'virtualization/axvm/tests/guests/virq/prepare.py','identity':ident(source/'virtualization/axvm/tests/guests/virq/prepare.py')},'no_legacy_cache_runtime_escape':True,'cleared':['PYTHONPATH','PYTHONHOME'],'actual_entry_wait':load(OUT/'cache-cmake-direct.receipt.json')['actual_Popen_wait']})
    # Execution is permitted to read local code, never alter the frozen inputs.
    check(root, actual)
    save(tools/'evidence/cache-identities.json',actual)
    save(tools/'evidence/cargo-cache-identities.json',inventory(tools/'cache/cargo'))
    print('cache relocation and direct production-entry proof PASS',flush=True)


def rust_checks():
    paths=load(OUT/'paths.json'); source=Path(paths['source']); tools=Path(paths['tools'])
    path=source/CHANGED
    old=(PARENT/CHANGED).read_text()
    assert path.read_text()==old
    token='const CAPACITY: usize = 16_384;'
    replacement='// Measurement capacity uses 10 MiB of slots across four CPUs.\n// Its memory cost requires new matched recording-on/off measurements.\nconst CAPACITY: usize = 65_536;'
    assert old.count(token)==1
    path.write_text(old.replace(token,replacement))
    env=load(tools/'inputs.json')['environment']
    assert command('cargo-fmt',['cargo','fmt','-p','axvm'],source,env)==0
    ordinary=load(OLD/'evidence/ordinary-identities.json')
    formatted=inventory(source)
    assert set(formatted)==set(ordinary)
    collateral=[k for k in ordinary if k!=CHANGED and ordinary[k]!=formatted[k]]
    restored=[]
    for name in collateral:
        before=(source/name).read_text()
        after=(PARENT/name).read_text()
        patch=''.join(difflib.unified_diff(after.splitlines(True),before.splitlines(True),fromfile=name+'.parent',tofile=name+'.formatted'))
        restored.append({'path':name,'formatted_identity':formatted[name],'parent_identity':ordinary[name],'format_diff':patch,'action':'restored exact parent bytes/mode after package fmt'})
        shutil.copy2(PARENT/name,source/name)
    save(OUT/'fmt-collateral-restored.json',restored)
    assert command('cargo-xtask-clippy',['cargo','xtask','clippy','--package','axvm'],source,env)==0
    final=inventory(source)
    assert set(final)==set(ordinary), ('member difference',sorted(set(final)^set(ordinary)))
    diff=[k for k in ordinary if ordinary[k]!=final[k]]
    assert diff==[CHANGED], diff
    assert sha(source/'Cargo.lock')==load(OLD/'evidence/sources-702.json')['Cargo.lock']
    (OUT/'diagnostics.rs.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True),path.read_text().splitlines(True),fromfile=CHANGED+'.parent',tofile=CHANGED+'.capacity-v2')))
    save(OUT/'source-post-validation.json',{'ordinary_files':len(final),'parent702_unchanged':701,'changed':[CHANGED],'Cargo.lock':ident(source/'Cargo.lock'),'all_other_ordinary_bytes_modes_equal':True,'fmt_unrelated_restored':restored,'capacity_before':16384,'capacity_after':65536,'four_cpu_slots_before_bytes':2621440,'four_cpu_slots_after_bytes':10485760,'recording_algorithm_unchanged':True,'runtime_zero_loss_not_proven':True})
    cm=load(tools/'evidence/cargo-cache-identities.json'); vm=load(tools/'evidence/cache-identities.json')
    cargo=check(tools/'cache/cargo',cm,load(tools/'inputs.json')['cache_policy']['cargo_runtime_files'])
    check(tools/'cache/vcpu-runtime-cache',vm)
    save(OUT/'cargo-bookkeeping.after.json',{k:v for k,v in cargo.items() if k not in cm})
    save(OUT/'cache-post-validation.json',{'virq_immutable_equal':True,'cargo_immutable_equal':True,'cargo_immutable_files':len(cm),'virq_members':len(vm),'runtime_manifest_separate':True})
    print('Rust fmt/xtask Clippy and unchanged-source/cache gates PASS',flush=True)


def freeze():
    paths=load(OUT/'paths.json'); source=Path(paths['source']); tools=Path(paths['tools'])
    evidence=tools/'evidence'
    assert not (tools/'freeze-manifest.json').exists()
    for n in ('sources-702.json','ordinary-identities.json','cache-identities.json','cargo-cache-identities.json','inputs.json'):
        parent=OLD/n if n=='inputs.json' else OLD/'evidence'/n
        shutil.copy2(parent,evidence/('capacity-v2-parent-'+n))
    for n in ('cache-provenance.json','cargo-cache-provenance.json','preparation.json'):
        shutil.copy2(OLD/'evidence'/n,evidence/('capacity-v2-parent-'+n))
    ordinary=inventory(source)
    normal=load(OLD/'evidence/sources-702.json')
    assert len(normal)==702
    changed=[k for k,v in normal.items() if sha(source/k)!=v]
    assert changed==[CHANGED],changed
    new_normal={k:sha(source/k) for k in normal}
    save(evidence/'sources-702.json',new_normal)
    save(evidence/'ordinary-identities.json',ordinary)
    controls=load(OLD/'evidence/control-identities.json')
    assert all(ordinary[k]==v for k,v in controls.items())
    save(evidence/'control-identities.json',{k:ordinary[k] for k in controls})
    inputs=load(tools/'inputs.json')
    inputs['normal702_sha256']=sha(evidence/'sources-702.json')
    save(tools/'inputs.json',inputs)
    parent_inputs=load(OLD/'inputs.json')
    expected_diff={'source','target','execution_tools_root','normal702_sha256','environment'}
    assert {k for k in inputs if inputs[k]!=parent_inputs[k]}==expected_diff
    environment_diff={k:{'parent':parent_inputs['environment'].get(k),'candidate':v} for k,v in inputs['environment'].items() if v!=parent_inputs['environment'].get(k)}
    assert set(environment_diff)=={'AXBUILD_TARGET_DIR','CARGO_TARGET_DIR','CARGO_HOME','VIRQ_CACHE_DIR','CCACHE_DIR'}
    save(OUT/'input-equivalence.json',{'changed_top_level':sorted(expected_diff),'environment_path_changes':environment_diff,'all_other_values_exact_equal':True,'cases_exact_equal':inputs['cases']==parent_inputs['cases'],'limits_exact_equal':inputs['limits']==parent_inputs['limits'],'normal702_field_compatibility':'same field name; binds new 702 manifest SHA','parent_normal702_sha256':parent_inputs['normal702_sha256'],'new_normal702_sha256':inputs['normal702_sha256']})
    references={
        'design/phase2-native-trace-capacity-v2-design.md':'5dbf286e5275dde7f8553de3785835b246f8df6ef7ad2b2e010bbe9357bb3ccd',
        'design/phase2-native-trace-capacity-v2-plan-v2.md':'54a43488604d56ea9bf02b5cdf06d1ab9b6d8bceb4248f91504c00e491534e27',
        'results/strict-native-trace-capacity-v2-design-plan-review-v2.json':'df19eac41e66bbb608ec7ee944bd55aac404ab6629de778ce997529848fae4fd',
        'results/strict-native-fit-capture-repair-spec-review-v1.json':'9eb529c4ed59975c59a282d3e76c6279f2eaf255dee0246f1431cddf6ff3d9e6',
        'results/strict-native-fit-capture-repair-quality-review-v1.json':'745cef5a7bfd243a0686abd1e27d11594d60554cef7ef867ac808f530c0084af',
        'results/strict-native-fit-capture-repair-root-acceptance-v1.json':'5245d7a61f00710a6e11bb7adf0fc3e9c64a0432aa4ccecfd71931207707a1dc'}
    reviewed=load(evidence/'reviewed-identities.json')
    for name,expected in references.items():
        p=R/name
        assert sha(p)==expected,name
        reviewed[str(p)]=ident(p)
        shutil.copy2(p,evidence/'authorities'/p.name)
    reviewed[str(CAPTURE)]=ident(CAPTURE)
    save(evidence/'reviewed-identities.json',reviewed)
    save(evidence/'capacity-v2-authority-provenance.json',{'new_exact_references':{str(R/k):v for k,v in references.items()},'capture':{'path':str(CAPTURE),'sha256':sha(CAPTURE)},'inherited_reviewed_manifest':ident(OLD/'evidence/reviewed-identities.json'),'inherited_versions':[ident(OLD/'evidence'/name) for name in ('inherited-tool-versions.json','inherited-root-tool-versions.json','inherited-toolchain-executables.json')],'scope':'inherited actual validation retained; new candidate requires independent Spec then Quality then Root copy check; no hardware approval'})
    save(evidence/'cache-provenance.json',{'source':str(OLD/'cache/vcpu-runtime-cache'),'private':str(tools/'cache/vcpu-runtime-cache'),'source_manifest':ident(OLD/'evidence/cache-identities.json'),'candidate_manifest':ident(evidence/'cache-identities.json'),'relocation_proof':ident(OUT/'cache-relocation.json'),'production_entry_proof':ident(OUT/'cache-production-entry-link.json'),'local_entry_probe_executed':True,'guest_build_executed':False,'downloads':False,'all_non_entry_metadata_members_equal_parent':True,'system_python_links_preserved':True,'historical_provenance':ident(evidence/'capacity-v2-parent-cache-provenance.json')})
    save(evidence/'cargo-cache-provenance.json',{'source':str(OLD/'cache/cargo'),'private':str(tools/'cache/cargo'),'source_manifest':ident(OLD/'evidence/cargo-cache-identities.json'),'candidate_manifest':ident(evidence/'cargo-cache-identities.json'),'immutable_bytes_modes_exact':True,'bookkeeping_before':ident(OUT/'cargo-bookkeeping.before.json'),'bookkeeping_after':ident(OUT/'cargo-bookkeeping.after.json'),'downloads':False,'added_config_or_credentials':False,'historical_provenance':ident(evidence/'capacity-v2-parent-cargo-cache-provenance.json')})
    save(evidence/'preparation.json',{'source':str(source),'tools':str(tools),'target':paths['target'],'parent_source':str(PARENT),'source_ordinary_files':len(ordinary),'source_702_count':702,'parent_changed_members':changed,'source_702_sha256':inputs['normal702_sha256'],'source_ordinary_manifest':ident(evidence/'ordinary-identities.json'),'source_controls':ident(evidence/'control-identities.json'),'hardware_started':0,'qemu_started':0,'fmt_wait':load(OUT/'cargo-fmt.receipt.json')['actual_Popen_wait'],'xtask_clippy_wait':load(OUT/'cargo-xtask-clippy.receipt.json')['actual_Popen_wait'],'scope':'new offline candidate; does not inherit a hardware approval'})
    proof_dir=evidence/'capacity-v2-validation'
    proof_dir.mkdir()
    for name in ('cache-relocation.json','cache-production-entry-link.json','host-python-identity.json','cache-python-probe.receipt.json','cache-cmake-direct.receipt.json','source-post-validation.json','cache-post-validation.json','input-equivalence.json','cargo-bookkeeping.before.json','cargo-bookkeeping.after.json','cargo-fmt.receipt.json','cargo-xtask-clippy.receipt.json'):
        shutil.copy2(OUT/name,proof_dir/name)
    with (evidence/'sources-702.tar.gz').open('wb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as gz:
            with tarfile.open(fileobj=gz,mode='w') as tar:
                for rel in sorted(new_normal):
                    p=source/rel; info=tar.gettarinfo(str(p),arcname=rel)
                    info.uid=info.gid=0; info.uname=info.gname=''; info.mtime=0
                    with p.open('rb') as data:
                        tar.addfile(info,data)
    with tarfile.open(evidence/'sources-702.tar.gz','r:gz') as tar:
        members=tar.getmembers()
        assert len(members)==702 and {m.name for m in members}==set(new_normal)
        for m in members:
            assert m.isfile() and m.mode==ordinary[m.name]['mode']
            assert hashlib.sha256(tar.extractfile(m).read()).hexdigest()==new_normal[m.name]
    save(evidence/'ccache-identities.json',inventory(tools/'cache/ccache'))
    # Freeze does not contain itself or the caches: their complete immutable manifests are frozen instead.
    frozen=inventory(tools)
    frozen={k:v for k,v in frozen.items() if not k.startswith('cache/')}
    assert not any(k.endswith('.once') or '__pycache__' in k for k in frozen)
    save(tools/'freeze-manifest.json',frozen)
    archive=OUT/'frozen-tools'
    shutil.copytree(tools,archive,ignore=shutil.ignore_patterns('cache'))
    for name in ('source-post-validation.json','input-equivalence.json','cache-relocation.json','cache-post-validation.json','cargo-bookkeeping.before.json','cargo-bookkeeping.after.json'):
        assert (OUT/name).exists()
    save(OUT/'candidate-identities.json',{'paths':paths,'freeze_manifest':ident(tools/'freeze-manifest.json'),'inputs':ident(tools/'inputs.json'),'normal702':ident(evidence/'sources-702.json'),'normal702_tar':ident(evidence/'sources-702.tar.gz'),'ordinary':ident(evidence/'ordinary-identities.json'),'cargo_cache':ident(evidence/'cargo-cache-identities.json'),'virq_cache':ident(evidence/'cache-identities.json'),'control':ident(evidence/'control-identities.json'),'capture':ident(tools/'capture_native.py'),'controller':ident(tools/'native_once.py'),'frozen_tool_members':len(frozen),'tools_archive_without_cache':str(archive),'source_ordinary_files':len(ordinary),'parent_changed_members':changed,'new_candidate_frozen':True})
    print('FROZEN',sha(tools/'freeze-manifest.json'),'source702',inputs['normal702_sha256'],flush=True)


if __name__=='__main__':
    {'prepare':prepare,'relocate':relocate,'rust-checks':rust_checks,'freeze':freeze}[sys.argv[1]]()
