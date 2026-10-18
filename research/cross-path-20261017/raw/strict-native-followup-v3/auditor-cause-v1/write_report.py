#!/usr/bin/env python3
"""Archive facts from isolated read-only probes; never change the sealed auditor."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
RESULT = R / 'results/strict-native-cache-v3-AB1-auditor-cause-v1'


def reference(path, expected=None):
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    if expected:
        assert checksum == expected, (str(path), checksum)
    return dict(path=str(path), bytes=len(raw), sha256=checksum)


def document(path, expected=None):
    ref = reference(path, expected)
    return json.loads(path.read_bytes()), ref


fmt, fmt_ref = document(HERE / 'format-diagnosis.json')
suite, suite_ref = document(HERE / 'suite-diagnosis.json')
handoff, handoff_ref = document(R / 'raw/strict-native-phase-v3/AB1-root-final-handoff-v1.json',
    'cf25d62d4ff106f0e6d3315ce4e0b58ce5f4d78ac2e90b7b79fe814116e9b72f')
original, original_ref = document(R / 'raw/strict-native-phase-v3/function-audit-v1/AB1-actual-audit-v1/report.json',
    '1a9257ef78caf570267dcb89c60d3143cf97dd033f9460b56176347f594d0b25')
capture, capture_ref = document(R / 'raw/strict-native-phase-v3/AB1/capture.json',
    '9b7004231459f32e1078b86505cbb3c73104d4c5d05862ed21fd6084c0ca7dd6')
actual_receipt, actual_receipt_ref = document(R / 'raw/strict-native-phase-v3/AB1-actual-audit-v1.receipt.json')
assert actual_receipt['actual_Popen_wait'] == 1
assert original['full_function_passed'] is False
assert len(fmt['saved_artifacts']) == 17 and all(x['verified'] for x in fmt['saved_artifacts'].values())
assert fmt['fit_ramdisk_bytes_equal_saved_host_initramfs'] is True
raw_segment, gzip_segment = fmt['host']['container_segments']
assert raw_segment['bytes'] == gzip_segment['offset'] == 1364
assert gzip_segment['bytes'] == 17796318
assert not fmt['host']['sealed_auditor_whole']['accepted']
assert fmt['host']['approved_capture_whole']['accepted']

# Preserve a tiny exact boundary, not another copy of the complete initramfs.
host_ref = fmt['host']['reference']
with Path(host_ref['path']).open('rb') as source:
    source.seek(1332)
    boundary = source.read(96)
assert boundary[32:34] == b'\x1f\x8b'
(HERE / 'host-newc-gzip-boundary.raw').write_bytes(boundary)
boundary_ref = reference(HERE / 'host-newc-gzip-boundary.raw')
boundary_ref.update(source_path=host_ref['path'], source_sha256=host_ref['sha256'],
                    source_offset=1332, source_end_exclusive=1428, hex=boundary.hex())

receipts = []
for path in sorted((HERE / 'commands').glob('*/receipt.json')):
    row, ref = document(path)
    # These are this investigation's already completed real child waits.
    actual = row.get('wait_returncode', row.get('actual_Popen_wait', row.get('returncode')))
    assert actual == 0, (str(path), actual)
    receipts.append(dict(reference=ref, actual_Popen_wait=actual, argv=row['argv']))
assert len(receipts) == 7

failed = ['same-run-launch-wait-completion-binding',
          'full-suite-no-additional-failure-or-tail',
          'actual-artifact-use-chain',
          'actual-exits-and-frozen-explicit-release']
assert all(name in json.dumps(original['gates']) for name in failed)

report = dict(
    schema_version=1,
    scope='read-only diagnosis of two AB1 auditor refusals; no implementation, full audit, hardware rerun, or acceptance',
    case_id='AB1',
    normal_end_to_end_GREEN=False,
    full_function_passed=False,
    actual_original_audit=dict(reference=original_ref, receipt=actual_receipt_ref,
                               actual_Popen_wait=1, result_preserved=True, failed_gates=failed),
    bound_inputs=dict(final_handoff=handoff_ref, capture=capture_ref,
                      raw=suite['sources']['raw'], sealed_sources=fmt['sources'],
                      saved_artifacts=fmt['saved_artifacts']),
    artifact_refusal=dict(
        conclusion='The sealed auditor is incompatible with the approved Host append-newc/gzip container. The observed boundary is not arbitrary junk or a malformed single archive.',
        formal_error='AuditError: newc trailer/tail',
        actual_callsite=dict(source=fmt['sources']['sealed_auditor'], line=668,
                             expression="host, _ = newc(components['ramdisk'])"),
        failing_rule=dict(line=557, expression="need(not size and not mode and not any(raw[pos:]), 'newc trailer/tail')",
                          trailer_mode=0, trailer_payload_bytes=0, post_trailer_position=1364,
                          any_remaining_nonzero=True, first_remaining_nonzero_offset=1364,
                          first_remaining_bytes_hex='1f8b08000000000000ff'),
        fit_default=fmt['fit_default'], fit_ramdisk_node=fmt['fit_ramdisk_node'],
        fit_ramdisk_equals_saved_host_initramfs=True,
        host_container=dict(reference=host_ref, total_bytes=17797682,
                            format='raw newc resource archive [0,1364), then gzip member [1364,17797682) containing a second newc archive',
                            segments=fmt['host']['container_segments'],
                            whole_sealed_auditor=fmt['host']['sealed_auditor_whole'],
                            whole_approved_capture=fmt['host']['approved_capture_whole'],
                            duplicate_name='.', duplicate_kind='matching empty directory; approved merger permits this and rejects other duplicate payloads',
                            boundary=boundary_ref),
        approved_capture_contract=dict(
            source=fmt['sources']['approved_capture'],
            strict_single_archive_lines=[86,131], host_container_lines=[296,345],
            behavior='Consumes bounded raw archives and gzip members, requires gzip EOF, recursively parses inflated archives, and permits duplicate paths only for matching empty directories.',
            host_callsite_line=486, guest_rootfs_strict_callsite_line=506,
            original_capture_artifact_chain_complete=capture['artifact_chain_complete'],
            original_capture_errors=capture['errors']),
        guest_rootfs=fmt['guest_rootfs'],
        scope_limit='Only exact saved format/decomposition and parser compatibility were reprobed. Other saved artifacts were SHA/size verified, not a rerun of the full use-chain gate.'),
    suite_refusal=dict(
        conclusion='Exactly two DTS simple_bus_reg Warning lines contain the standalone word error; both become unclassified-reject under the sealed generic candidate rule.',
        formal_error='AuditError: failure/diagnostic/unclassified error candidate or unframed final bytes observed',
        source=suite['sources']['sealed_auditor'],
        candidate_regex_line=24, classification_lines=[124,138], retention_lines=[156,161],
        rejecting_gate_line=525,
        candidate_count=2, candidates=suite['candidates'],
        raw_candidate_copy=suite['raw_candidate_copy'],
        candidate_match=dict(word='error', text_offset=201,
                             source_raw_offsets=[2896,5374], bytes=5),
        explicit_or_protocol_failure_candidate_count=suite['explicit_or_protocol_failure_candidate_count'],
        unframed_nonempty_final_rows=suite['unframed_nonempty_final_rows'],
        suite_marker_records=suite['suite_marker_records'],
        semantic_boundary='Observed severity is Warning (simple_bus_reg), emitted around Zephyr DTS generation/linking. This is neither a CMake failure flag nor a compiler fatal-error line. The investigation does not determine whether the DTS mismatch itself is acceptable hardware configuration.',
        suite_pass_does_not_override_whole_run_failure=True),
    user_cache=suite['user_cache'],
    minimal_proposals_not_implemented=dict(
        host_container='Add a source-bound Host container reader for the already approved raw-newc/gzip append format. Keep strict per-archive trailer/name/type/hardlink checks, gzip EOF/tail checks, duplicate conflict checks, and exact payload identity checks. Keep Guest rootfs on the strict single-archive path.',
        suite_classification='If separately approved, classify only the evidenced DTS simple_bus_reg Warning grammar in its build-output context as a retained build warning. Do not allow all Warning lines or silently discard unknown errors; preserve raw spans and non-error classification.',
        required_negative_checks=[
            'Host: truncated header/name/payload/trailer; nonzero or malformed trailer; arbitrary inter-archive tail; truncated/invalid gzip; unsupported next magic; duplicate regular payload or incompatible duplicate directory; expected payload identity mismatch.',
            'Suite: known failure markers, nonzero errors/dropped/incomplete, Error:/error: or fatal tool diagnostics, changed/unknown warning prose containing error, and truncated LINUX_PHA tail must continue to reject.',
            'Same saved failed AB1 must remain a full failure while xtask wait is null and explicit release unknown; AB0/0 remain unexecuted.'
        ],
        approval_or_new_implementation_requested=False),
    performed=[
        'Verified exact final handoff, original audit report, sealed auditor, frozen capture, raw log, and freeze-bound offline witness bytes.',
        'Streamed SHA/size verification of all 17 accurately saved artifacts; selected actual FIT default ramdisk and compared every ramdisk byte with saved Host initramfs.',
        'AST-extracted only pure format functions from exact sealed sources; called those functions on exact actual Host, bounded real internal archives, and Guest rootfs bytes.',
        'Ran isolated immutable regex rules over exact raw log; reproduced the original two candidate classifications and retained exact candidate bytes, offsets, and original suite marker spans.',
        'Compared actual raw Cache files selection with the exact field in the freeze-bound offline causal witness.',
        'Recorded seven completed diagnostic commands as real Popen waits with exact argv/env/stdout/stderr. Report-generation and final sealing receipts reside in the same commands directory.'
    ],
    not_performed_or_unknown=[
        'No implementation or sealed report changes; no full audit/tests/build/ready/Git/board/network/proc/signal command; no cache/source scan or modification.',
        'No proof of complete artifact-use-chain PASS from these isolated probes; no new complete normal-function GREEN.',
        'USER_CACHE selection cause and resulting mutation scope are unknown in this investigation; no attempt to reconcile or modify them.',
        'Controller timeout/cleanup/xtask-wait/release cause is outside this task and remains delegated independently.',
        'AB0 and 0 were not run; Host/M2/Joint/overall goal completion is not asserted.'
    ],
    evidence=dict(format_diagnosis=fmt_ref, suite_diagnosis=suite_ref,
                  source_rules=reference(HERE / 'source-rules.json'),
                  scripts=[reference(HERE / name) for name in ['run_command.py','inspect_formats.py','inspect_suite.py','write_report.py']],
                  completed_diagnostic_command_receipts=receipts,
                  command_receipts_directory=str(HERE / 'commands')))
RESULT.with_suffix('.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')

md = f'''只读调查已定位两个拒绝点，正式 AB1 失败保持不变；本报告不实现修复，不重跑完整审计。原完整审计 SHA `{original_ref['sha256']}`、实际 Popen.wait=1；最终 handoff SHA `{handoff_ref['sha256']}`。完整正常功能 GREEN 仍为 false，AB0/0 未执行。

- Host 实际保存 initramfs 为 17,797,682B，SHA `{host_ref['sha256']}`；FIT 默认 `/configurations/config-ostool` 的 `/images/ramdisk` 与它全字节相同。它由原始 newc `[0,1364)` 与 gzip `[1364,17797682)` 拼接，gzip 内是 54,086,784B 的第二份 newc。首个 TRAILER header 偏移 1240，mode=0、size=0、结束于 1364；该处原字节为 `1f8b08000000000000ff`。两份实际 archive 单独均被两套严格解析器接受，Guest rootfs 也被两者接受。
- 封存 auditor SHA `6fa57d1b...` 的 [audit.py]({fmt['sources']['sealed_auditor']['path']}:668) 将整个 Host 容器交给单 archive `newc()`；[第 557 行]({fmt['sources']['sealed_auditor']['path']}:557) 用 `any(raw[pos:])` 拒绝首个 TRAILER 后的合法 gzip。冻结 capture SHA `61717a37...` 的 [\u005fnewc_entries]({fmt['sources']['approved_capture']['path']}:296) / [newc_members]({fmt['sources']['approved_capture']['path']}:343) 明确支持该拼接，并检查 gzip EOF、逐 archive 合法性和重复项。原 capture `artifact_chain_complete=true/errors=[]` 与本次纯格式结果一致。结论是 auditor 不兼容已批准 Host 拼包格式，不能把合法 gzip 称为任意残尾；本次未重跑完整 use-chain 门。
- suite 原始候选仅两条，位于 xtask.log 第 24/52 行、偏移 2695/5173、各 228B，同 SHA `c83438e2c6ba62743446b3445873b1486bb7309f41bb7c3cfef9cff3477e0283`。原文是 `Warning (simple_bus_reg): ... simple-bus unit address format error, expected "fe600000"`。命中为文本偏移 201 的独立单词 `error`，对应原日志偏移 2896/5374；[候选 regex 第 24 行]({fmt['sources']['sealed_auditor']['path']}:24) 和 [分类第 135 行]({fmt['sources']['sealed_auditor']['path']}:135) 将其保留为 `unclassified-reject/requires_rejection=true`，[suite 第 525 行]({fmt['sources']['sealed_auditor']['path']}:525) 因此拒绝。没有额外 explicit/protocol failure 候选，也无未换行残尾。实际 suite pass/summary/OK 仍在第 50101/50102/50103 行，但不能覆盖整轮失败。这是 DTS 警告文案的分类边界，不是 CMake 失败旗标或编译 fatal error；DTS 地址差异本身是否可接受未在此验证。
- 实际 [xtask.log]({suite['sources']['raw']['path']}:11) 偏移 1138、63B、SHA `a213fe1b38cdb90f43d77e485c347185b6a36081534f7dd25da046a7500ba2bd` 明确选择 `/home/yanlien/.cache/zephyr`。冻结离线 witness SHA `b863d65a...` 的 `actual_stdout_selects_user_cache` 明确记载候选目录下 `.../zephyr/.cache`，两者不同；本任务未追查选择原因、未读改 cache/env，不能声称一致。

最小建议仅供后续审批：Host 容器读取应匹配已批准 append-newc/gzip 合同，保留逐 archive、gzip EOF/残尾、重复冲突和实际 payload SHA 检查；Guest rootfs 继续严格单 archive。日志若调整，应只针对有准确构建上下文的这条 DTS Warning 语法显式分类并保留原始证据，不作通用 Warning 放行。修订必须有截断/垃圾尾/重复 payload/非法 gzip，以及真实错误、非零 counters、未知 error 文案和 `LINUX_PHA` 残尾负例；当前 null xtask wait/unknown release 仍须拒绝完整正常门。

已做：准确 17 工件的流式 SHA/size 核对、纯格式函数和孤立 regex 调用；完整偏移/头字节/归档跨度/源码行见 [JSON]({RESULT.with_suffix('.json')})，微小原字节保存在 `{HERE}`。每条实际命令的 argv/env/stdout/stderr 和真实 Popen.wait 收据均在 `commands/`。未做：修复、完整 audit/tests、硬件、build/ready、Git、网络、proc/signal、cache/source 修改。控制器根因另由独立任务处理；本次不宣称 Host/M2/Joint 或整体目标完成。
'''
RESULT.with_suffix('.md').write_text(md)
print(json.dumps(dict(json=reference(RESULT.with_suffix('.json')),
                      markdown=reference(RESULT.with_suffix('.md')),
                      sealed_auditor_unchanged=reference(Path(fmt['sources']['sealed_auditor']['path']),
                          '6fa57d1bb99a9fbdb49613ffc90cb4b648aa9511465957aec25b9e58e34e76aa'),
                      normal_end_to_end_GREEN=False), indent=2))
