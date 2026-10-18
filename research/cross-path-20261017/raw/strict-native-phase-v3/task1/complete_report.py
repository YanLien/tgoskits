#!/usr/bin/env python3
"""Archive and report the exact offline-ready candidate, keeping all earlier refusals."""
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import stat
import sys
import tarfile

sys.dont_write_bytecode=True
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(OUT))
import prepare as h

p=h.paths(); tools=p['tools']; evidence=tools/'evidence'
ready=h.load(OUT/'candidate-ready-state.json')
assert ready['actual_wait']==0 and ready['target_metadata_unchanged'] and ready['no_markers']
assert h.load(OUT/'finalize-after-addendum.launch.json')['actual_Popen_wait']==0
assert h.load(OUT/'host-prepare.receipt.json')['actual_Popen_wait']==0
assert not any((tools/(case+'.once')).exists() for case in ['AB1','AB0','0'])
frozen=h.load(tools/'freeze-manifest.json'); archive_root=OUT/'frozen-tools'
archive=OUT/'frozen-tools.tar.gz'
assert not archive.exists()
# The archive contains tools/evidence only; the separately recorded caches and target stay local.
expected={**frozen,'freeze-manifest.json':h.ident(tools/'freeze-manifest.json')}
with archive.open('wb') as raw:
    with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as zipped:
        with tarfile.open(fileobj=zipped,mode='w') as tar:
            for name in sorted(expected):
                path=archive_root/name
                info=tar.gettarinfo(str(path),arcname=name)
                assert info.isfile() and stat.S_IMODE(info.mode)==expected[name]['mode'] and info.size==expected[name]['bytes']
                info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
                with path.open('rb') as stream:
                    tar.addfile(info,stream)
with tarfile.open(archive,'r:gz') as tar:
    members=tar.getmembers()
    assert {m.name for m in members}==set(expected) and len(members)==len(expected)
    for member in members:
        assert member.isfile() and member.mode==expected[member.name]['mode']
        assert hashlib.sha256(tar.extractfile(member).read()).hexdigest()==expected[member.name]['sha256']
archive_receipt={'path':str(archive),'identity':h.ident(archive),'member_count':len(expected),'all_payload_SHA_mode_size_match_frozen_tools':True,
                 'cache_included':False,'target_included':False,'sources702_tar':h.ident(evidence/'sources-702.tar.gz')}
h.save(OUT/'tools-archive-verification.json',archive_receipt)
production=h.load(OUT/'host-prepare.receipt.json'); identities=h.load(OUT/'candidate-identities.json')
authorization=h.load(OUT/'generated-cache-authorization.json'); cache=h.load(OUT/'cache-post-validation.json')
unexpected=h.load(OUT/'post-prepare-unexpected-zephyr-cache.json'); cause=h.load(OUT/'zephyr-capability-cache-cause.json')
assert cache['vcpu-runtime-cache']['immutable_members']==54064
assert cache['vcpu-runtime-cache']['runtime']=={}
assert len(cache['vcpu-runtime-cache']['new_generated_immutable_files'])==45
assert len(cache['vcpu-runtime-cache']['changed_immutable_members'])==14
directory=h.load(evidence/'cache-directory-identities.json')
directory_counts={name:len(group['directories']) for name,group in directory.items()}
assert all('.' in group['directories'] for group in directory.values())
assert h.load(OUT/'directory-missing-refs-negative.receipt.json')['actual_Popen_wait']==2
assert h.load(OUT/'protected.before.json')==h.load(OUT/'protected.after.json')
inputs=h.load(tools/'inputs.json');parent_inputs=h.load(h.OLD/'inputs.json')
assert inputs['cache_policy']==parent_inputs['cache_policy']
space=h.load(OUT/'space.after-prepare.json')
space['archive_raw_bytes_after_tool_archive']=sum(path.stat().st_size for path in OUT.rglob('*') if path.is_file())
space['virq_cache_regular_file_bytes']=cache['vcpu-runtime-cache']['files_bytes']
space['cargo_cache_regular_file_bytes']=cache['cargo']['files_bytes']
assert space['archive_raw_bytes_after_tool_archive']<1073741824
evidence_names=['paths.json','prepare.initial-failed-launch.json','prepare.initial-failed-log-provenance.json','prepare.first-error.json','prepare.initial-failed.py',
 'prepare.initial-failed.stdout','prepare.initial-failed.stderr','source-partial-before-resume.json','prepare-assertion-correction.patch','prepare-resume.launch.json',
 'host-prepare-helper.precondition-failed.launch.json','host-prepare-helper.precondition-failed.stdout','host-prepare-helper.precondition-failed.stderr',
 'host-prepare.external-precondition-first-error.json','prepare.external-precondition-failed.py','prepare-external-precondition-correction.patch',
 'host-prepare-helper.launch.json','relocate.launch.json','cache-relocation.json','cache-relocation.patch','cache-production-entry-link.json','host-python-identity.json',
 'cache-python-probe.receipt.json','cache-cmake-direct.receipt.json','zephyr-git-revparse.receipt.json','zephyr-git-status.receipt.json','restored-git-directories.json',
 'host-prepare-preconditions.json','host-prepare.receipt.json','host-prepare.stdout','host-prepare.stderr','host-prepare-artifacts.json','actual-rootfs-verification.json',
 'source-post-validation.json','cargo-post-validation.json','cache-post-validation.json','cargo-bookkeeping.before.json','cargo-bookkeeping.after.json',
 'post-prepare-unexpected-zephyr-cache.json','zephyr-capability-cache-cause.json','finalize.first-error.json','finalize.launch.json','finalize.stdout','finalize.stderr',
 'generated-cache-authorization.json','finalize-generated-cache-addendum.patch','finalize-after-addendum.launch.json','finalize-after-addendum.stdout','finalize-after-addendum.stderr',
 'directory-missing-refs-negative.receipt.json','directory-missing-refs-negative.stdout','directory-missing-refs-negative.stderr','directory-negative-restoration.json',
 'candidate-identities.json','candidate-check-ready.receipt.json','candidate-check-ready.stdout','candidate-check-ready.stderr','candidate-ready-state.json',
 'candidate-stopped-state.json','capture_native.py.patch','native_once.py.patch','capture-scope.json','input-equivalence.json','inherited-rust-validation.json',
 'protected.before.json','protected.after.json','parent-metadata-protection.after.json','target.after-prepare.metadata.json','actual-zephyr-cmake-build-identity.json',
 'space.after-prepare.json','tools-archive-verification.json','complete_report.archive-metadata-failed.py','complete-report.archive-metadata-failed.launch.json','complete-report.archive-metadata-failed.stdout','complete-report.archive-metadata-failed.stderr','frozen-tools.archive-metadata-failed.tar.gz','complete-report-archive-mode-correction.patch','prepare.py','finalize.py','finalize_after_addendum.py','patch_capture.py','audited_entry.py','complete_report.py']
evidence_index={str((OUT/name).relative_to(h.R)):h.ident(OUT/name) for name in evidence_names}
for reference in authorization['references']:
    assert h.sha(h.R/reference['path'])==reference['sha256']
report={
 'schema_version':1,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'candidate':'strict-native-cache-v3',
 'state':'OFFLINE_READY_PENDING_SPEC_QUALITY_ROOTCOPY','offline_implementation_complete':True,'Task1_independently_accepted':False,
 'next_gate':'independent Spec, then Quality, then Root exact tools-copy acceptance; no hardware by this report',
 'paths':h.load(OUT/'paths.json'),'candidate_identities':identities,'tool_archive':archive_receipt,
 'parent':{'source':str(h.PARENT),'tools':str(h.OLD),'freeze_manifest_sha256':h.sha(h.OLD/'freeze-manifest.json'),
           'ordinary_manifest_sha256':h.ORDINARY_SHA,'source702_manifest_sha256':h.NORMAL_SHA},
 'authority':{'original_plan':{'path':'design/phase2-native-cache-topology-v3-plan.md','identity':h.ident(h.R/'design/phase2-native-cache-topology-v3-plan.md')},
              'original_design_review':{'path':'results/strict-native-cache-v3-design-plan-review-v1.json','identity':h.ident(h.R/'results/strict-native-cache-v3-design-plan-review-v1.json')},
              'generated_cache_exact_authorization':authorization},
 'source':h.load(OUT/'source-post-validation.json'),'input_equivalence':h.load(OUT/'input-equivalence.json'),
 'copy_and_entry':{'cache_copy':'shutil.copytree(symlinks=True) retains actual directories and modes; only approved inputs',
  'new_git_directories':h.load(OUT/'restored-git-directories.json'),'venv_exact_relocated_count':13,'all_other_venv_vendor_toolchain_bytes_same_except_explicit_generated_cache':True,
  'python_probe_wait':0,'cmake_direct_wait':0,'git_revparse_wait':0,'git_revision':'32229d0b6cc60a1906307311b8e79ec483ad1e88','git_status_wait':0,'git_status_empty':True,
  'actual_entry_proof':h.load(OUT/'cache-production-entry-link.json')},
 'production_host_prepare':{'executions':1,'actual_Popen_wait':0,'elapsed_seconds':production['elapsed_seconds'],'budget_seconds':300,
  'argv':production['argv'],'cwd':production['cwd'],'environment':production['environment'],'start_new_session':True,
  'owned_record_at_spawn':production['owned_record_at_spawn'],'environment_extra_ownership_marker':'STRICT_NATIVE_RUN_TOKEN follows original controller convention',
  'proc_scope':'only exact owned child PID identity; no host process scan','timeout':False,'cleanup_invoked':False,'signals':[],
  'downloads':False,'actual_artifacts':h.load(OUT/'host-prepare-artifacts.json'),'actual_rootfs':h.load(OUT/'actual-rootfs-verification.json'),
  'known_worker_sha256':'b9db9b8fc7925bf2c18e2d9edfbd3c0ee10a5a0f57985151e2f7b0073122ffc2','init_bytes':390,
  'fixed_kernel_and_base_paths_SHA_unchanged':True,'artifact_scope':'preparation resources only; no Host/Guest boot or Trace'},
 'generated_cache':{'first_finalization_actual_wait':1,'first_refusal_preserved':True,'accepted_only_before_final_freeze':True,
  'added_files':45,'added_file_bytes':45,'changed_existing_log':list(unexpected['changed_existing']),'appended_log_bytes':cause['appended_bytes'],
  'appended_log_lines':45,'new_log_sha256':cause['new_log']['sha256'],'all_added_keys_values_MD5_names_and_log_prefix_exact':True,
  'final_immutable_members':cache['vcpu-runtime-cache']['immutable_members'],'all_other_VIRQ_immutable_members_exact_parent':True,
  'Cargo_immutable_members':cache['cargo']['immutable_members'],'all_Cargo_immutable_exact_parent':True,
  'runtime_policy_exact_parent':True,'new_runtime_exceptions':False,'future_cache_changes_rejected':True,'final_cache_report':cache},
 'directory_gate':{'manifest':identities['directory_manifest'],'group_directory_counts':directory_counts,'root_relative_path':'.',
  'all_non_symlink_directory_paths_and_modes_exact':True,'integrated_in_original_os_walk':True,'before_cache_file_hashes':True,
  'actual_negative_wait':2,'actual_negative_error':(OUT/'directory-missing-refs-negative.stdout').read_text(),
  'negative_used_actual_staging_cache_before_final_freeze':True,'negative_moved_only_empty_refs_hierarchy':True,
  'all_directory_modes_restored':True,'frozen_execution_root_mutated_for_negative':False,'actual_ready_wait':0},
 'tools':{'capture_scope':h.load(OUT/'capture-scope.json'),'capture_parent_sha256':h.CAPTURE_SHA,
          'controller_change':'only output root raw/strict-native-phase-v2 -> raw/strict-native-phase-v3','all_other_capture_bytes_exact':True,
          'old_file_symlink_primary96_quota_loss_full_FIT_newc_ownership_wait_rules_retained':True},
 'actual_ready':{'receipt':h.ident(OUT/'candidate-check-ready.receipt.json'),'actual_Popen_wait':0,'ready':ready['ready'],
  'target_metadata_before_after_unchanged':True,'case_markers_absent':True,'only_required_primary96_ready_gate_run':True,'additional_primary96_scan':False},
 'inherited_rust_validation':h.load(OUT/'inherited-rust-validation.json'),
 'local_helper_precondition_errors':[{'kind':'overbroad ordinary path exclusion','initial_actual_exec_exit':1,'direct_Popen_wait_not_separately_recorded':True,
    'production_prepare_started':False,'snapshot':'prepare.initial-failed.py','correction_patch':'prepare-assertion-correction.patch','resume_actual_Popen_wait':0},
   {'kind':'fixed compiler alias compared using cache symlink identity instead of original external follow-stat semantics','actual_helper_Popen_wait':1,
    'production_prepare_started':False,'snapshot':'prepare.external-precondition-failed.py','correction_patch':'prepare-external-precondition-correction.patch'},
   {'kind':'unserialized TarInfo.mode includes regular-file type bits; compare permission field with stat.S_IMODE',
    'actual_archive_helper_Popen_wait':1,'frozen_candidate_mutated':False,'snapshot':'complete_report.archive-metadata-failed.py',
    'correction_patch':'complete-report-archive-mode-correction.patch','failed_partial_tar_preserved':True}],
 'protection':{'selected_parent_tools_manifests_and_failed_records_SHA_unchanged':True,'parent_source_and_cache_all_lstat_fields_and_members_unchanged':True,
  'parent_all_cache_immutable_SHA_verified_before_copy':True,'old_cache_or_failed_candidate_modified':False,'main_source_modified':False,
  'source702_ordinary_Rust_protocol_budget_pressure_variables_unchanged':True,'target_after_ready_matches_actual_prepare_snapshot':True},
 'space':space,'hardware_started':0,'qemu_started':0,'formal_case_quota_consumed':False,'hardware_authorized':False,
 'normal_Host_validation':False,'capacity_zero_loss_proven':False,'M2':False,'Joint':False,'goal_complete':False,
 'Spec_review_complete':False,'Quality_review_complete':False,'Root_copy_acceptance_complete':False,'evidence':evidence_index}
h.save(h.R/'results/strict-native-cache-v3-task1.json',report)
md='''# 严格原生缓存 v3 离线准备

## 1. 准备结果

本次候选完成离线实施和实际 ready，状态为 `OFFLINE_READY_PENDING_SPEC_QUALITY_ROOTCOPY`，待独立 Spec→Quality 和 Root 工具副本验收。完整身份与收据见 [JSON 报告](strict-native-cache-v3-task1.json)。未启动板卡或 QEMU，未消耗正式案例额度。

### 1.1 输入与入口

普通源为 `{source}`，工具为 `{tools}`，target 为 `{target}`。全部 9642 普通文件与 702 源保持父容量 v2 字节和模式；普通清单 SHA 为 `{ordinary}`，702 清单 SHA 为 `{normal}`。缓存使用 `shutil.copytree(symlinks=True)` 保存目录语义，仅在新副本补齐五个模式 0775 的已观察空 Git 目录，并重定位原批准的 13 项 venv 入口及 metadata。

新 Python prefix、CMake 模块和实际 binary 均归新缓存，直接 CMake、真实 Git 固定 HEAD 和 clean status 均实际 wait 0。准确生产命令 `python3 virtualization/axvm/tests/guests/virq/prepare.py --linux-peer` 只运行一次，同一父 `Popen.wait` 为 0，耗时 {elapsed:.3f} 秒，预算仍为 300 秒。环境沿用父白名单和 AB1，仅替换五项路径，另有原控制器同式 `STRICT_NATIVE_RUN_TOKEN` 所有权标记。只读取准确自持子 PID 身份，未扫描宿主进程，也未触发 timeout、cleanup 或信号。

### 1.2 实际产物

真实 Zephyr ELF、BIN、DTB、Linux worker、rootfs、build.json 与资源配置已保存身份。`capture_native.verify_rootfs()` 对实际 rootfs 验证通过，init 为 390 字节，worker SHA 保持 `b9db9b8fc7925bf2c18e2d9edfbd3c0ee10a5a0f57985151e2f7b0073122ffc2`，固定 kernel/base 路径与 SHA 不变。v2 的 fmt wait 0 与项目 Clippy 29/29 收据仅因普通源全同而继承，明确未在 v3 重跑。

## 2. 冻结与边界

最终 freeze SHA 为 `{freeze}`。工具归档仅含冻结工具与 evidence，未包含 cache/target；归档 SHA 为 `{tar_sha}`。原始材料目录总文件字节为 {raw_bytes}，小于 1 GiB，临时 cache 和 target 容量在 JSON 单列。

### 2.1 生成缓存与目录门

第一次 finalizer 真实 wait 1 和首错保持原样：生产准备新增了 45 个单字节能力结果，并向既有 `ToolchainCapabilityDatabase/log.txt` 追加 27,058 字节、45 行。Root 精核和独立 PASS 的[精确补充](../design/phase2-native-cache-topology-v3-generated-cache-addendum-v1.md)已绑定最终材料；最终只接纳这 45 项、准确 log 新身份和原 13 项入口重定位，所有其他 VIRQ 不可变文件与父相同，Cargo 不可变文件全同。生成缓存已进入不可变清单，没有新增 runtime 例外。

新 `verify_static()` 在原 `os.walk` 收集两组全部非 symlink 目录、根 `.` 和 mode，并在大文件 hash 前核集合、类型与模式。冻结前对实际暂存 cache 移除空 refs 层级，真实入口实际 wait 2，明确因目录身份门拒绝；随后完整恢复目录与模式。最终冻结后，真实 `native_once.py --check-ready` 实际 wait 0，target metadata 不变且无 `.once`。capture 仅该函数变化，其余所有字节与批准父版本相同；controller 仅换输出根。

### 2.2 证据范围

父 source/cache 的完整 lstat 身份和成员集合、所选父工具/manifest/旧失败材料的前后 SHA 保持一致；没有修改主源码、旧候选或论文封存。两个本地 helper 前置错误已分别保留准确快照、首错和纠错 diff；它们发生在首次生产 prepare Popen 之前，不计作生产准备失败或重试。后续工具归档 helper 曾将含文件类型位的原始 TarInfo.mode 直接与权限字段比较并退出 1；失败部分 tar 与收据保留，修正为 stat.S_IMODE 后对实际序列化 tar 再核完整 mode/size/SHA，未触碰冻结候选。首次冻结拒绝与后续精确补充接纳分列，历史收据不回填。

本报告只接纳离线准备实施候选。正常 Host、容量零丢样、M2、Joint、goal_complete 和 hardware_authorized 均为 false；Spec、Quality 和 Root 副本验收仍待独立执行。后续真实硬件运行仍须 Root 单独准确批准，并沿用原单次与预算门。
'''.format(source=p['source'],tools=p['tools'],target=p['target'],ordinary=h.ORDINARY_SHA,normal=h.NORMAL_SHA,
           elapsed=production['elapsed_seconds'],freeze=identities['freeze_manifest']['sha256'],tar_sha=archive_receipt['identity']['sha256'],raw_bytes=space['archive_raw_bytes_after_tool_archive'])
(h.R/'results/strict-native-cache-v3-task1.md').write_text(md)
print('offline-ready candidate report and verified tools tar saved; independent acceptance and hardware remain pending')
