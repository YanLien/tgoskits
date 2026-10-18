#!/usr/bin/env python3
"""Audit current recorder costs without upgrading them to the full M1 gate."""
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads((archive/p).read_text())
plan = read('configs/recorder-ops-plan.json')
state = read('results/recorder-ops-status.json')
assert state['terminal'] and state['success'] and len(state['completed']) == 18
assert all(digest(repo/p) == h for p, h in plan['source_sha256'].items())
assert all(digest(repo/p) == h for p, h in plan['control_sha256'].items())
patch = read('results/recorder-operations-patch-audit.json')
assert patch['isolated_apply_matches_live_sources'] and len(patch['changed']) == 3
assert all(digest(repo/p) == h['after_sha256'] for p, h in patch['changed'].items())
with tarfile.open(archive/'configs/recorder-ops-before.tar.gz') as before:
    for m in before:
        if m.isfile() and (m.name.startswith(('virtualization/axvm/src/', 'components/axcpu/', 'drivers/ax-driver/', 'test-suit/arceos/cpu/pmu/'))
                           or m.name in ('virtualization/axvm/Cargo.toml', 'Cargo.lock')):
            assert before.extractfile(m).read() == (repo/m.name).read_bytes()
ram = read('results/private-ram-patch-audit.json')
assert digest(repo/ram['source']) == ram['after_sha256']
assert 'malformed VIRQ_RECORDING' in (archive/'raw/recorder-ops-scope-red.log').read_text()
assert 'passed checks: 29, failed checks: 0, skipped checks: 0' in (archive/'raw/recorder-ops-clippy.log').read_text()
tests = (archive/'raw/recorder-ops-analysis-tests.log').read_text()
assert 'Ran 42 tests' in tests and '\nOK\n' in tests
stat = read('configs/recorder-ops-statistics-contract.json')
assert stat['success'] and stat['main_source_unchanged'] and stat['red_exit'] != 0 and stat['green_exit'] == 0
assert stat['source_sha256'] == digest(archive/'recorder_ops_statistics.py')
assert stat['test_sha256'] == digest(archive/'test_recorder_ops_statistics.py')
assert stat['red_log_sha256'] == digest(archive/'raw/recorder-ops-statistics-unit-red.log')
assert stat['green_log_sha256'] == digest(archive/'raw/recorder-ops-statistics-unit-green.log')
assert 'AssertionError' in (archive/'raw/recorder-ops-statistics-unit-red.log').read_text()
subprocess.run(['python3', str(archive/'summarize-recorder-ops.py')], cwd=repo, check=True, stdout=subprocess.DEVNULL)
summary = read('results/recorder-ops-paired-summary.json')
assert summary['independent_pairs'] == 8 and summary['native_boots'] == 16 and summary['task_observations'] == 1024
assert summary['statistics'] == plan['statistics'] and not summary['M1'] and not summary['M2']
assert sum(b['order'] == ['on', 'off'] for b in plan['blocks']) == 4
assert sum(b['order'] == ['off', 'on'] for b in plan['blocks']) == 4
pilots = []
for run in plan['pilots']:
    name, mode = run['name'], run['mode']
    config = archive/'configs'/name
    identity = read(f'configs/{name}/provenance.json')
    assert identity['runtime'] == 'qemu' and identity['exit_code'] == 0
    assert identity['raw_log_sha256'] == digest(archive/'raw'/(name+'.log'))
    for key, filename, sha_key, metadata in (
        ('source_sha256', 'sources.tar.gz', 'source_archive_sha256', identity),
        ('host_source_sha256', 'host-sources.tar.gz', 'host_source_archive_sha256', identity),
        ('source_sha256', 'driver-sources.tar.gz', 'archive_sha256', read(f'configs/{name}/driver-source-provenance.json')),
        ('source_sha256', 'cpu-sources.tar.gz', 'archive_sha256', read(f'configs/{name}/cpu-source-provenance.json'))):
        assert digest(config/filename) == metadata[sha_key]
        with tarfile.open(config/filename) as snapshot:
            assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == h for p, h in metadata[key].items())
        assert all(digest(repo/p) == h for p, h in metadata[key].items())
    decoded = read(f'results/{name}/analysis-input-provenance.json')
    input_path = archive/'results'/name/'analysis-input.log'
    assert decoded['measurement_bytes_unchanged'] and decoded['decoding_valid_for_analysis']
    assert decoded['raw_sha256'] == identity['raw_log_sha256'] and decoded['analysis_input_sha256'] == digest(input_path)
    raw, data = (archive/'raw'/(name+'.log')).read_bytes(), input_path.read_bytes()
    assert raw[raw.index(b'VIRQ_MEASUREMENT '):] == data[data.index(b'VIRQ_MEASUREMENT '):]
    result = read(f'results/{name}/probe_cost/summary.json')
    assert result['comparison_scope'] == 'recorder_operations' and result['recording_declaration_version'] == 2
    assert result['recording_mode'] == mode and result['complete_chain_accepted'] == (mode == 'on')
    assert all(p['samples'] == 32 for p in result['policies'].values())
    counter = read(f'results/{name}/counter/summary.json')
    assert counter['series'] == 48 and counter['raw_reads'] == 12288 and counter['recording_mode'] == mode
    if mode == 'off':
        assert 'disabled recorder cannot establish a complete runtime chain' in (archive/'results'/name/'complete-task-rejection.log').read_text()
        assert 'disabled recorder has no IRQ stage observations' in (archive/'results'/name/'complete-stages-rejection.log').read_text()
    pilots.append(dict(name=name, mode=mode, tasks=64, performance_evidence=False))
for run in state['completed']:
    name = run['name']
    log = (archive/'results'/name/'analysis-input.log').read_text()
    retired = [m.start() for m in re.finditer('VIRQ_VM_GROUP_RETIRED count=2 empty=1', log)]
    counter_exports = [m.start() for m in re.finditer('VIRQ_COUNTER_SERIES ', log)]
    assert len(retired) == 2 and len(counter_exports) == 48 and min(counter_exports) > max(retired)
    assert max(counter_exports) < log.index('VIRQ_TRACE_FROZEN ')
    if run['runtime'] == 'board':
        identity = read(f'configs/{name}/provenance.json')
        raw_log = (archive/'raw'/(name+'.log')).read_bytes().decode('utf-8', errors='replace')
        fits = re.findall(r'FIT image ok: (\S+)', raw_log)
        dtbs = re.findall(r'Using DTB from: (\S+)', raw_log)
        assert fits and dtbs
        # Only the exact paths in this run's boot transcript establish use.
        # Other cached artifacts in artifact_sha256 are merely observed files.
        assert digest(archive/'configs'/name/'host-boot.fit') == identity['artifact_sha256'][fits[-1]]
        assert digest(archive/'configs'/name/'host-input.dtb') == identity['artifact_sha256'][dtbs[-1]]
report = dict(native_pairs=8, native_boots=16, native_task_observations=1024, qemu_task_observations=128,
              recorded_native_tasks=512, task_only_native_observations=512, qemu_pilots=pilots,
              declaration_version=2, source_identity_verified=True, host_core_and_pmu_unchanged=True,
              clippy_checks=29, analysis_tests=42, statistics_tests=1, marker_scope_corrected=True,
              native_frequency_snapshots=256, native_counter_series=768, native_counter_raw_reads=196608,
              native_thermal_snapshots=64, M1=False, M2=False, audit_script_sha256=digest(Path(__file__)))
(archive/'results/recorder-ops-audit.json').write_text(json.dumps(report, indent=2)+'\n')
lines = ['# 当前记录操作开销报告', '', '## 1. 对照与可观察端点', '',
         '本轮 8 个独立真板启动对，共 16 次启动、1024 条有效任务观察；on/off 顺序平衡随机化并在运行前归档，种子 20261021。每启动含 Fair/FIFO 各 32 个任务；512 条 on 任务有记录并通过既有物理任务链入口，512 条 off 仅作任务观察，丢样状态未知，不伪造 T0 或调度阶段。另有 QEMU on/off 共 128 条任务，仅验证功能，不进入性能估计。', '',
         '唯一实验因素为 VIRQ_RECORDING，频率/温度/连续计数序列在两模式均启用。两 VM、CPU0 服务/CPU1 关键任务/CPU3 Linux、PPI30、20 ms 周期、4096 轮已知答案任务、10 ms deadline、Linux CPU 基线、SGI 关闭均固定；Guest/Host 输入、源码和工具身份经逐组核对。Fair 后 FIFO 的启动内顺序固定，以下分别估计记录开关差值，不作为随机化策略优劣比较。', '',
         '共同端点为计划释放到 Guest 任务完成，保留 Host/Guest 偏移区间。off 不具备实测中断入口，不能称为 T0→T6 对照。发布前/后的阶段关联质量仍须分别审计，物理任务链入口接纳也不等于论文 M1 已完成。', '',
         '## 2. 配对均值差与不确定性', '', '| 策略 | on−off 均值端点区间 (µs) | 配对 Bootstrap 百分位包围 (µs) | Guest 执行均值差 (ns) | Linux 速率平均变化 |', '| --- | --- | --- | --- | --- |']
for policy, p in summary['policies'].items():
    lines.append(f'| {policy} | {p["latency_on_minus_off_mean_lower_ns"]/1000:.3f}～{p["latency_on_minus_off_mean_upper_ns"]/1000:.3f} | {p["paired_bootstrap_95_lower_ns"]/1000:.3f}～{p["paired_bootstrap_95_upper_ns"]/1000:.3f} | {p["task_execution_on_minus_off_mean_ns"]:.2f} | {p["linux_rate_change_percent"]:+.3f}% |')
lines += ['', '重采样单位是完整独立启动对，每策略 8 个单位，10000 次，种子 20261022。下界均值的 2.5 百分位至上界均值的 97.5 百分位形成经验包围；保留偏移端点但不认证小样本覆盖率、参考时钟校准或可见更新误差。不能将 32 个启动内任务当独立重复。差值允许为负，不预设正开销。逐对结果见 recorder-ops-paired-replicates.csv。', '',
          '## 3. 范围修正与环境', '',
          '早先“仅记录写入”的表述不准确。record_at 在关闭时于入口返回，内部生成时间戳、IRQ 守卫、writer 登记、槽位预留和写入等启用路径操作都随开关停止；v2 因此声明 recorder_operations。旧 recorder_writes 声明仍可读取，但标签不保证纯内存写入比较。Host 核心与探针逻辑本轮没有改变，三文件补丁只修正运行声明、解释范围和原有行为测试。', '',
          '独立的任务/IRQ 时间戳、入口检查、编译 hook、邮箱轮询、Guest 时间戳与 Linux 围栏仍存在，差值不是全部测量成本。Marker 包围也包含计时和可能抢占，不当成纯指令成本。原第 16 版本数值不移用于本轮。', '',
          '| 模式 | SoC 快照范围 (°C) | A55 簇快照范围 (°C) | 名义比例频率快照范围 (MHz) |', '| --- | --- | --- | --- |']
for mode in ('on', 'off'):
    env = [r for r in summary['environment'] if r['mode'] == mode]
    lines.append(f'| {mode} | {min(r["soc_snapshot_min_mc"] for r in env)/1000:.3f}～{max(r["soc_snapshot_max_mc"] for r in env)/1000:.3f} | {min(r["little_snapshot_min_mc"] for r in env)/1000:.3f}～{max(r["little_snapshot_max_mc"] for r in env)/1000:.3f} | {min(r["nominal_frequency_snapshot_min_hz"] for r in env)/1e6:.3f}～{max(r["nominal_frequency_snapshot_max_hz"] for r in env)/1e6:.3f} |')
lines += ['', '这些都是 VM 创建前/退休后的观测，不是运行窗口最大温度、恒频或受控 OPP 的证明。连续计数 GCD 只作观察统计；频率为公布参考尺度下的快照比例估计。平衡顺序不能消除未知环境或跨启动残留效应。U-Boot/BL31 逐次身份仍不完整，不以固定输入 DTB/FIT 的哈希冒充不可变固件。环境逐启动记录见 recorder-ops-environment.csv。', '',
          '## 4. 尾部、违约与正确性', '', '| 策略 / 模式 | P99 名义区间 (µs) | P99.9 名义区间 (µs) | 观察 DMR 时钟分类界 |', '| --- | --- | --- | --- |']
for policy, p in summary['policies'].items():
    for mode in ('on', 'off'):
        tail = p['descriptive_tails'][mode]
        lo, hi = tail['p99_nominal_ns']
        low, high = tail['p999_nominal_ns']
        dmr = p['observed_dmr_clock_bounds'][mode]
        lines.append(f'| {policy} / {mode} | {lo/1000:.3f}～{hi/1000:.3f} | {low/1000:.3f}～{high/1000:.3f} | {dmr[0]:.6f}～{dmr[1]:.6f} |')
lines += ['', '每策略/模式 256 个任务，P99.9 已退化为最大次序统计量，不是可靠极端尾部精度、未来 deadline 保证或严格 WCET/WCRT。DMR 区间描述时钟分类，非统计置信区间；分位数不做加性交互推断。', '',
          '29 项 Clippy、42 项分析测试通过。相同增强测试在旧声明解析实现上先失败，更新后通过；legacy 兼容及非法 scope/version 组合拒绝均保留。独立统计行为测试通过；隔离副本把每对的 32 个任务当独立重复后稳定失败，主源码未变。两组 QEMU 与 16 组真板均保留原始日志、源码/镜像身份和测量字节；off 另保留完整任务链和 IRQ 阶段分析的精确预期拒绝。', '',
          '## 5. 剩余门', '',
          '本轮量化当前记录启用路径的观测差值，未隔离所有残余探针，也未完成剩余阶段归因和固件身份。M1/M2 继续 false。下一步按原论文要求审计 T0～T6 的实际边界与可关联比例，然后运行交错/随机重复 0/A/B/AB，以同一运行级均值估计 I_AB 及不确定性，尾部、DMR、吞吐分别报告；不将有限时钟精度隐瞒，也不把严格物理误差认证当作无限推迟四组的理由。没有耦合、联合优化收益或严格 WCET/WCRT 完成声明。', '']
(archive/'results/recorder-ops-report.md').write_text('\n'.join(lines))
print('RECORDER_OPS_AUDIT_OK native_pairs=8 native_tasks=1024 qemu_tasks=128 M1=0 M2=0')
