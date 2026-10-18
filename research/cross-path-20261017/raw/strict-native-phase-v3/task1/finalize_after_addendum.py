#!/usr/bin/env python3
"""Freeze only after actual preparation, a restored real-directory RED, and exact inputs."""
import ast
import difflib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import time

sys.dont_write_bytecode=True
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(OUT))
import prepare as h


def metadata(root):
    rows={}
    for directory,children,files in os.walk(root,followlinks=False):
        for path in [Path(directory),*[Path(directory)/n for n in children+files]]:
            s=path.lstat(); rel=str(path.relative_to(root))
            rows[rel]={'mode':s.st_mode,'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'inode':s.st_ino}
    return dict(sorted(rows.items()))


def command(name,argv,cwd,env,expected=0):
    start=time.time_ns()
    with (OUT/(name+'.stdout')).open('wb') as stdout,(OUT/(name+'.stderr')).open('wb') as stderr:
        child=subprocess.Popen(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
        code=child.wait()
    receipt={'argv':argv,'cwd':str(cwd),'environment':env,'pid':child.pid,'actual_Popen_wait':code,
             'start_unix_ns':start,'end_unix_ns':time.time_ns(),'stdout':h.ident(OUT/(name+'.stdout')),'stderr':h.ident(OUT/(name+'.stderr'))}
    h.save(OUT/(name+'.receipt.json'),receipt)
    print(name,'actual_wait=',code,flush=True)
    assert code==expected,(name,code)
    return receipt


def verify_parent_metadata():
    before=h.load(OUT/'parent-source-stamps.before.json')
    assert all(h.stamp(h.PARENT/k)==v for k,v in before.items()),'parent ordinary tree metadata changed'
    before=h.load(OUT/'parent-cache-stamps.before.json')
    for sub,stamps in before.items():
        root=h.OLD/'cache'/sub
        assert all(h.stamp(root/k)==v for k,v in stamps.items()),('parent cache metadata changed',sub)
        actual=set()
        for directory,children,files in os.walk(root,followlinks=False):
            actual.add(str(Path(directory).relative_to(root)))
            actual.update(str((Path(directory)/name).relative_to(root)) for name in children+files)
        assert actual==set(stamps),('parent cache membership changed',sub)
    h.save(OUT/'parent-metadata-protection.after.json',{'ordinary_all_lstat_fields_unchanged':True,'cargo_and_virq_all_lstat_fields_and_members_unchanged':True,
           'fields':['inode','bytes','mtime_ns','ctime_ns','mode'],'initial_all_immutable_SHA_verified':True,'extra_full_parent_hash_scan_performed':False})


def finalize():
    p=h.paths(); source=p['source']; tools=p['tools']; target=p['target']; evidence=tools/'evidence'
    authorization=h.load(OUT/'generated-cache-authorization.json')
    for reference in authorization['references']:
        assert h.sha(h.R/reference['path'])==reference['sha256'],reference['path']
    delta=h.load(OUT/'post-prepare-unexpected-zephyr-cache.json')
    accepted_generated={**delta['added'],**{k:v['actual'] for k,v in delta['changed_existing'].items()}}
    assert len(delta['added'])==45 and set(delta['changed_existing'])=={'zephyr/.cache/ToolchainCapabilityDatabase/log.txt'}
    assert h.load(OUT/'host-prepare.receipt.json')['actual_Popen_wait']==0
    assert not (tools/'freeze-manifest.json').exists()
    ordinary=h.load(h.OLD/'evidence/ordinary-identities.json'); normal=h.load(h.OLD/'evidence/sources-702.json')
    source_proof=h.load(OUT/'source-post-validation.json')
    assert source_proof['all_source_bytes_modes_equal_parent'] and source_proof['ordinary_files']==9642
    assert source_proof['source702_count']==702
    assert h.sha(evidence/'ordinary-identities.json')==h.ORDINARY_SHA and h.sha(evidence/'sources-702.json')==h.NORMAL_SHA
    # The completed source/Cargo post-prepare proofs are retained. Neither tree was
    # written since; final actual readiness below freshly checks their full bytes.
    relocation=h.load(OUT/'cache-relocation.json'); allowed={x['path']:x['new'] for x in relocation['changes']}
    directory_groups={}; cache_report={}
    parent_dirs=h.load(OUT/'parent-cache-stamps.before.json')
    for manifest,sub in [('cache-identities.json','vcpu-runtime-cache'),('cargo-cache-identities.json','cargo')]:
        root=tools/'cache'/sub; expected=h.load(h.OLD/'evidence'/manifest)
        if sub=='vcpu-runtime-cache':
            actual,directories,cache_stamps=h.inventory(root)
            h.save(OUT/'final-virq-cache-identities.observed.json',actual)
        else:
            post=h.load(OUT/'cargo-post-validation.json')
            assert post['all_immutable_exact_parent'] and post['immutable_members']==len(expected)
            runtime_snapshot={k:h.ident(root/k) for k in post['runtime']}
            assert runtime_snapshot==post['runtime']
            actual={**expected,**runtime_snapshot}
            directories={str(Path(d).relative_to(root)):stat.S_IMODE(Path(d).lstat().st_mode)
                         for d,children,files in os.walk(root,followlinks=False)}
        runtime=h.load(tools/'inputs.json')['cache_policy']['cargo_runtime_files'] if sub=='cargo' else {}
        approved={**expected,**allowed,**accepted_generated} if sub=='vcpu-runtime-cache' else expected
        h.assert_members(actual,approved,runtime)
        changed=[name for name in expected if actual[name]!=expected[name]]
        if sub=='vcpu-runtime-cache':
            assert set(changed)==set(allowed)|set(delta['changed_existing'])
            assert set(actual)-set(expected)==set(delta['added'])
        else:
            assert not changed
        for rel in h.GIT_DIRS if sub=='vcpu-runtime-cache' else []:
            assert directories['zephyr/.git/'+rel]==0o775
        old_directory_names={k for k,v in parent_dirs[sub].items() if stat.S_ISDIR(v[4])}
        added=set(directories)-old_directory_names
        expected_added={'zephyr/.git/'+k for k in h.GIT_DIRS} if sub=='vcpu-runtime-cache' else set()
        assert added==expected_added,(sub,sorted(added))
        assert old_directory_names<=set(directories)
        for name in old_directory_names:
            assert directories[name]==stat.S_IMODE(parent_dirs[sub][name][4]),(sub,name)
        immutable={k:actual[k] for k in approved}
        h.save(evidence/manifest,immutable)
        state={k:v for k,v in actual.items() if k not in expected} if sub=='cargo' else {}
        if sub=='cargo':
            assert h.load(OUT/'cargo-bookkeeping.after.json')==state
            for name,row in state.items():
                assert row.get('type')!='symlink' and row['bytes']<=runtime[name]
        directory_groups[manifest]={'root':str(root),'directories':directories}
        cache_report[sub]={'immutable_members':len(approved),'parent_immutable_members':len(expected),'directory_count':len(directories),'added_directories':sorted(added),
             'changed_immutable_members':changed,'new_generated_immutable_files':sorted(set(actual)-set(expected)) if sub=='vcpu-runtime-cache' else [],'runtime':state,
             'files_bytes':sum(v.get('bytes',0) for v in actual.values()),'manifest':h.ident(evidence/manifest)}
    h.save(evidence/'cache-directory-identities.json',directory_groups)
    h.save(OUT/'cache-post-validation.json',cache_report)
    print('retained complete source/Cargo proofs and final VIRQ recheck with exact accepted generated delta verified',flush=True)
    # Use the real parser against the actual produced archive and approved binary/init oracle.
    sys.path.insert(0,str(tools))
    import capture_native as c
    rootfs=h.load(OUT/'actual-rootfs-verification.json')
    assert c.digest(target/'axbuild/axvm/vcpu-runtime/linux/initramfs.cpio.gz')==rootfs['archive_sha256']
    assert rootfs['members']['init']['bytes']==390 and rootfs['members']['bin/ordinary-load']['sha256']==c.WORKER_SHA
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
    directory_identity_before=h.ident(evidence/'cache-directory-identities.json')
    refs=tools/'cache/vcpu-runtime-cache/zephyr/.git/refs'
    saved_modes={str((refs/x).relative_to(refs)):stat.S_IMODE((refs/x).lstat().st_mode) for x in ['.','heads','tags']}
    removed=False
    try:
        for name in ['heads','tags']:
            (refs/name).rmdir()
        refs.rmdir(); removed=True
        command('directory-missing-refs-negative',['python3','-B',str(OUT/'audited_entry.py')],source,env,expected=2)
        message=(OUT/'directory-missing-refs-negative.stdout').read_text()
        assert 'private cache directory identity differs: cache-identities.json' in message and 'zephyr/.git/refs' in message,message
        assert 'freeze' not in message and not (tools/'freeze-manifest.json').exists()
    finally:
        if removed:
            refs.mkdir(mode=saved_modes['.']); refs.chmod(saved_modes['.'])
            for name in ['heads','tags']:
                (refs/name).mkdir(mode=saved_modes[name]); (refs/name).chmod(saved_modes[name])
        else:
            # Preserve all evidence if a directory operation unexpectedly failed.
            raise RuntimeError('negative setup incomplete; candidate not frozen')
    restored={}
    for manifest,group in directory_groups.items():
        root=Path(group['root']); d={}
        for directory,children,files in os.walk(root,followlinks=False):
            d[str(Path(directory).relative_to(root))]=stat.S_IMODE(Path(directory).lstat().st_mode)
        assert d==group['directories'],manifest
        restored[manifest]={'all_directories_and_modes_restored':True,'directory_count':len(d)}
    assert h.ident(evidence/'cache-directory-identities.json')==directory_identity_before
    h.save(OUT/'directory-negative-restoration.json',{'real_candidate_cache_used':True,'before_final_freeze':True,'new_directory_gate_rejected':True,
          'file_mutations_performed':False,'directory_manifest':directory_identity_before,'saved_modes':saved_modes,'groups':restored})
    verify_parent_metadata()
    assert h.protected()==h.load(OUT/'protected.before.json')
    assert h.load(OUT/'protected.after.json')==h.protected()
    parent_inputs=h.load(h.OLD/'inputs.json'); inputs=h.load(tools/'inputs.json')
    changed_top={k for k in inputs if inputs[k]!=parent_inputs[k]}
    assert changed_top=={'source','target','execution_tools_root','environment'}
    changed_env={k for k in inputs['environment'] if inputs['environment'][k]!=parent_inputs['environment'][k]}
    assert changed_env=={'AXBUILD_TARGET_DIR','CARGO_TARGET_DIR','CARGO_HOME','VIRQ_CACHE_DIR','CCACHE_DIR'}
    input_proof=h.load(OUT/'input-equivalence.json')
    assert set(input_proof['changed_top_level'])==changed_top and set(input_proof['changed_environment_paths'])==changed_env
    inherited=h.load(OUT/'inherited-rust-validation.json')
    assert inherited['rerun_in_v3'] is False and inherited['fmt']['actual_v2_wait']==0
    assert inherited['xtask_clippy']['actual_v2_wait']==0 and inherited['xtask_clippy']['passed']==29
    # Bind the new authority and preserve inherited historical manifests separately.
    for name in ['inputs.json','freeze-manifest.json']:
        shutil.copy2(h.OLD/name,evidence/('cache-v3-parent-'+name))
    for name in ['cache-identities.json','cargo-cache-identities.json','cache-provenance.json','cargo-cache-provenance.json','preparation.json']:
        shutil.copy2(h.OLD/'evidence'/name,evidence/('cache-v3-parent-'+name))
    reviewed=h.load(evidence/'reviewed-identities.json')
    for rel in ['design/phase2-native-cache-topology-v3-plan.md','results/strict-native-cache-v3-design-plan-review-v1.json',*[ref['path'] for ref in authorization['references']]]:
        path=h.R/rel; reviewed[str(path)]=h.ident(path)
        shutil.copy2(path,evidence/'authorities'/path.name)
    h.save(evidence/'reviewed-identities.json',reviewed)
    h.save(evidence/'cache-provenance.json',{'source':str(h.OLD/'cache/vcpu-runtime-cache'),'private':str(tools/'cache/vcpu-runtime-cache'),
          'parent_manifest':h.ident(h.OLD/'evidence/cache-identities.json'),'candidate_manifest':h.ident(evidence/'cache-identities.json'),
          'directories_manifest':h.ident(evidence/'cache-directory-identities.json'),'changed_files':sorted(allowed),'restored_empty_git_directories':h.GIT_DIRS,'accepted_generated_cache':accepted_generated,'generated_cache_authorization':authorization,
          'copy_method':'shutil.copytree(symlinks=True), directory mode copystat; verified allowed members only','downloads':False,'host_prepare_actual_wait':0})
    h.save(evidence/'cargo-cache-provenance.json',{'source':str(h.OLD/'cache/cargo'),'private':str(tools/'cache/cargo'),'all_immutable_equal_parent':True,
          'parent_runtime_at_copy':h.ident(OUT/'cargo-bookkeeping.before.json'),'candidate_runtime_after_prepare':h.ident(OUT/'cargo-bookkeeping.after.json'),
          'runtime_not_immutable':True,'downloads':False,'new_credentials_or_config':False})
    h.save(evidence/'preparation.json',{'source':str(source),'tools':str(tools),'target':str(target),'parent_source':str(h.PARENT),'parent_tools':str(h.OLD),
          'ordinary_count':9642,'source702_count':702,'ordinary_manifest_sha256':h.ORDINARY_SHA,'source702_manifest_sha256':h.NORMAL_SHA,
          'hardware_started':0,'qemu_started':0,'host_prepare_executed_once':True,'host_prepare_wait':0,'normal_host_validation':False,
          'capacity_zero_loss_proven':False,'M2':False,'Joint':False,'goal_complete':False,'hardware_authorized':False,'rust_validation_rerun':False})
    validation=evidence/'cache-v3-validation'; validation.mkdir()
    for name in ['cache-relocation.json','cache-production-entry-link.json','cache-python-probe.receipt.json','cache-cmake-direct.receipt.json','zephyr-git-revparse.receipt.json','zephyr-git-status.receipt.json',
                 'host-prepare.receipt.json','host-prepare-preconditions.json','host-prepare-artifacts.json','actual-rootfs-verification.json','source-post-validation.json','cache-post-validation.json',
                 'input-equivalence.json','inherited-rust-validation.json','generated-cache-authorization.json','zephyr-capability-cache-cause.json','post-prepare-unexpected-zephyr-cache.json','finalize.first-error.json','finalize.launch.json','cargo-bookkeeping.before.json','cargo-bookkeeping.after.json','directory-missing-refs-negative.receipt.json','directory-negative-restoration.json','capture-scope.json']:
        shutil.copy2(OUT/name,validation/name)
    # The unchanged source tar is inherited byte-for-byte and its actual member payloads are checked.
    with tarfile.open(evidence/'sources-702.tar.gz','r:gz') as tar:
        members=tar.getmembers(); assert len(members)==702 and {m.name for m in members}==set(normal)
        for member in members:
            assert member.isfile() and member.mode==ordinary[member.name]['mode']
            assert __import__('hashlib').sha256(tar.extractfile(member).read()).hexdigest()==normal[member.name]
    assert h.load(OUT/'target.after-prepare.metadata.json')==metadata(target)
    frozen,dirs,stamps=h.inventory(tools,exclude_cache=True)
    assert not any(n.endswith('.once') or '__pycache__' in n for n in frozen)
    h.save(tools/'freeze-manifest.json',frozen)
    shutil.copytree(tools,OUT/'frozen-tools',ignore=shutil.ignore_patterns('cache'),symlinks=True)
    h.save(OUT/'candidate-identities.json',{'paths':h.load(OUT/'paths.json'),'freeze_manifest':h.ident(tools/'freeze-manifest.json'),'inputs':h.ident(tools/'inputs.json'),
          'ordinary':h.ident(evidence/'ordinary-identities.json'),'normal702':h.ident(evidence/'sources-702.json'),'sources702_tar':h.ident(evidence/'sources-702.tar.gz'),
          'directory_manifest':h.ident(evidence/'cache-directory-identities.json'),'virq_cache':h.ident(evidence/'cache-identities.json'),'cargo_cache':h.ident(evidence/'cargo-cache-identities.json'),
          'capture':h.ident(tools/'capture_native.py'),'controller':h.ident(tools/'native_once.py'),'frozen_members':len(frozen),'parent_freeze_sha256':h.sha(h.OLD/'freeze-manifest.json')})
    before=metadata(target)
    command('candidate-check-ready',['python3','-B',str(tools/'native_once.py'),'--check-ready','--source-manifest-sha',h.NORMAL_SHA],source,env)
    assert before==metadata(target),'readiness mutated target'
    assert not any((tools/(name+'.once')).exists() for name in ['AB1','AB0','0'])
    ready=(OUT/'candidate-check-ready.stdout').read_text()
    assert ready.startswith('STRICT_NATIVE_READY ')
    h.save(OUT/'candidate-ready-state.json',{'actual_wait':0,'ready':json.loads(ready.split(' ',1)[1]),'no_markers':True,'target_metadata_unchanged':True,
           'normal_host_validation':False,'capacity_zero_loss_proven':False,'hardware_authorized':False})
    print('FROZEN',h.sha(tools/'freeze-manifest.json'),'actual ready0; no hardware/QEMU',flush=True)


if __name__=='__main__':
    try:
        finalize()
    except BaseException as error:
        h.save(OUT/'finalize-after-addendum.first-error.json',{'type':type(error).__name__,'message':str(error),'time_ns':time.time_ns(),'stop':True})
        raise
