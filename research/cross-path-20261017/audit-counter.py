#!/usr/bin/env python3
"""Audit raw EL2 counter observations and preserve their interpretation limits."""
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
plan = read('configs/counter-check-plan.json')
state = read('results/counter-check-status.json')
assert state['terminal'] and state['success'] and len(state['completed']) == 3
assert all(digest(repo/p) == h for p, h in plan['source_sha256'].items())
assert all(digest(repo/p) == h for p, h in plan['control_sha256'].items())
patch = read('results/counter-increments-patch-audit.json')
assert patch['isolated_apply_matches_live_sources'] and len(patch['changed']) == 5
assert all(digest(repo/p) == h['after_sha256'] for p, h in patch['changed'].items())
with tarfile.open(archive/'configs/counter-before.tar.gz') as baseline:
    for m in baseline:
        if m.isfile() and (m.name.startswith(('virtualization/axvm/src/', 'components/axcpu/', 'drivers/ax-driver/', 'test-suit/arceos/cpu/pmu/'))
                           or m.name in ('virtualization/axvm/Cargo.toml', 'Cargo.lock')):
            assert baseline.extractfile(m).read() == (repo/m.name).read_bytes()
ram = read('results/private-ram-patch-audit.json')
assert digest(repo/ram['source']) == ram['after_sha256']
contract = read('configs/counter-reversal-contract.json')
assert contract['success'] and contract['source_restored'] and contract['red_exit'] != 0 and contract['green_exit'] == 0
assert contract['original_sha256'] == digest(repo/'virtualization/axvm/tests/analysis/analyze_virq_counter.py')
for phase in ('red', 'green'):
    assert contract[phase+'_log_sha256'] == digest(archive/'raw'/('counter-reversal-'+phase+'.log'))
assert 'ValueError not raised' in (archive/'raw/counter-reversal-red.log').read_text()
assert 'passed checks: 29, failed checks: 0, skipped checks: 0' in (archive/'raw/counter-clippy.log').read_text()
tests = (archive/'raw/counter-analysis-tests.log').read_text()
assert 'Ran 42 tests' in tests and '\nOK\n' in tests
runs, all_rows, all_sensitivity = [], [], []
reference = None
for run in plan['runs']:
    name = run['name']
    config = archive/'configs'/name
    provenance = read(f'configs/{name}/provenance.json')
    driver = read(f'configs/{name}/driver-source-provenance.json')
    cpu = read(f'configs/{name}/cpu-source-provenance.json')
    raw_path = archive/'raw'/(name+'.log')
    assert digest(raw_path) == provenance['raw_log_sha256'] and provenance['exit_code'] == 0 and provenance['suite_passed']
    assert provenance['capture_script_sha256'] == digest(archive/'capture-periodic.py')
    assert driver['capture_script_sha256'] == digest(archive/'capture-thermal-driver.py')
    assert cpu['capture_script_sha256'] == digest(archive/'capture-frequency-cpu.py')
    assert provenance['cargo_lock_sha256'] == digest(repo/'Cargo.lock')
    current = dict(tests=provenance['source_sha256'], host=provenance['host_source_sha256'],
                   driver=driver['source_sha256'], cpu=cpu['source_sha256'], git_commit=provenance['git_commit'],
                   tracked_diff_sha256=digest(config/'tracked-worktree-before.patch'), git_status_sha256=digest(config/'status-before.txt'))
    if reference is None:
        reference = current
    else:
        assert current == reference
    for key, filename, sha_key, metadata in (
        ('source_sha256', 'sources.tar.gz', 'source_archive_sha256', provenance),
        ('host_source_sha256', 'host-sources.tar.gz', 'host_source_archive_sha256', provenance),
        ('source_sha256', 'driver-sources.tar.gz', 'archive_sha256', driver),
        ('source_sha256', 'cpu-sources.tar.gz', 'archive_sha256', cpu)):
        mapping = metadata[key]
        assert all(digest(repo/p) == h for p, h in mapping.items())
        assert digest(config/filename) == metadata[sha_key]
        with tarfile.open(config/filename) as snapshot:
            assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == h for p, h in mapping.items())
    for artifact in ('realtime.elf', 'realtime.bin', 'realtime-input.dtb'):
        assert digest(config/artifact) in provenance['artifact_sha256'].values()
    inp = read(f'results/{name}/analysis-input-provenance.json')
    input_path = archive/'results'/name/'analysis-input.log'
    assert inp['decoding_valid_for_analysis'] and inp['measurement_bytes_unchanged'] and inp['raw_sha256'] == digest(raw_path)
    assert inp['analysis_input_sha256'] == digest(input_path)
    raw, data = raw_path.read_bytes(), input_path.read_bytes()
    assert raw[raw.index(b'VIRQ_MEASUREMENT '):] == data[data.index(b'VIRQ_MEASUREMENT '):]
    counter = read(f'results/{name}/counter/summary.json')
    frequency = read(f'results/{name}/frequency/summary.json')
    thermal = read(f'results/{name}/thermal/summary.json')
    stages = read(f'results/{name}/stages/summary.json')
    physical = read(f'results/{name}/physical/summary.json')
    assert stages['samples'] == counter['task_observations'] == frequency['task_observations'] == 64
    assert stages['dropped'] == stages['incomplete'] == 0
    assert not counter['effective_resolution_verified'] and not counter['physical_frequency_error_bounds_verified']
    assert counter['window_frequency_hz'] is None and not counter['M1'] and not counter['M2']
    with (archive/'results'/name/'counter/series.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    with (archive/'results'/name/'counter/frequency-sensitivity.csv').open() as stream:
        sensitivity = list(csv.DictReader(stream))
    enabled = run['frequency'] == 'enabled'
    assert counter['observations_available'] == enabled and len(rows) == (48 if enabled else 0)
    assert counter.get('raw_reads', 0) == (12288 if enabled else 0)
    assert frequency['cpu_count'] == 4 and frequency['observations_available'] == enabled
    assert thermal['observations_available'] == (run['runtime'] == 'board')
    text = input_path.read_text()
    retired = [m.start() for m in re.finditer('VIRQ_VM_GROUP_RETIRED count=2 empty=1', text)]
    exports = [m.start() for m in re.finditer('VIRQ_COUNTER_SERIES ', text)]
    assert len(retired) == 2
    if enabled:
        assert len(exports) == 48 and min(exports) > max(retired) and max(exports) < text.index('VIRQ_TRACE_FROZEN ')
        for row in rows:
            assert row['reads'] == '256' and len(json.loads(row['values'])) == 256
    if run['runtime'] == 'board':
        assert provenance['observed_platforms'] == ['orangepi5plus_rk3588']
        assert all(r['counter_hz'] == '24000000' for r in rows)
        assert 'RK3588 CPU DVFS SCMI' not in text and 'cpufreq: A55 ' not in text
        for artifact in ('host-input.dtb', 'host-boot.fit'):
            assert digest(config/artifact) in provenance['artifact_sha256'].values()
        subprocess.run(['python3', str(archive/'audit-pressure-export.py'), name], cwd=repo, check=True)
    all_rows.extend(dict(run=name, runtime=run['runtime'], **r) for r in rows)
    all_sensitivity.extend(dict(run=name, runtime=run['runtime'], **r) for r in sensitivity)
    runs.append(dict(name=name, runtime=run['runtime'], enabled=enabled, tasks=64,
                     trace_records=physical['runtime']['records'], dropped=0, incomplete=0,
                     series=len(rows), raw_reads=counter.get('raw_reads', 0), counter=counter, raw_sha256=digest(raw_path)))
for filename, rows in (('counter-series.csv', all_rows), ('counter-frequency-sensitivity.csv', all_sensitivity)):
    with (archive/'results'/filename).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
report = dict(runs=runs, accepted_boots=3, task_observations=192, series=96, raw_reads=24576,
              native_series=48, native_raw_reads=12288, cpu_core_and_host_unchanged=True,
              clippy_checks=29, python_tests=42, effective_resolution_verified=False,
              physical_frequency_error_bounds_verified=False, M1=False, M2=False,
              audit_script_sha256=digest(Path(__file__)))
(archive/'results/counter-audit.json').write_text(json.dumps(report, indent=2)+'\n')
lines = ['# EL2 架构计数连续读报告', '', '## 1. 运行与实际证据', '',
         '| 运行 | 平台 / 开启 | 有效任务 | Trace / 丢样 / 未完成 | 序列 / 原始读数 |',
         '| --- | --- | --- | --- | --- |']
for r in runs:
    lines.append(f'| {r["name"]} | {r["runtime"]} / {int(r["enabled"])} | 64 | {r["trace_records"]} / 0 / 0 | {r["series"]} / {r["raw_reads"]} |')
lines += ['', '三次完整链独立启动共 192 条任务观察。真板为 A55 四核、Linux 内存 + SGI 压力；QEMU 用于功能验证，不混合作物理时间精度证据。每种模式在每个策略 VM 创建前/退休后逐核保存 256 个原始读数；全部输出在两组 VM 退休及追踪关闭后。', '',
          '## 2. 增量观察', '', '| 平台 | 模式 | 零增量 | 逆序 | 正增量 GCD (ticks) | 正增量取值（前 16 个） |', '| --- | --- | --- | --- | --- | --- |']
for r in runs:
    if r['enabled']:
        for mode, summary in r['counter']['by_mode'].items():
            values = summary['observed_positive_ticks']
            shown = ', '.join(map(str, values[:16]))+(' …' if len(values)>16 else '')
            lines.append(f'| {r["runtime"]} | {mode} | {summary["zero_differences"]} | {summary["backwards_differences"]} | {summary["gcd_of_positive_differences"]} | {shown} |')
native_rows = [r for r in all_rows if r['runtime'] == 'board']
lines += ['', '真板逐段采集包围时间如下。每次包围含 256 个读、循环/数组存储、函数及外层计时开销，不能称为纯 MRS/ISB 成本，也不是忙碌 Guest 内的最坏读延迟。', '',
          '| 模式 | 256 读包围最小～最大 (µs) | 摊到每读的包围最小～最大 (ns) |',
          '| --- | --- | --- |']
for mode in ('physical', 'virtual', 'physical_raw'):
    times = [float(r['envelope_ns']) for r in native_rows if r['mode'] == mode]
    lines.append(f'| {mode} | {min(times)/1000:.3f}～{max(times)/1000:.3f} | {min(times)/256:.2f}～{max(times)/256:.2f} |')
native_summary = next(r['counter']['by_mode'] for r in runs if r['runtime'] == 'board')
if all(native_summary[mode]['observed_positive_ticks'] == [7] for mode in native_summary):
    lines += ['', '本次真板三种读法的正增量都只有 7 ticks，无逆序；按 24 MHz 名义尺度对应约 291.7 ns 的最小已观察正增量。无额外 ISB 的读法也重现了 0/7，说明不能只用生产读取接口中的 ISB 解释该现象。各段多次读返回同一值，零差值不表示调用零开销。硬件广播、分频/缩放与采样节奏的最终机制仍未直接读取配置验证。']
lines += ['', 'physical/virtual 使用既有生产读取接口及其读前 ISB；physical_raw 只做 MRS，不额外加 ISB，仅用于读节奏诊断。所有序列用 Host 物理时间戳包围，virtual 不假定偏移为零。完整原始值、逐核直方图和包围时间见 counter-series.csv。模式之间的差异不能直接等同纯 ISB 成本，循环、函数布局、存储与采样节奏也参与其中。', '',
          '## 3. 时间尺度与频率解释', '',
          'CNTFRQ 表示公布的计数时间尺度，不保证每次可见更新只有一个 tick。Arm Generic Timer 102379_0100_02_en 第 5 节允许减少计数广播更新次数并保持名义时间推进，见 [原始文档](https://documentation-service.arm.com/static/6294c39db334256d9ea8ae53?token=)。本轮只读计数寄存器，没有读取或修改 Secure CNTControlBase、CNTSCR、比较器、GIC 或 OPP。', '',
          '表中 GCD、最小/最大增量及零增量比例只是有限样本统计，不能据此证明唯一硬件配置、最大更新步长或绝对时钟校准。q=1 与各序列观测 GCD 的频率敏感性结果见 counter-frequency-sensitivity.csv；使用 (Δcycles−1)·CNTFRQ/(t3−t0+q) 与 (Δcycles+1)·CNTFRQ/(t2−t1−q)，均明确以 q 为假设，不作为已认证物理误差边界或窗口恒频证据。第 19 原始数据不回填新分辨率。', '',
          '## 4. 验证与剩余门', '',
          '29 项 Clippy、42 项分析测试通过。对实际分析器临时移除串行化逆序拒绝后，同一完整行为测试稳定失败，恢复原字节后通过；原始证据见 configs/counter-reversal-contract.json 与 raw/counter-reversal-*.log。缺失、重复、乱序、错误时钟/包围、u64 越界及关闭仍有数据都拒绝；raw 逆序保留为诊断，不借它宣称因果顺序。', '',
          '五文件增量 patches/counter-increments.patch 在 configs/counter-before.tar.gz 的副本隔离应用后逐字节匹配。三组冻结 Host/tests/ax-cpu/驱动与编译身份，measurement 字节未改。CPU 核心、Host 热路径、PMU 恢复、驱动、压力实现、manifest、锁文件与原 RAM 修复均未改；此前 finalize 仅描述历史检查点。', '',
          '本轮仅完成计数更新的观察与敏感性分析，不能证明未来最大更新步长、参考时钟校准、运行窗口最高温度/恒频或严格 WCET/WCRT。新配置记录器与残余握手成本、剩余阶段边界和随机重复四组仍待完成，M1/M2 保持 false。下一步按 [当前开销对照准备](../design/current-probe-cost-plan.md) 修正记录操作的范围声明并运行重复启动对。高风险共享硬件 API 的合入审查要求不变，本轮不提交或合入。', '']
(archive/'results/counter-report.md').write_text('\n'.join(lines))
print('COUNTER_AUDIT_OK boots=3 tasks=192 native_series=48 native_reads=12288 M1=0 M2=0')
