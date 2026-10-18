#!/usr/bin/env python3
"""Render the completed, audited recorder comparison with its actual limits."""
import json
from pathlib import Path

archive = Path(__file__).resolve().parent
data = json.loads((archive/'results/recorder-cost-paired-summary.json').read_text())
assert data['independent_pairs'] == 4 and data['task_observations'] == 512
lines = ['# 记录器开关配对试验报告','',
    '## 1. 数据与可解释范围','',
    '真板预先安排 4 个配对块，每块独立启动 on/off 各一次；种子 20261017，顺序为 off/on、on/off、on/off、off/on。每次启动包含 Fair/FIFO 各 32 条周期任务，共 512 条有效任务观察。其中 on 的 256 条通过现有完整追踪分析，off 的 256 条只作为已校验任务观察，不具备 IRQ 入口、vCPU 驻留与调度阶段轨迹。complete_chain 字段只代表现有观察点的验收范围，不表示全部细分阶段或 M1 已完成。QEMU 的 128 条功能观察不计入下表。','',
    '测试/Host 源码、Cargo.lock、工具版本、Guest ELF/bin、Guest/Host DTB、Linux 程序/内核/基底和任务配置一致；资源配置差异仅为 recording。on/off 都保留缓冲分配、编译钩子、校准握手、轮询、Guest 时间戳和 Linux 围栏。所测差值是记录器准入路径的增量观察，包含其原子操作、IRQ 保护、内部计数器读取和屏障，不是所有探针的总开销或单条写指令成本。','',
    'CPU 频率和温度未在这些窗口中测得或固定；平衡随机顺序不能消除未观测混杂或跨启动热状态影响。本报告是探索性对比，不能单独识别纯记录器因果开销，M1/M2 仍未完成。','',
    '## 2. 运行级配对结果','',
    '正数表示 on 大于 off。计划释放→任务结束的差值保留各次校准的时钟区间；该计划释放是 Host 逻辑计划，不是外部设备到达。两种策略分别统计，固定的策略执行顺序不支持策略优劣的因果比较。','',
    '| 策略 | 平均响应差时钟区间（µs） | 探索性配对 bootstrap 95% 区间（µs） | Guest 任务执行差（ns） | Linux 迭代率变化（%） |',
    '| --- | --- | --- | --- | --- |']
for policy,p in data['policies'].items():
    lines.append(f'| {policy} | [{p["latency_on_minus_off_mean_lower_ns"]/1000:.3f}, {p["latency_on_minus_off_mean_upper_ns"]/1000:.3f}] | '
                 f'[{p["exploratory_paired_bootstrap_95_lower_ns"]/1000:.3f}, {p["exploratory_paired_bootstrap_95_upper_ns"]/1000:.3f}] | '
                 f'{p["task_execution_on_minus_off_mean_ns"]:.2f} | {p["linux_rate_change_percent"]:.3f} |')
lines += ['', 'bootstrap 以整个配对块为重采样单位，10000 次、种子 20261018，不把单次启动内的 32 条任务当作独立重复。区间外沿同时保留时钟不确定性；只有 4 个块，覆盖率未建立，也未覆盖未测频率/温度混杂，不作显著性或收益判断。Linux 数值是有边界已完成 LCG 迭代率的配对相对变化均值，不是 DRAM 带宽。','',
    '| 策略 | on 观测 DMR 时钟界 | off 观测 DMR 时钟界 | Marker 包络平均差（ns） |',
    '| --- | --- | --- | --- |']
for policy,p in data['policies'].items():
    lines.append(f'| {policy} | {p["observed_dmr_clock_bounds"]["on"]} | {p["observed_dmr_clock_bounds"]["off"]} | {p["marker_envelope_on_minus_off_mean_ns"]:.2f} |')
lines += ['', 'DMR 界仅表示观测样本的时钟分类不确定性，不是统计置信区间。Marker 包络含时间戳读取且可能受抢占影响，仅为辅助组件观察。每策略每次 32 条任务的 P99.9 退化为样本最大值，不能据此建立稳定尾部或 WCET/WCRT。逐次分布与校验信息保留在各 cohort 的 probe_cost/summary.json 和 samples.csv。','',
    '## 3. 原始输入与剩余测量门','',
    '原始串口输出、构建前源码归档、输入/固件哈希位于 raw/recorder-cost-* 和 configs/recorder-cost-*。预定顺序为 configs/recorder-cost-pair-plan.json；运行状态为 results/recorder-cost-pair-status.json。逐块差值见 recorder-cost-paired-replicates.csv，完整审计和不确定性参数见 recorder-cost-paired-summary.json。关闭模式被完整链入口拒绝的日志逐次保留。','',
    '下一步补齐当前实际 IRQ 分发/计时器同步阶段、其新增观测成本、剩余握手成本和真板环境字段。GuestEntryBoundary 是进入后端前的软件观察点，不能冒充 ERET 硬件时间；跨核 IRQ 处理与 Guest 调度可以重叠，不能简单把完整阶段持续时间相加。之后才能运行匹配配置的重复四组并估计 I_AB；本轮不提供耦合或联合优化结论。','']
(archive/'results/recorder-cost-report.md').write_text('\n'.join(lines))
print('RECORDER_REPORT_WRITTEN pairs=4 task_observations=512 M1=0 M2=0')
