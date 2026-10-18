#!/usr/bin/env python3
"""Audit frozen source identity and actual stage observations; render a bounded report."""
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path
import tarfile
import tomllib

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads((archive/p).read_text())
plan = read('configs/irq-stage-check-plan.json')
state = read('results/irq-stage-check-status.json')
assert state['terminal'] and not state['success'] and state['completed'] == ['irq-stages-board-memory-sgi-32']
recovery=read('configs/irq-stage-recovery-plan.json')
recovered=read('results/irq-stage-recovery-status.json')
assert recovered['terminal'] and recovered['success'] and len(recovered['completed']) == 2
assert recovery['host_source_sha256'] == plan['host_source_sha256']
assert recovery['source_sha256'] == dict(plan['source_sha256'], **recovery['source_additions'])
assert set(recovery['source_additions']) == {'virtualization/axvm/tests/vcpu-runtime/irq-stages/host-initramfs.toml'}
assert all(digest(repo/p) == h for p,h in recovery['controls'].items())
failed=read('configs/irq-stages-qemu-lower-32/provenance.json')
failed_raw=archive/'raw/irq-stages-qemu-lower-32.log'
assert failed['exit_code'] == 1 and digest(failed_raw) == failed['raw_log_sha256']
assert b'VIRQ_MEASUREMENT ' not in failed_raw.read_bytes() and b'AXVM_TEST_FAILED' in failed_raw.read_bytes()
assert all(digest(repo/p) == h for p,h in plan['controls'].items())
fix = read('results/private-ram-patch-audit.json')
assert digest(repo/fix['source']) == fix['after_sha256']
patch = read('results/irq-stages-patch-audit.json')
assert patch['isolated_apply_matches_live_sources']
assert all(digest(repo/p) == h['after_sha256'] for p,h in patch['changed'].items())
runs = []
names = ['irq-stages-qemu-current-32']+state['completed']+[r['name'] for r in recovery['runs']]
new_names={r['name'] for r in recovery['runs']}
for name in names:
    provenance = read(f'configs/{name}/provenance.json')
    assert provenance['exit_code'] == 0 and provenance['suite_passed']
    assert provenance['capture_script_sha256'] == digest(archive/'capture-periodic.py')
    for artifact in ('realtime.elf','realtime.bin','realtime-input.dtb'):
        assert digest(archive/'configs'/name/artifact) in provenance['artifact_sha256'].values()
    for key, filename, sha_key in (('source_sha256','sources.tar.gz','source_archive_sha256'),
                                   ('host_source_sha256','host-sources.tar.gz','host_source_archive_sha256')):
        assert provenance[key] == (recovery if name in new_names else plan)[key]
        assert all(digest(repo/p) == h for p,h in provenance[key].items())
        path = archive/'configs'/name/filename
        assert digest(path) == provenance[sha_key]
        with tarfile.open(path) as snapshot:
            assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == h for p,h in provenance[key].items())
    assert provenance['cargo_lock_sha256'] == plan['cargo_lock_sha256'] == digest(repo/'Cargo.lock')
    raw = archive/'raw'/(name+'.log')
    assert digest(raw) == provenance['raw_log_sha256']
    input_provenance = read(f'results/{name}/analysis-input-provenance.json')
    assert input_provenance['decoding_valid_for_analysis'] and input_provenance['measurement_bytes_unchanged']
    assert input_provenance['raw_sha256'] == digest(raw)
    analysis_input = archive/'results'/name/'analysis-input.log'
    assert digest(analysis_input) == input_provenance['analysis_input_sha256']
    raw_bytes, input_bytes = raw.read_bytes(), analysis_input.read_bytes()
    assert raw_bytes[raw_bytes.index(b'VIRQ_MEASUREMENT '):] == input_bytes[input_bytes.index(b'VIRQ_MEASUREMENT '):]
    config = tomllib.loads((archive/'configs'/name/'measurement.toml').read_text())
    assert config['samples'] == 32 and config['source'] == 'physical_timer_ppi' and config['task_enabled']
    off = config['recording'] == 'off'
    with (archive/'results'/name/('probe_cost' if off else 'task')/'samples.csv').open() as stream:
        assert len(list(csv.DictReader(stream))) == 64
    if off:
        summary = read(f'results/{name}/probe_cost/summary.json')
        assert not summary['complete_chain_accepted'] and summary['recording_mode'] == 'off'
        assert b'VIRQ_RUNTIME_SUMMARY' not in raw_bytes
        assert (archive/'results'/name/'stages-rejection.log').is_file()
        run = dict(name=name,runtime=provenance['runtime'],recording='off',task_observations=64,
                   stage_observations=0,stage_latency=None,complete_chain_accepted=False)
    else:
        summary = read(f'results/{name}/stages/summary.json')
        physical = read(f'results/{name}/physical/summary.json')
        task = read(f'results/{name}/task/summary.json')
        assert summary['samples'] == 64 and summary['dropped'] == summary['incomplete'] == 0
        assert not summary['M1'] and not summary['M2'] and not summary['new_probe_cost_quantified']
        assert all(p['samples'] == 32 for p in summary['policies'].values())
        with (archive/'results'/name/'stages/samples.csv').open() as stream:
            stage_rows=list(csv.DictReader(stream))
        assert len(stage_rows) == 64
        for policy,group in summary['policies'].items():
            group['by_entry_context']={}
            for origin in group['contexts']:
                selected=[r for r in stage_rows if r['policy']==policy and r['irq_entry_context']==origin]
                assert len(selected) == group['contexts'][origin]
                intervals={}
                for field in ('entry_to_dispatch_begin_ns','dispatch_ns','timer_sync_ns','timer_end_to_dispatch_begin_ns'):
                    values=sorted(float(r[field]) for r in selected if r[field] != '')
                    intervals[field]=dict(median=statistics.median(values),p99=values[math.ceil(.99*len(values))-1]) if values else None
                group['by_entry_context'][origin]=dict(samples=len(selected),intervals_ns=intervals)
        if config['irq_context'] == 'guest_running':
            assert config['irq_context'] == 'guest_running' and config['period_us'] == 0 and config['scenario'] == 'baseline'
            assert all(p['contexts'].get('lower_el_pre_iar',0) > 0 for p in summary['policies'].values())
        else:
            assert config['irq_context'] == 'current_el' and config['period_us'] == 20000
            assert all(p['intervals_ns']['timer_sync_ns'] is None for p in summary['policies'].values())
            assert task['linux_fences']['mode'] == 'serial'
        if provenance['runtime'] == 'board':
            assert provenance['observed_platforms'] == ['orangepi5plus_rk3588']
            assert config['scenario'] == 'linux_memory' and config['irq_pressure'] == 'sgi'
            assert all(p['clock']['frequency_hz'] == 24_000_000 for p in physical['policies'].values())
            assert (archive/'configs'/name/'host-input.dtb').is_file() and (archive/'configs'/name/'host-boot.fit').is_file()
        run = dict(name=name,runtime=provenance['runtime'],recording='on',task_observations=64,
                   stage_observations=64,trace_records=physical['runtime']['records'],dropped=0,incomplete=0,
                   policies=summary['policies'])
    run['raw_sha256'] = digest(raw)
    run['scenario'] = config['scenario']
    run['irq_context'] = config['irq_context']
    runs.append(run)
assert 'FAILED (failures=1)' in (archive/'raw/irq-stage-contract-red.log').read_text()
assert 'Ran 39 tests' in (archive/'raw/irq-stages-python-tests.log').read_text()
assert '\nOK\n' in (archive/'raw/irq-stages-python-tests.log').read_text()
assert 'passed checks: 21, failed checks: 0, skipped checks: 0' in (archive/'raw/irq-stages-clippy.log').read_text()
report = dict(runs=runs,instrumentation_identity_verified=True,test_configuration_additions=recovery['source_additions'],frozen_artifacts_verified=True,private_ram_fix_unchanged=True,
              stage_observations=192,task_observations=256,independent_accepted_boots=4,failed_boots=1,failed_run='irq-stages-qemu-lower-32',
              M1=False,M2=False,new_probe_cost_quantified=False,
              scope='Directed functional checks across different topologies; not interference or cost estimates',
              audit_script_sha256=digest(Path(__file__)))
(archive/'results/irq-stages-audit.json').write_text(json.dumps(report,indent=2)+'\n')
lines = ['# IRQ 分段观测验证报告','','## 1. 实际验证','','四次独立 Host 启动共 256 条任务观察，其中 192 条具有新分段，64 条关闭记录。以下不同拓扑只验证各自路径，不混合作效应估计。','','| 运行 | 平台/配置 | 任务/分段 | Trace / dropped / incomplete |','| --- | --- | --- | --- |']
for run in runs:
    trace = f"{run['trace_records']} / 0 / 0" if run['recording']=='on' else '无阶段记录（不是零时延）'
    lines.append(f"| {run['name']} | {run['runtime']} / {run['scenario']} / {run['irq_context']} | {run['task_observations']} / {run['stage_observations']} | {trace} |")
lines += ['','## 2. 已测阶段与观测结果','','同一 CPU/INTID/T0 ticks 严格关联路由 begin/end，低 EL 另有关联的 synchronize_timer begin/end。每个物理样本均有唯一 IrqKick 位于自己的路由区间；当前 EL 的 timer_sync 为 null。IRQ、VGIC、计时器、错误传播与退休顺序保持原路径。','','| 运行/策略 | 路由中位数 / P99 (µs) | 低 EL timer_sync 中位数 (µs) | 路由结束相对 ISR（该策略全体） |','| --- | --- | --- | --- |']
for run in runs:
    for policy,group in run.get('policies',{}).items():
        for origin,part in group['by_entry_context'].items():
            route=part['intervals_ns']['dispatch_ns'];timer=part['intervals_ns']['timer_sync_ns']
            timer_text=f"{timer['median']/1000:.3f}" if timer else 'null'
            label=f"{run['name']} / {policy} / {origin} (n={part['samples']})"
            lines.append(f"| {label} | {route['median']/1000:.3f} / {route['p99']/1000:.3f} | {timer_text} | {json.dumps(group['dispatch_end_vs_isr'],ensure_ascii=False)} |")
lines += ['','这些是有插桩的描述性分布。表中按真实入口来源分层；Guest-running 的 Fair 有 31 条低 EL 与 1 条当前 EL，FIFO 有 32 条低 EL，不把混合来源当作纯低 EL。每组每策略仅 32 条，P99 接近最大次序统计量，不建立尾部保证或 WCET/WCRT。跨核 Ready/Running/ISR 可以与路由重叠，各段不能机械相加。低 EL 的 timer 与 route 间隙包含 VGIC 保存等适配工作，不能单独归因。','','## 3. 证据与限制','','39 项分析测试、21 项 Clippy 及全部适用的物理 IRQ/任务/周期/围栏/压力分析通过。原 physical 拒绝测试在旧实现上稳定失败，新实现拒绝声明分段却缺失记录的日志。off 模式保留任务与围栏校验，同时明确拒绝完整链和分段接纳。15 文件增量补丁在隔离的修改前 Host/tests 副本应用并逐文件匹配；新增 Host 模块包含在补丁内。原生产 RAM 修复 SHA 不变。','','原始字节、实际 ELF/DTB/FIT、全量 Host/tests 源码、环境、工具版本和配置保留于 configs/ 与 raw/ 对应 cohort；本轮 Host 与测量实现一致性由 results/irq-stages-audit.json 核对；源码树唯一差异是低 EL 首次失败后补齐的 host-initramfs 装配清单，未更改此前两组使用的配置。脚本使用已有 plan 防止覆盖或盲目重启，运行顺序用于功能覆盖，未随机化用于效应推断。','','低 EL 首次尝试 irq-stages-qemu-lower-32 因新目录漏带 host-initramfs.toml，在测量前失败。原始日志、失败退出码和原控制器终态完整保留，0 条有效样本；补齐既有单 RT Guest 清单后使用新编号复测。恢复计划与终态分别为 configs/irq-stage-recovery-plan.json 和 results/irq-stage-recovery-status.json，不覆盖或重启原计划。','','新增热路径记录改变探针成本，第 16 节的 +5～9 µs 仅属于旧源码，不能移用于本轮。新开销、残余握手、频率/温度、完整 T0～T6 边界及重复四组实验仍未完成；M1/M2 为 false，无耦合或优化收益结论。QEMU 不支持真实硬件性能归因。','']
(archive/'results/irq-stages-report.md').write_text('\n'.join(lines))
print('IRQ_STAGE_AUDIT_OK boots=4 tasks=256 stage_samples=192 M1=0 M2=0')
