#!/usr/bin/env python3
"""Produce a bounded cause report without editing any existing evidence."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
R = OUT.parents[2]
TOOLS = Path('/tmp/crosspath-native-cache-v3-tools-jrhcn15t')
SOURCE = Path('/tmp/crosspath-native-cache-v3-src-hr23qnrs')
PHASE = R / 'raw/strict-native-phase-v3'


def load(path):
    return json.loads(path.read_bytes())


def reference(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def save(path, obj):
    with path.open('x') as stream:
        json.dump(obj, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write('\n')


original_paths = {
    'run_result': PHASE / 'AB1/run-result.json', 'owned_child': PHASE / 'AB1/owned-child.json',
    'xtask_log': PHASE / 'AB1/xtask.log', 'capture': PHASE / 'AB1/capture.json',
    'root_launch': PHASE / 'AB1-root-launch.json', 'root_wait': PHASE / 'AB1-root-wait.json',
    'root_completion': PHASE / 'AB1-root-supervisor-completion-v1.json',
    'final_handoff': PHASE / 'AB1-root-final-handoff-v1.json',
    'host_observation': PHASE / 'AB1-host-terminal-observation-v1.json',
    'native_source': TOOLS / 'native_once.py', 'capture_source': TOOLS / 'capture_native.py',
    'freeze_manifest': TOOLS / 'freeze-manifest.json', 'inputs': TOOLS / 'inputs.json',
    'case_marker': TOOLS / 'AB1.once', 'cargo_alias': SOURCE / '.cargo/config.toml',
    'xtask_main': SOURCE / 'xtask/src/main.rs',
    'board_stage_source': SOURCE / 'scripts/axbuild/src/context/mod.rs'}
refs = {k: reference(v) for k, v in original_paths.items()}
run = load(original_paths['run_result'])
owned = load(original_paths['owned_child'])
capture = load(original_paths['capture'])
root_wait = load(original_paths['root_wait'])
completion = load(original_paths['root_completion'])
handoff = load(original_paths['final_handoff'])
host = load(original_paths['host_observation'])
marker = load(original_paths['case_marker'])
inputs = load(original_paths['inputs'])
probe = load(OUT / 'exec-cleanup.receipt.json')
version = load(OUT / 'cargo-version.receipt.json')
summary = load(OUT / 'probe-summary.json')
native_text = original_paths['native_source'].read_text()
tree = ast.parse(native_text)
calls = sorted([{'method': n.func.attr, 'line': n.lineno, 'expression': ast.get_source_segment(native_text, n)}
    for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    and isinstance(n.func.value, ast.Name) and n.func.value.id == 'child'
    and n.func.attr in ['poll', 'wait']], key=lambda x: x['line'])
facts = {
    'child_wait_poll_calls': calls,
    'run_once': {
        'start_before_Popen_line': 295, 'Popen_lines': [299, 300], 'first_identity_line': 301,
        'bounded_real_wait_line': 304, 'timeout_lines': [305, 307], 'cleanup_call_line': 314,
        'cleanup_exception_lines': [319, 321], 'post_cleanup_poll_line': 322,
        'capture_call_line': 333, 'static_verification_line': 345,
        'result_lines': [348, 353], 'no_child_poll_or_wait_after_line_322': True},
    'cleanup': {
        'initial_poll_line': 216, 'initial_prove_line': 217,
        'leader_argv_comparison_lines': [203, 204], 'token_check_lines': [205, 206],
        'first_group_signal_line': 223,
        'error_does_not_persist_observed_cleanup_argv': True,
        'leader_argv_error_occurs_before_initial_token_check': True,
        'signal_path_control_flow_inference': 'The reported leader argv mismatch aborts the initial proof before the first killpg call. This is frozen-source reasoning, not an independently recorded signal syscall receipt.'},
    'capture': {'unconditional_post_exit_label_lines': [432, 434],
                'no_child_exit_argument_or_precondition': True},
    'project_startup': {
        'cargo_alias_line': 15, 'cargo_alias': 'run -p tg-xtask --',
        'xtask_main_lines': [5, 9], 'main_calls': 'axbuild::run().await?',
        'raw_log_running_tg_xtask_line': 2,
        'board_stage_done_requires_result_is_ok_lines': [[481, 487], [509, 515]],
        'board_stage_duration_is_Instant_elapsed_lines': [642, 663]}}
save(OUT / 'source-facts.json', facts)

log_lines = original_paths['xtask_log'].read_bytes().decode(errors='replace').splitlines()
selected = []
for lineno, line in enumerate(log_lines, 1):
    if lineno in [1, 2, 310, 325, 1172, 1568, 1640, 50103, 50104]:
        selected.append({'line': lineno, 'text': line})
save(OUT / 'original-log-excerpts.json', {'source': refs['xtask_log'], 'lines': selected})
save(OUT / 'probe-command.receipt.json', {
    'command': 'python3 -B tgoskits/research/cross-path-20261017/raw/strict-native-followup-v3/controller-cause-v1/local_probe.py',
    'cwd': '/home/yanlien/Program/hypervisor', 'tool': 'tools.exec_command',
    'tool_chunk': 'f38982', 'actual_command_exit_code': 0,
    'source': 'Actual tool return observed by investigator, not inferred from process absence',
    'actual_local_cargo_strace_parent_wait_exit': version['actual_parent_wait_exit'],
    'actual_local_exec_child_parent_wait_exit': probe['actual_parent_wait_exit']})

def utc_ns(value):
    secs, ns = divmod(value, 1_000_000_000)
    return datetime.fromtimestamp(secs, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + f'.{ns:09d}Z'

mtime_ns = original_paths['xtask_log'].stat().st_mtime_ns
timeline = {
    'case_marker_time_ns': marker['time_ns'], 'case_marker_utc': utc_ns(marker['time_ns']),
    'marker_plus_920_approximate_outer_deadline_utc': utc_ns(marker['time_ns'] + 920_000_000_000),
    'marker_not_exact_monotonic_start': True,
    'capture_time_ns': capture['capture_time_ns'], 'capture_utc': utc_ns(capture['capture_time_ns']),
    'raw_final_mtime_ns': mtime_ns, 'raw_final_mtime_utc': utc_ns(mtime_ns),
    'raw_mtime_minus_capture_timestamp_seconds': (mtime_ns - capture['capture_time_ns']) / 1e9,
    'raw_mtime_scope': 'File write metadata only; not an exact guest/board execution or process-exit timestamp.',
    'driver_elapsed_seconds': run['elapsed_seconds'], 'capture_elapsed_seconds': run['capture_elapsed_seconds'],
    'board_prepared_stage_reported_seconds': 856.03,
    'remaining_time_after_920_and_capture_seconds': run['elapsed_seconds'] - 920 - run['capture_elapsed_seconds'],
    'unallocated_elapsed_scope': 'Includes cleanup, static verification and overhead; no per-stage timing exists, so do not attribute it solely to cleanup or wait.'}

report = {
    'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
    'case_id': 'AB1', 'scope': 'Root cause investigation only; no repair or native rerun',
    'verdict': 'CONTROLLER_ARGV_IDENTITY_AND_TERMINAL_COLLECTION_GAP_CONFIRMED; HISTORICAL_EXEC_TARGET_AND_XTASK_EXIT_UNKNOWN',
    'original_evidence': refs,
    'original_terminal_facts': {
        'root_tool_session': completion['original_unified_exec_session'],
        'root_tool_terminal_chunk': completion['completion_tool_chunk'],
        'actual_root_tool_exit': completion['actual_unified_exec_exit'],
        'actual_driver_parent_Popen_wait_exit': root_wait['driver_wait_exit'],
        'xtask_wait_exit': run['xtask_wait_exit'], 'outer_timeout': run['outer_timeout'],
        'cleanup': run['cleanup'], 'release': run['release'], 'tool_errors': run['tool_errors'],
        'case_quota_consumed': handoff['case_quota_consumed'],
        'later_cases_unexecuted': handoff['later_cases_unexecuted'],
        'initial_child_identity': {k: owned[k] for k in ['pid', 'pgid', 'starttime', 'state', 'argv', 'expected_argv']},
        'actual_argv_item_count': len(owned['argv']),
        'initial_argv_equals_expected': owned['argv'] == owned['expected_argv'] == inputs['argv'],
        'ownership_token_omitted': True,
        'capture_artifact_chain_complete': capture['artifact_chain_complete'],
        'capture_host_function_passed': capture['host_function_passed'],
        'whole_native_round_success': False},
    'proved': [
        'The original Root tool and driver both exited 1. The original xtask Popen.wait did not return a terminal status within the controller budget.',
        'The original cleanup exception reports a group leader argv mismatch; the observed replacement argv/executable was not recorded.',
        'The frozen controller uses the immediate post-Popen argv as a later invariant. This can reject a legitimate exec that keeps PID/starttime/PGID/token.',
        'cleanup refusal is followed by one real child.poll at native_once.py:322. There is no further explicit child.poll/wait after capture begins or before report/return.',
        'A None at the last poll is persisted unchanged, even if the child later exits while evidence capture/static verification runs. Driver exit 1 is required by the timeout/tool_errors irrespective of a later child exit.',
        'The post-exit capture label is unconditional and cannot certify exit when run_once enters capture with xtask_wait_exit None.',
        'The installed cargo launcher is a symlink to rustup. A real local version-only trace shows that rustup execs the fixed toolchain cargo in the same traced process and rewrites argv[0] to the absolute cargo path.',
        'A real newly owned Python exec child reproduced the exact frozen cleanup refusal while retaining PID/starttime/PGID/token. The parent later obtained actual exit 23 with its original Popen.wait; no signals were sent.',
        'The final raw log has phase ACCEPT for both policies, frozen records 42768/dropped0/incomplete0, AXTEST_SUITE_OK and board stage done856.03s. These are separate from original child terminal and release evidence.'
    ],
    'not_proved': [
        'Which executable/argv the historical AB1 leader had at cleanup, and exactly when/how it changed. Rustup exec is a supported mechanism and plausible explanation, not a recovered historical event.',
        'Whether the historical leader still held the token at cleanup; the mismatch check occurs before that token check.',
        'The original xtask exit code or exact exit instant, or a successful historical finalize/release.',
        'The board/guest marker completion instant relative to the exact outer monotonic deadline; raw mtime is only write metadata.',
        'A complete allocation of the 955.909559556s driver interval to cleanup/capture/static verification. Only capture has its own recorded duration.',
        'Full normal-function acceptance or completion of the whole native round from guest/trace/artifact evidence alone.',
        'Any repaired controller behavior or authorization to retry consumed AB1 or run AB0/0.'
    ],
    'causal_chain': [
        {'step': 1, 'fact': 'The single original child.wait times out under outer920.', 'source_lines': [295, 304, 307]},
        {'step': 2, 'fact': 'finally calls cleanup; its initial proof rejects a live same-starttime group leader whose argv differs from the immediate startup snapshot.', 'source_lines': [184, 204, 217, 314]},
        {'step': 3, 'fact': 'The refusal handler stores cleanup unknown, then one final poll returns None in the observed result.', 'source_lines': [319, 322]},
        {'step': 4, 'fact': 'Capture and static verification proceed without collecting a later terminal result. The last None and unknown release remain.', 'source_lines': [327, 345]},
        {'step': 5, 'fact': 'Timeout error and cleanup error force driver_return_code1; the real Root parent and tool independently observe exit1.', 'source_lines': [348, 353]}
    ],
    'timeline': timeline,
    'source_facts': facts,
    'local_probes': {
        'cargo_version_actual_wait_exit': version['actual_parent_wait_exit'],
        'cargo_invocation_difference_from_AB1': 'Version probe uses explicit launcher path and isolated cwd/Cargo home/target; it does not execute xtask alias or recover historical AB1 argv.',
        'python_exec_actual_wait_exit': probe['actual_parent_wait_exit'],
        'frozen_function_AST_unmodified': probe['function_AST_unmodified'],
        'scoped_Path_adapter_limitation': probe['test_Path_scope'],
        'no_real_AB1_Popen_substitute': True, 'signals_sent': [], 'host_proc_scans': 0,
        'original_PID_not_observed_or_signalled': True,
        'all_assertions_passed': summary['all_assertions_passed']},
    'later_host_observation': {
        'observed_utc': host['observed_utc'], 'original_pid_absent_now': host['current_original_pid_observation']['original_pid_absent_now'],
        'group_empty_at_later_observation': host['current_group_observed_empty'], 'current_available': host['current_available'],
        'scope': host['scope'], 'does_not_recover_original_wait_or_historical_release': True},
    'minimal_next_step_for_Root': [
        'Treat v3 AB1 as exhausted failed-stop; keep AB0/0 unexecuted. Preserve the frozen candidate and original evidence.',
        'Before any new hardware candidate, validate a separate controller lifecycle design against real local owned exec transitions, terminal races, refusal and capture paths using original Popen handles.',
        'Specify and prove the exact approved launcher/exec identity chain before authorizing any signal. Persist compared argv/executable identity and token-check outcome without disclosing the token; do not relax ownership because this mechanism is plausible.',
        'Keep existing board/outer/cleanup/capture/lease limits. Any later original-child poll/wait evidence must remain separate from timeout failure and release; it cannot retroactively turn this AB1 into success.',
        'A future run requires a separately reviewed/frozen/authorized candidate and fresh quota. This investigation implements no change.'
    ],
    'integrity': {'existing_references_compared_before_after': 43,
                  'all_compared_bytes_and_metadata_unchanged': load(OUT / 'existing-evidence.before.json') == load(OUT / 'existing-evidence.after.json'),
                  'existing_reports_modified': False, 'failed_candidate_modified': False,
                  'source_builds': 0, 'board_or_QEMU_starts': 0, 'Git_commands': 0},
    'raw_evidence': {p.name: reference(p) for p in sorted(OUT.iterdir()) if p.is_file()},
    'repair_implemented': False, 'goal_complete': False}
assert refs['final_handoff']['sha256'] == 'cf25d62d4ff106f0e6d3315ce4e0b58ce5f4d78ac2e90b7b79fe814116e9b72f'
assert refs['freeze_manifest']['sha256'] == '0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8'
assert report['integrity']['all_compared_bytes_and_metadata_unchanged']
assert len(owned['argv']) == 20
json_path = R / 'results/strict-native-cache-v3-AB1-exit-cause-v1.json'
save(json_path, report)

md = f'''# strict native cache v3 AB1：控制器退出根因调查

原 AB1 仍是失败停止：Root 原 tool session 77494 / chunk 36f9ce 实际退出 1，driver 原父进程 `Popen.wait` 实际返回 1，xtask 退出码仍未知，`outer_timeout=true`，release unknown。AB1 配额已耗，AB0/0 未执行。本调查没有实现修复，也没有重跑硬件。

已证实的问题是：控制器把启动后立即采集的可变 argv 当作 cleanup 的永久身份条件，并在最后一次 poll 尚无结果时继续采证，之后不再显式收集原子进程退出状态。合法 exec 可以触发同样的拒绝；历史 AB1 到底变成哪个 argv 仍没有证据。

| 证据 | 实际结果与边界 |
| --- | --- |
| 冻结 `native_once.py:299-304` | 原 Popen 启动后立即记录 argv，再执行总预算 920 秒内的真实 wait。原 argv 与 expected 一致，实际是 20 项。 |
| `cleanup_owned:189-205,216-223` | 相同 PID/starttime/PGID 的 leader argv 不同即报 `owned group leader argv changed`；比较发生在 token 核验前。原拒绝没有保存实际新 argv/exe。该初始拒绝路径在首个 killpg 之前；这是源码控制流推导，不是独立信号 syscall 回执。 |
| `run_once:319-345` | 拒绝后仍有一次 `child.poll()`（322 行），所以“拒绝后从不再 poll”不准确；该次仍为 None。capture 与 static verification 后没有下一次显式 poll/wait。 |
| Cargo／项目入口 | launcher cargo 符号链接指向 rustup；`.cargo/config.toml:15` 的 xtask 是 `run -p tg-xtask --`。原 log:2 确有 target/debug/tg-xtask 启动记录，不能据此定位原 leader 的 exec 身份。 |
| 固定已安装 Cargo 的局部 strace | 仅运行一次隔离 `cargo --version`，同一 trace PID 从 rustup launcher exec 到固定工具链 Cargo，argv[0] 变为绝对路径，原 parent 真实 wait0。该次没有调用项目 alias，也不能还原 AB1。 |
| 自身新 Python Popen child | 合法 os.exec 前后 PID/starttime/PGID/token 相同；冻结函数 AST 未改，得到相同 argv changed。测试只把 `/proc` 枚举视图限制为该新 child，实际 stat/cmdline/environ 均来自内核；无宿主扫描、无信号，原 parent 真实 wait23。23 是局部测试退出码，绝非硬件退出码。 |

按原源码和结果可以确定如下路径：总预算 wait 超时 → finally cleanup 的首轮身份证明拒绝 → 存 cleanup unknown → 322 行 poll 仍 None → 继续 capture/static verification → 保存 None 并返回 1。超时错误已经足以要求 driver 失败；后来即使子进程成功退出，也不能恢复本轮成功或历史 release。

完整 raw log 记录两策略 phase ACCEPT、42768 条 frozen 事件（dropped0 / incomplete0）、`AXTEST_SUITE_OK` 以及 board stage done856.03s。普通源码 `context/mod.rs:481-487,509-515` 只在内部 board 调用返回 Ok 时打印 done；这不是原 Popen 的真实终止记录，也不证明整轮在外层预算内完成。

nonce 标记为 {timeline['case_marker_utc']}，加 920 秒约为 {timeline['marker_plus_920_approximate_outer_deadline_utc']}；该标记在 `start=time.monotonic()` 前，只可近似定位。capture 时间是 {timeline['capture_utc']}，raw 最终 mtime 是 {timeline['raw_final_mtime_utc']}（后约 {timeline['raw_mtime_minus_capture_timestamp_seconds']:.6f} 秒）。mtime 只说明文件写入时间，不能当作 Guest、板卡或进程退出的严格执行时间。capture 源码 432-434 行无条件写 `post-exit`，而本轮没有退出门禁支撑这个标签。

driver elapsed 为 {run['elapsed_seconds']:.9f} 秒，capture 为 {run['capture_elapsed_seconds']:.9f} 秒。扣除 920 和 capture 后约 {timeline['remaining_time_after_920_and_capture_seconds']:.6f} 秒没有分阶段计时，不能全部归为 cleanup，也不能把 driver elapsed 当作一次持续到终止的 xtask wait。

Root 在 {host['observed_utc']} 已另行确认原 PID 消失、group 当时为空、board available1；这是后来的只读观察，不恢复原 xtask wait，也不证明历史 release。本调查没有再次观察或发送信号给原 PID/group。

仍不能证明历史 exec 目标、转变时刻、cleanup 时 token 是否仍存在、xtask 最终退出码、历史 release 成功或整轮正常功能验收。rustup 的真实 exec 行为支持一个具体机制，但不能直接认定它就是历史唯一成因。

最小下一步是由 Root 审查独立控制器候选的本地生命周期证据：精确列明并证明授权 launcher/exec 链，记录实际比较的 argv/exe 与 token 核验结果（不泄露 token），覆盖合法 exec、退出竞态、cleanup 拒绝与采证期间终止的真实父子进程路径。保留现有 board/outer/cleanup/capture/lease 时限和所有权约束；不要重用本轮配额，不把迟到的终止记录追认为本轮成功。该调查没有制作新候选。

原 final handoff SHA256：`{refs['final_handoff']['sha256']}`。冻结 manifest SHA256：`{refs['freeze_manifest']['sha256']}`；`native_once.py` SHA256：`{refs['native_source']['sha256']}`。43 项已有证据／源码／控制器的字节与元数据前后完全一致。

原始局部证据位于 [controller-cause-v1](../raw/strict-native-followup-v3/controller-cause-v1/)，包括脚本、真实 execve trace、真实 wait 回执、源码行号事实及前后 SHA 清单。[JSON 报告](strict-native-cache-v3-AB1-exit-cause-v1.json) 保存各引用精确 SHA 和全部限制。局部诊断命令工具 chunk f38982 实际退出 0；没有 board/QEMU、主源码构建、Git 或宿主 `/proc` 扫描。
'''
md_path = R / 'results/strict-native-cache-v3-AB1-exit-cause-v1.md'
with md_path.open('x') as stream:
    stream.write(md)
print(json.dumps({'created': [reference(json_path), reference(md_path)], 'existing_evidence_unchanged': True,
                  'historical_xtask_wait_exit': None, 'repair_implemented': False}, ensure_ascii=False))
