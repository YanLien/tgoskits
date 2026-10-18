#!/usr/bin/env python3
"""Audit cycle-scope proofs and actual AxVM frequency observations."""
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
plan = read('configs/frequency-check-plan.json')
state = read('results/frequency-check-status.json')
assert state['terminal'] and state['success'] and len(state['completed']) == 3
correction = read('configs/frequency-quantization-correction.json')
assert correction['success'] and correction['controller_terminal_before_edit']
assert correction['red_exit'] != 0 and correction['green_exit'] == 0
assert set(correction['sources']) == {'virtualization/axvm/tests/analysis/'+name for name in ('analyze_virq_frequency.py', 'test_virq_frequency_analysis.py')}
for p, hashes in correction['sources'].items():
    assert plan['source_sha256'][p] == hashes['before_sha256']
    assert digest(repo/p) == hashes['after_sha256']
    assert digest(archive/'configs/frequency-analysis-before'/Path(p).name) == hashes['before_sha256']
    assert digest(archive/'configs/frequency-quantized-payload'/Path(p).name) == hashes['after_sha256']
assert correction['red_log_sha256'] == digest(archive/'raw/frequency-quantization-red.log')
assert correction['green_log_sha256'] == digest(archive/'raw/frequency-analysis-final-tests.log')


def source_matches(p, h):
    if p in correction['sources']:
        return h == correction['sources'][p]['before_sha256'] and digest(repo/p) == correction['sources'][p]['after_sha256']
    return digest(repo/p) == h


assert all(source_matches(p, h) for p, h in plan['source_sha256'].items())
assert all(digest(repo/p) == h for p, h in plan['control_sha256'].items())
fix = read('results/private-ram-patch-audit.json')
assert digest(repo/fix['source']) == fix['after_sha256']
patch = read('results/frequency-cycles-patch-audit.json')
assert patch['isolated_apply_matches_live_sources'] and len(patch['changed']) == 17
assert all(digest(repo/p) == h['after_sha256'] for p, h in patch['changed'].items())
with tarfile.open(archive/'configs/frequency-before.tar.gz') as backup:
    assert hashlib.sha256(backup.extractfile('Cargo.lock').read()).hexdigest() == digest(repo/'Cargo.lock')
    for m in backup:
        if m.isfile() and m.name.startswith('virtualization/axvm/src/'):
            assert backup.extractfile(m).read() == (repo/m.name).read_bytes()
contract = read('configs/frequency-restoration-contract.json')
assert contract['success'] and contract['source_restored'] and contract['red_exit_code'] != 0 and contract['green_exit_code'] == 0
assert contract['original_sha256'] == digest(repo/'components/axcpu/src/arch/aarch64/pmu/cycle_scope.rs')
assert contract['red_log_sha256'] == digest(archive/'raw/frequency-cycle-truncation-red.log')
assert contract['green_log_sha256'] == digest(archive/'raw/frequency-cycle-restoration-green.log')
assert 'temporary scope destroyed saved state' in (archive/'raw/frequency-cycle-truncation-red.log').read_text()
for name, count in (('frequency-pmu-clippy.log', 46), ('frequency-axvm-clippy.log', 29)):
    assert f'passed checks: {count}, failed checks: 0, skipped checks: 0' in (archive/'raw'/name).read_text()
tests = (archive/'raw/frequency-analysis-final-tests.log').read_text()
assert 'Ran 41 tests' in tests and '\nOK\n' in tests
functional = []
for name, count, version in (('frequency-pmu-qemu.log', 4, 1), ('frequency-pmu-max-qemu.log', 4, 6), ('frequency-pmu-board.log', 8, 4)):
    raw_functional = (archive/'raw'/name).read_bytes()
    first_core = raw_functional.index(b'CPU_PMU_CORE ')
    # Board power-on may contain non-UTF8 firmware bytes. Validate the complete
    # program evidence strictly; never repair a core/IRQ/success marker.
    log = raw_functional[first_core:].decode('utf-8')
    prefix_replacements = raw_functional[:first_core].decode('utf-8', errors='replace').count('\ufffd')
    assert 'CPU_PMU_OK' in log
    cores = re.findall(r'CPU_PMU_CORE cpu=(\d+) midr=0x([0-9a-f]+) part=0x([0-9a-f]+) info=PmuInfo .*?version: (\d+)', log)
    # One native line is interleaved with SMP boot logging. The final success
    # marker follows all eight hardware assertions; intact lines prove 1..7.
    expected = set(range(count)) if name != 'frequency-pmu-board.log' else set(range(1, count))
    assert expected <= {int(r[0]) for r in cores}
    assert all(int(r[3]) == version for r in cores)
    assert {int(n) for n in re.findall(r'CPU_PMU_IRQ cpu=(\d+) count=2 ', log)} == set(range(count))
    assert ('all arceos board test groups passed' if count == 8 else 'result: 1/1 case(s) passed') in log
    functional.append(dict(log=name, cpus=count, pmuver=version, sha256=digest(archive/'raw'/name),
                           program_region_utf8_valid=True, boot_prefix_replacement_characters=prefix_replacements))
with tarfile.open(archive/'configs/frequency-pmu-functional/sources.tar.gz') as snapshot:
    for m in snapshot:
        if m.isfile():
            assert snapshot.extractfile(m).read() == (repo/m.name).read_bytes()
runs, all_samples = [], []
reference = None
for run in plan['runs']:
    name = run['name']
    config = archive/'configs'/name
    provenance = read(f'configs/{name}/provenance.json')
    extra = read(f'configs/{name}/driver-source-provenance.json')
    cpu = read(f'configs/{name}/cpu-source-provenance.json')
    raw_path = archive/'raw'/(name+'.log')
    assert digest(raw_path) == provenance['raw_log_sha256'] and provenance['exit_code'] == 0 and provenance['suite_passed']
    assert provenance['capture_script_sha256'] == digest(archive/'capture-periodic.py')
    assert extra['capture_script_sha256'] == digest(archive/'capture-thermal-driver.py')
    assert cpu['capture_script_sha256'] == digest(archive/'capture-frequency-cpu.py')
    assert provenance['cargo_lock_sha256'] == digest(repo/'Cargo.lock')
    current = dict(tests=provenance['source_sha256'], host=provenance['host_source_sha256'], driver=extra['source_sha256'], cpu=cpu['source_sha256'],
                   git_commit=provenance['git_commit'], tracked_diff_sha256=digest(config/'tracked-worktree-before.patch'),
                   git_status_sha256=digest(config/'status-before.txt'))
    if reference is None:
        reference = current
    else:
        assert current == reference
    for key, filename, sha_key, metadata in (
        ('source_sha256', 'sources.tar.gz', 'source_archive_sha256', provenance),
        ('host_source_sha256', 'host-sources.tar.gz', 'host_source_archive_sha256', provenance),
        ('source_sha256', 'driver-sources.tar.gz', 'archive_sha256', extra),
        ('source_sha256', 'cpu-sources.tar.gz', 'archive_sha256', cpu)):
        mapping = metadata[key]
        assert all(source_matches(p, h) for p, h in mapping.items())
        assert digest(config/filename) == metadata[sha_key]
        with tarfile.open(config/filename) as snapshot:
            assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == h for p, h in mapping.items())
    for artifact in ('realtime.elf', 'realtime.bin', 'realtime-input.dtb'):
        assert digest(config/artifact) in provenance['artifact_sha256'].values()
    inp = read(f'results/{name}/analysis-input-provenance.json')
    input_path = archive/'results'/name/'analysis-input.log'
    assert inp['decoding_valid_for_analysis'] and inp['measurement_bytes_unchanged'] and inp['raw_sha256'] == digest(raw_path)
    assert inp['analysis_input_sha256'] == digest(input_path)
    raw, measured = raw_path.read_bytes(), input_path.read_bytes()
    assert raw[raw.index(b'VIRQ_MEASUREMENT '):] == measured[measured.index(b'VIRQ_MEASUREMENT '):]
    frequency = read(f'results/{name}/frequency/summary.json')
    thermal = read(f'results/{name}/thermal/summary.json')
    stages = read(f'results/{name}/stages/summary.json')
    physical = read(f'results/{name}/physical/summary.json')
    assert stages['samples'] == frequency['task_observations'] == 64 and stages['dropped'] == stages['incomplete'] == 0
    assert frequency['window_frequency_hz'] is None and not frequency['continuous_coverage'] and not frequency['M1'] and not frequency['M2']
    assert frequency['timestamp_quantum_ticks'] == frequency['cycle_quantum'] == 1
    for subdir, identity in (('frequency-before-quantization', 'old_outputs'), ('frequency', 'new_outputs')):
        assert all(digest(archive/'results'/name/subdir/p) == h for p, h in correction[identity][name].items())
    with (archive/'results'/name/'frequency/samples.csv').open() as stream:
        samples = list(csv.DictReader(stream))
    with (archive/'results'/name/'thermal/samples.csv').open() as stream:
        temperatures = list(csv.DictReader(stream))
    enabled = run['frequency'] == 'enabled'
    assert frequency['observations_available'] == enabled and len(samples) == (16 if enabled else 0)
    assert frequency['cpu_count'] == 4
    assert thermal['observations_available'] == (run['runtime'] == 'board') and len(temperatures) == (4 if run['runtime'] == 'board' else 0)
    text = input_path.read_text()
    retired = [m.start() for m in re.finditer('VIRQ_VM_GROUP_RETIRED count=2 empty=1', text)]
    exports = [m.start() for m in re.finditer('VIRQ_FREQUENCY_SAMPLE ', text)]
    assert len(retired) == 2
    if enabled:
        assert len(exports) == 16 and min(exports) > max(retired)
        assert max(exports) < text.index('VIRQ_TRACE_FROZEN ')
    if run['runtime'] == 'board':
        assert provenance['observed_platforms'] == ['orangepi5plus_rk3588']
        assert all(r['counter_hz'] == '24000000' and r['pmuver'] == '4' and ((int(r['midr']) >> 4) & 0xfff) == 0xd05 for r in samples)
        assert 'RK3588 CPU DVFS SCMI' not in text and 'cpufreq: A55 ' not in text
        for artifact in ('host-input.dtb', 'host-boot.fit'):
            assert digest(config/artifact) in provenance['artifact_sha256'].values()
        subprocess.run(['python3', str(archive/'audit-pressure-export.py'), name], cwd=repo, check=True)
    all_samples.extend(dict(run=name, runtime=run['runtime'], **s) for s in samples)
    runs.append(dict(name=name, runtime=run['runtime'], frequency_enabled=enabled, tasks=64,
                     trace_records=physical['runtime']['records'], dropped=0, incomplete=0,
                     snapshots=len(samples), temperatures=temperatures, raw_sha256=digest(raw_path)))
with (archive/'results/frequency-snapshots.csv').open('w', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=list(all_samples[0]))
    writer.writeheader()
    writer.writerows(all_samples)
report = dict(runs=runs, functional=functional, accepted_boots=3, task_observations=192,
              frequency_snapshots=32, native_frequency_snapshots=16, thermal_snapshots=4,
              source_identity_verified=True, private_ram_fix_unchanged=True, clippy_checks=75,
              python_tests=41, window_frequency_hz=None, continuous_frequency_coverage=False,
              analysis_revised_after_sampling=True, original_analysis_outputs_retained=True,
              reference_resolution_verified=False, physical_frequency_error_bounds_verified=False,
              observed_native_positive_bracket_differences_ticks=sorted({int(s[b])-int(s[a])
                  for s in all_samples if s['runtime']=='board' for a,b in (('t0','t1'),('t2','t3'))
                  if int(s[b])>int(s[a])}),
              M1=False, M2=False, audit_script_sha256=digest(Path(__file__)))
(archive/'results/frequency-audit.json').write_text(json.dumps(report, indent=2)+'\n')
lines = ['# PMU 频率快照验证报告', '', '## 1. 实际运行', '',
         '| 运行 | 平台 / 测频 | 有效任务 | Trace / 丢样 / 未完成 | 频率快照 |',
         '| --- | --- | --- | --- | --- |']
for r in runs:
    lines.append(f'| {r["name"]} | {r["runtime"]} / {int(r["frequency_enabled"])} | 64 | {r["trace_records"]} / 0 / 0 | {r["snapshots"]} |')
lines += ['', '三次独立启动共 192 条任务观察，完整链、周期、Linux 围栏与 IRQ 分段验收通过。真板为 A55 四核，Linux 内存 + SGI 压力；QEMU 只作功能验证，不混合推断物理频率或干扰。', '',
          '## 2. 真板逐核频率区间', '', '| 策略 | 采样点 | CPU | 单 tick 分辨率假设下的频率计算区间 (MHz) |', '| --- | --- | --- | --- |']
for s in all_samples:
    if s['runtime'] == 'board':
        lines.append(f'| {s["policy"]} | {s["point"]} | {s["cpu"]} | {float(s["frequency_lower_hz"])/1e6:.3f}～{float(s["frequency_upper_hz"])/1e6:.3f} |')
lines += ['', '每个策略的 VM 创建前、全部退休后逐核忙运行约 2 ms。两个周期读分别被 t0/t1 与 t2/t3 时间戳包围；假设一个参考 tick 与一个周期的整数粒度，下界计算为 (Δcycles−1)·CNTFRQ/(t3−t0+1)，上界为 (Δcycles+1)·CNTFRQ/(t2−t1−1)。这依赖公布的参考频率与尚待验证的单 tick 有效分辨率，不覆盖参考时钟校准误差。区间是该假设下的计算结果，不是已验证的物理频率误差边界或统计置信区间；不证明窗口恒频、运行中频率或最大能力。24 MHz 仅是计时尺度。完整原始数值见 frequency-snapshots.csv。', '',
          '进一步检查发现，真板这 32 对紧邻包围时间戳的正差值全部为 7 ticks，其余为 0。这不足以单独证明硬件有效分辨率恰为 7 ticks，却使单 tick 粒度假设缺乏板上验证。因此当前只将约 816 MHz 报为名义参考下的 PMU 快照估计，不把表中细小边界视为完整精度保证。下一步须独立测量连续计数读的增量分布，并核对计数器更新与校准语义，再修订误差模型。M1/M2 均未升级。', '',
          '测频局部屏蔽 IRQ 且忙运行，会预热核心并可能影响固件策略。温度在每组逐核测频前查询；4 个 SoC/A55 簇快照不代表窗口内最高温度。没有请求 OPP，也没有修改 SCMI/MDCR；独立 TSADC 初始化沿用已有 CRU/保护设置及其 PPLL 限制。', '',
          '## 3. 所有权、恢复与验证', '',
          '唯一 PMU 会话内借用周期计数器，只允许已核对的版本 1/4/5/6；硬件非空闲即拒绝，回调不执行。回调只读，私有守卫恢复完整 64 位周期值、过滤器、原周期溢出位与控制，不复位全部 PMU。counter/IRQ/user/global 占用无写入拒绝以及回调返回错误的恢复由现有真实 PMU 系统用例覆盖。Host PMCR 本来就会保存恢复，本轮没有修复所谓 Host PMCR 遗失问题。', '',
          '75 项 Clippy 和 41 项分析测试通过。PMU 功能用例在四核 Cortex-A53 QEMU（版本 1）、四核 max QEMU（版本 6）及八核真板（版本 4）通过；八核用例是独立的寄存器功能证明，不改变论文实验的四核配置。原始板卡第 0 核文本被 SMP 启动日志交错，未修复原始字节；最终 CPU_PMU_OK 位于八核断言之后，完整的第 1～7 核与八核 IRQ 行保留。该日志开机前缀含非 UTF-8 字节，首次审计全文件解码失败并保留日志；现在只对首条 CPU_PMU_CORE 起的完整程序证据严格解码，前缀替换数单列，原始字节不改。较新未支持版本只有入口拒绝规则，当前 QEMU 不提供其实际运行证据。', '',
          '短暂把恢复写成低 32 位时，同一正式 QEMU 用例确定性报 temporary scope destroyed saved state 并失败；finally 恢复完全相同源码字节后原用例通过。期间没有其他构建或实验。证据为 configs/frequency-restoration-contract.json 和 raw/frequency-cycle-*.log。分析套件首次失败来自测试输入的替换字符串未命中，已修正输入并保留 frequency-analysis-fixture-failed.log，没有放宽验收规则。', '',
          '真板出现同 tick 包围端点后，发现初版分析没有把整数计数粒度向外计入。全部原计划结束、来源检查完成后才修改两个分析文件：增强同一测试使旧公式确定性失败，再修正计算并通过 41 项测试，最后对三组原始数据重算。原分析源码和旧数值输出保留为 configs/frequency-analysis-before 与各组 frequency-before-quantization；它们已被替代，不用作最终边界。原计划不改，差异映射为 configs/frequency-quantization-correction.json；运行源码、原始日志和 measurement 字节未改。', '',
          '17 文件增量补丁已在修改前完整副本隔离应用并逐字节匹配；每次 AxVM 启动冻结 Host/tests/ax-cpu/驱动、feature、锁文件和实际 Guest/Host 构建产物。原始测量字节不改，频率值在两组 VM 退休和追踪关闭后才批量输出；默认关闭时保留不可用，不补零。原 RAM 修复及 Host 热路径实现不变。', '',
          '## 4. 剩余门', '',
          '仍须补窗口内环境覆盖、新版本记录器及残余握手开销、其余 T0～T6 边界、EL3 固件逐次身份，以及随机重复 E0/E1/E2/E3 和运行级交互项不确定性。当前快照只补部分频率证据，M1/M2 继续 false；没有耦合、联合优化收益或严格 WCET/WCRT 结论。高风险共享硬件 API 合入前仍需合格领域审查，本轮不提交或合入。', '']
(archive/'results/frequency-report.md').write_text('\n'.join(lines))
print('FREQUENCY_AUDIT_OK boots=3 tasks=192 native_snapshots=16 M1=0 M2=0')
