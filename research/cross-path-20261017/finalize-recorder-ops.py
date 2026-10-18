#!/usr/bin/env python3
"""Seal current recorder cost evidence only after the full paired plan succeeds."""
import hashlib
import json
from pathlib import Path
import subprocess

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
subprocess.run(['python3', str(archive/'audit-recorder-ops.py')], cwd=repo, check=True)
section = '''

## 21. 当前版本记录操作的八对真板对照

### 21.1 范围与重复单位

[协议与范围校正](design/current-probe-cost-plan.md) 以版本 2 声明 recorder_operations，涵盖随开关门控的内部时间戳、IRQ 守卫、writer 登记、预留与写入。旧 recorder_writes 声明兼容但不保证纯内存写入成本；独立任务/IRQ 计时、入口检查、编译 hook、邮箱和 Linux 围栏等残余项保留。本轮不改 Host 热路径或 PMU 核心。

两组 QEMU on/off 功能验证后，按运行前种子 20261021 的平衡顺序执行 8 个独立真板启动对；16 次启动共 1024 条任务观察。on 的 512 条有记录并通过既有物理任务链入口，off 的 512 条只作任务观察，完整链和 IRQ 阶段必须拒绝，trace_loss 保持未知。频率、温度和计数序列两模式均启用，其他工作量与输入相同。QEMU 的 128 条任务不进入性能估计。

### 21.2 统计、身份与实际结果

[开销报告](results/recorder-ops-report.md)、[逐对结果](results/recorder-ops-paired-replicates.csv) 和 [环境快照](results/recorder-ops-environment.csv) 给出共同计划释放→Guest 完成端点的 on−off 均值区间、以完整启动对为单位的 10000 次 Bootstrap、Guest 执行差、Linux 吞吐、尾部和观察 DMR。8 对不是 256 次独立重复；百分位包围不认证小样本覆盖率或物理时钟误差，P99.9 在每策略/模式 256 个任务时等于最大次序统计量。差值可为负，不预设正开销或优化收益。

29 项 Clippy、42 项分析测试通过。准确声明的同一行为测试在旧解析实现上先失败，更新后通过，legacy 及错误版本组合的规则保持。独立统计测试通过；隔离副本膨胀到每任务独立重采样时稳定失败，主源码不改。三文件补丁 patches/recorder-operations.patch 在 configs/recorder-ops-before.tar.gz 的副本隔离应用后匹配。每次冻结相关源码、工具、输入和实际产物；原测量字节不改，真板 FIT/DTB 按本次启动日志的实际路径核对，不把其他缓存文件当作使用证明。

一次性计划与终态为 configs/recorder-ops-plan.json、results/recorder-ops-status.json，不盲目重启。审计为 results/recorder-ops-audit.json，当前封存入口为 finalize-recorder-ops.py；旧 finalize 仅描述各自历史时点。

### 21.3 剩余 M1/M2 门

快照不是运行窗口恒频、最高温度或固定 OPP 的保证，U-Boot/BL31 逐次身份仍不完整。记录操作差值不是全部探针成本，T4 仍是软件进入边界，阶段重叠和关联比例须准确报告。M1/M2 保持 false。下一步审计同一链中的实际阶段与残余成本，然后进行交错/随机重复 0/A/B/AB，按运行级均值估计 I_AB，不以分位数非加性证明耦合；仅在稳定交互和机制证据支持后进入后续优化。本轮不提交或合入。
'''
readme = archive/'README.md'
text = readme.read_text()
if '\n## 21.' not in text:
    readme.write_text(text+section)
else:
    assert text[text.index('\n\n## 21.'):].strip() == section.strip()
# Correct the interpretation of historical labels, preserving all raw bytes,
# estimates and archived source/config snapshots from the earlier experiment.
old = archive/'results/recorder-cost-report.md'
note = '范围勘误：旧 recorder_writes 标签不保证“纯内存写入成本”；内部时间戳等启用路径操作也受开关门控。原数值与原始数据保留，当前范围及新版实测见 [第 21 检查点报告](recorder-ops-report.md)。'
content = old.read_text()
if note not in content:
    first, rest = content.split('\n', 1)
    old.write_text(first+'\n\n'+note+'\n'+rest)
for name in ('platform-observation-gap.md', 'm1-next-measurement-gate.md'):
    target = archive/'design'/name
    note = '第 21 检查点已按当前观测版本完成 8 对记录操作开销比较，见 [新报告](../results/recorder-ops-report.md)。差值不等同全部残余探针成本；M1 阶段关联审计、逐次固件身份及重复四组仍待完成。'
    content = target.read_text()
    if note not in content:
        first, rest = content.split('\n', 1)
        target.write_text(first+'\n\n'+note+'\n'+rest)
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
paths = sorted(p for p in archive.rglob('*') if p.is_file() and p.name != 'SHA256SUMS' and '__pycache__' not in p.parts)
for path in paths:
    if path.suffix == '.json':
        json.loads(path.read_text())
manifest = archive/'SHA256SUMS'
manifest.write_text(''.join(f'{digest(p)}  {p.relative_to(repo)}\n' for p in paths))
result = subprocess.run(['sha256sum', '-c', str(manifest)], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
assert result.returncode == 0, result.stdout
print(f'RECORDER_OPS_CHECKPOINT_OK files={len(paths)} native_pairs=8 native_tasks=1024 qemu_tasks=128 M1=0 M2=0')
