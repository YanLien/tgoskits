#!/usr/bin/env python3
"""Audit independent thermal observation, preserved failure evidence and source identity."""
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tomllib

archive=Path(__file__).resolve().parent
repo=archive.parent.parent
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads((archive/p).read_text())
plan=read('configs/thermal-check-plan.json')
recovery=read('configs/thermal-recovery-plan.json')
state=read('results/thermal-recovery-status.json')
old=read('results/thermal-check-status.json')
assert old['terminal'] and not old['success'] and old['active_run']=='thermal-qemu-unavailable-32'
assert state['terminal'] and state['success'] and len(state['completed'])==3
assert plan['source_sha256']==recovery['source_sha256']
for selected in (plan,recovery):
    assert all(digest(repo/p)==h for p,h in selected['source_sha256'].items())
    assert all(digest(repo/p)==h for p,h in selected['control_sha256'].items())
fix=read('results/private-ram-patch-audit.json')
assert digest(repo/fix['source'])==fix['after_sha256']
patch=read('results/independent-thermal-patch-audit.json')
assert patch['isolated_apply_matches_live_sources'] and len(patch['changed'])==16
assert all(digest(repo/p)==h['after_sha256'] for p,h in patch['changed'].items())
with tarfile.open(archive/'configs/thermal-before-complete.tar.gz') as backup:
    assert hashlib.sha256(backup.extractfile('Cargo.lock').read()).hexdigest()==digest(repo/'Cargo.lock')
completion=read('configs/thermal-before-completion.json')
assert completion['complete_archive_sha256']==digest(archive/'configs/thermal-before-complete.tar.gz')
assert completion['original_archive_sha256']==digest(archive/'configs/thermal-before.tar.gz')
std=read('configs/thermal-std-snapshot.json')
assert std['main_sources_unchanged'] and std['red_exit']!=0 and std['green_exit']==0
assert all(digest(repo/p)==h for p,h in std['source_sha256'].items())
assert digest(repo/'scripts/test/std_crates.csv')==std['original_main_whitelist_sha256']
assert digest(repo/'scripts/axbuild/src/test/std.rs')==std['formal_runner_sha256']
assert std['red_log_sha256']==digest(archive/'raw/thermal-readonly-mutant-red.log')
assert std['green_log_sha256']==digest(archive/'raw/thermal-std-tests-green.log')
red=(archive/'raw/thermal-readonly-mutant-red.log').read_text()
green=(archive/'raw/thermal-std-tests-green.log').read_text()
assert 'queries must never tighten thresholds' in red and 'failed: ax-driver' in red
assert 'running 4 std test profile(s) for ax-driver' in green and 'all std tests passed' in green
assert 'test soc::rockchip::thermal::tests::rk3588_tsadc_thresholds_and_invalid_samples ... ok' in green
assert 'passed checks: 93, failed checks: 0, skipped checks: 0' in (archive/'raw/thermal-clippy.log').read_text()
python=(archive/'raw/thermal-python-tests.log').read_text()
assert 'Ran 40 tests' in python and '\nOK\n' in python
# Feature graph and unchanged dependencies bound the no-OPP claim.
driver=tomllib.loads((repo/'drivers/ax-driver/Cargo.toml').read_text())
vm=tomllib.loads((repo/'virtualization/axvm/Cargo.toml').read_text())
assert driver['features']['rk3588-thermal']==['rockchip-soc']
assert 'rk3588-thermal' in driver['features']['rk3588-cpufreq']
assert vm['features']['axtest-thermal']==['axtest','ax-driver/rk3588-thermal']
dependencies=read('configs/thermal-dependency-source-sha256.json')
assert dependencies['unchanged_relative_to_HEAD']
assert all(digest(repo/p)==h for p,h in dependencies['source_sha256'].items())
subprocess.run(['python3',str(archive/'verify-thermal-negative.py')],cwd=repo,check=True)
negative=read('results/thermal-negative-audit.json')
assert negative['expected_admission_rejection'] and not negative['measurement_accepted']
runs=[];reference=None
for run in plan['runs']:
    name=run['name'];config=archive/'configs'/name
    provenance=read(f'configs/{name}/provenance.json')
    extra=read(f'configs/{name}/driver-source-provenance.json')
    raw_path=archive/'raw'/(name+'.log')
    assert digest(raw_path)==provenance['raw_log_sha256']
    assert provenance['capture_script_sha256']==digest(archive/'capture-periodic.py')
    assert extra['capture_script_sha256']==digest(archive/'capture-thermal-driver.py')
    assert provenance['cargo_lock_sha256']==digest(repo/'Cargo.lock')
    current={key:provenance[key] for key in ('source_sha256','host_source_sha256')}
    current['driver_source_sha256']=extra['source_sha256']
    if reference is None: reference=current
    else: assert current==reference
    for source_key,filename,sha_key,metadata in (
        ('source_sha256','sources.tar.gz','source_archive_sha256',provenance),
        ('host_source_sha256','host-sources.tar.gz','host_source_archive_sha256',provenance),
        ('source_sha256','driver-sources.tar.gz','archive_sha256',extra)):
        source_map=metadata[source_key]
        assert all(digest(repo/p)==h for p,h in source_map.items())
        assert digest(config/filename)==metadata[sha_key]
        with tarfile.open(config/filename) as snapshot:
            assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest()==h for p,h in source_map.items())
    if run.get('expected_rejection'):
        assert provenance['exit_code']==1 and negative['task_observations']==0
        runs.append(dict(name=name,runtime='qemu',thermal_enabled=True,measurement_accepted=False,
                         expected_rejection=True,task_observations=0,snapshots=0,raw_sha256=digest(raw_path)))
        continue
    assert provenance['exit_code']==0 and provenance['suite_passed']
    for artifact in ('realtime.elf','realtime.bin','realtime-input.dtb'):
        assert digest(config/artifact) in provenance['artifact_sha256'].values()
    inp=read(f'results/{name}/analysis-input-provenance.json')
    assert inp['decoding_valid_for_analysis'] and inp['measurement_bytes_unchanged'] and inp['raw_sha256']==digest(raw_path)
    input_path=archive/'results'/name/'analysis-input.log'
    assert inp['analysis_input_sha256']==digest(input_path)
    raw,input_bytes=raw_path.read_bytes(),input_path.read_bytes()
    assert raw[raw.index(b'VIRQ_MEASUREMENT '):]==input_bytes[input_bytes.index(b'VIRQ_MEASUREMENT '):]
    thermal=read(f'results/{name}/thermal/summary.json')
    stages=read(f'results/{name}/stages/summary.json')
    physical=read(f'results/{name}/physical/summary.json')
    assert thermal['task_observations']==64 and stages['samples']==64
    assert stages['dropped']==stages['incomplete']==0
    assert thermal['cpu_frequency_hz'] is None and thermal['window_maximum_mc'] is None
    assert not thermal['M1'] and not thermal['M2']
    with (archive/'results'/name/'task/samples.csv').open() as stream:
        assert len(list(csv.DictReader(stream)))==64
    with (archive/'results'/name/'thermal/samples.csv').open() as stream:
        samples=list(csv.DictReader(stream))
    enabled=run['thermal']=='enabled'
    assert thermal['observations_available']==enabled and len(samples)==(4 if enabled else 0)
    if enabled:
        assert provenance['observed_platforms']==['orangepi5plus_rk3588']
        assert all(r['frequency_hz']=='24000000' for r in samples)
        text=input_path.read_text()
        retired=[m.start() for m in re.finditer('VIRQ_VM_GROUP_RETIRED count=2 empty=1',text)]
        exports=[m.start() for m in re.finditer('VIRQ_THERMAL_SAMPLE ',text)]
        assert len(retired)==2 and len(exports)==4 and min(exports)>max(retired)
        assert 'RK3588 TSADC sampling with verified <=120 C hardware shutdown on all channels' in text
        assert 'RK3588 CPU DVFS SCMI' not in text and 'cpufreq: A55 ' not in text
        assert digest(config/'host-input.dtb') in provenance['artifact_sha256'].values()
        assert digest(config/'host-boot.fit') in provenance['artifact_sha256'].values()
        subprocess.run(['python3',str(archive/'audit-pressure-export.py'),name],cwd=repo,check=True)
    else:
        assert thermal['temperature_mc'] is None
    runs.append(dict(name=name,runtime=run['runtime'],thermal_enabled=enabled,measurement_accepted=True,
                     task_observations=64,stage_observations=64,trace_records=physical['runtime']['records'],
                     dropped=0,incomplete=0,snapshots=len(samples),thermal=thermal,samples=samples,
                     raw_sha256=digest(raw_path)))
report=dict(runs=runs,accepted_boots=2,expected_rejected_boots=1,task_observations=128,
            thermal_snapshots=4,individual_sensor_readings=8,source_identity_verified=True,
            private_ram_fix_unchanged=True,formal_std_profiles=4,clippy_checks=93,python_tests=40,
            cpu_frequency_hz=None,window_maximum_temperature_mc=None,M1=False,M2=False,
            audit_script_sha256=digest(Path(__file__)))
(archive/'results/thermal-audit.json').write_text(json.dumps(report,indent=2)+'\n')
lines=['# 独立温度观测验证报告','','## 1. 功能与实际样本','','| 运行 | 平台/温度 feature | 结果 | 有效任务 / 温度快照 | Trace / 丢样 / 未完成 |','| --- | --- | --- | --- | --- |']
for r in runs:
    outcome='通过' if r['measurement_accepted'] else '测量前按预期拒绝'
    trace=f"{r['trace_records']} / 0 / 0" if r['measurement_accepted'] else '无有效任务数据'
    lines.append(f"| {r['name']} | {r['runtime']} / {'开启' if r['thermal_enabled'] else '关闭'} | {outcome} | {r['task_observations']} / {r['snapshots']} | {trace} |")
lines+=['','本轮 2 次有效独立启动共 128 条任务观察；另 1 次 QEMU 无 TSADC 的预期拒绝为 0 条有效数据。真板在 Linux 内存压力 + SGI 下运行，默认 QEMU 仅回归功能。两者不混合作硬件性能比较。','','## 2. 真板温度与采样边界','','| 策略 | 采样点 | SoC (°C) | A55 簇 (°C) | 两次查询包围耗时 (µs) |','| --- | --- | --- | --- | --- |']
for r in runs:
    for sample in r.get('samples',[]):
        lines.append(f"| {sample['policy']} | {sample['point']} | {int(sample['soc_mc'])/1000:.3f} | {int(sample['little_mc'])/1000:.3f} | {float(sample['query_pair_envelope_ns'])/1000:.3f} |")
lines+=['','SoC 为 TSADC 通道 0，A55 簇为通道 3；不是逻辑 CPU/vCPU 编号。采用既有四点表插值，毫摄氏度是整数表示单位，不代表 0.001°C 的测量准确度。四个采样点在各策略 VM 创建前/全部退休后，输出晚于两组 VM 退休；关键任务窗口与快照时钟顺序经严格校验。查询包围值包含计时和可能抢占，不能称纯查询成本。','','这些快照不提供窗口最大温度，也不证明窗口内恒温、固定 CPU 频率或 CPU 已限频。24 MHz 仅为时间戳尺度。关闭温度 feature 的 QEMU 结果保留 temperature=null，不补零或旧值。','','## 3. 驱动与验证证据','','rk3588-thermal 复用唯一 TSADC 探测、永久映射与热保护逻辑，CPU 调频继续包含该 feature；OTP/PVTM/regulator/OPP/governor 不因单独测温启用。运行时公共查询只读，原调频 refresh 的收紧阈值行为保留在原 feature。冷启动仍有 CRU/TSADC 初始化写入，继承的 CRU 核心可能归一化 PPLL，因此该配置不是整机完全被动插件，不能回填旧实验或直接沿用旧成本。','','93 项 Clippy、40 项 Python 分析测试通过。隔离的当前源码副本仅将自己的 std 允许列表限定 ax-driver，再运行未修改的 cargo xtask test 四个正式 profile；主树清单未改。插入“查询写寄存器”的隔离变异稳定失败，恢复后同一套件通过。此纯寄存器规则测试不替代真板，亦未执行 CPU 升降频硬件测试。相关证据见 configs/thermal-std-snapshot.json、raw/thermal-readonly-mutant-red.log、raw/thermal-std-tests-green.log。','','QEMU 无传感器时在创建 VM 前返回明确不可用错误，未采到任务。原控制器因 runner 诊断插入行分割错误文本而停止；原计划、终态和原始字节保留。恢复脚本只在失败诊断内严格核对那一条固定插入行，不改原始字节、不修补或接纳性能数据；之后仅执行尚未运行的两组。证据为 results/thermal-negative-audit.json 和 configs/thermal-recovery-plan.json。','','本轮增量 patches/independent-thermal.patch 共 16 文件，在完整修改前副本隔离应用后与实时源码逐文件一致；新增驱动模块已覆盖。原基线归档未改，完整基线补入的唯一 axvm manifest 来源经去掉本轮 feature 行后与 HEAD 逐字节核实，见 configs/thermal-before-completion.json。所有运行冻结 Host/tests/驱动、feature manifest、锁文件、实际镜像/DTB/真板 FIT 与原始日志，审计见 results/thermal-audit.json。原生产 RAM 修复保持原 SHA。','','## 4. 剩余测量门','','CPU 实际频率仍未测得：当前 Guest 系统上下文会保存/恢复 PMCR_EL0，不能把跨 VM 窗口的计数差直接解释为送达频率；本轮不写 PMU、不强制 OPP。EL3 固件逐次身份、窗口内环境覆盖、新版本记录器与残余握手成本、剩余 T0～T6 边界和随机重复四组仍须补齐。M1/M2 为 false，无稳定交互、优化收益或 WCET/WCRT 结论。高风险共享驱动改动在合入前仍需独立领域设计审查；本轮不提交或合入。','']
(archive/'results/thermal-report.md').write_text('\n'.join(lines))
print('THERMAL_AUDIT_OK accepted_boots=2 expected_rejected_boots=1 tasks=128 snapshots=4 M1=0 M2=0')
