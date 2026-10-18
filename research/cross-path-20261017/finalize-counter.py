#!/usr/bin/env python3
"""Seal empirical counter statistics without certifying clock accuracy."""
import hashlib
import json
from pathlib import Path
import subprocess

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
subprocess.run(['python3', str(archive/'audit-counter.py')], cwd=repo, check=True)
section = '''

## 20. EL2 连续计数读与分辨率敏感性

### 20.1 同一所有者内的只读序列

[设计与权威语义](design/counter-increment-observation.md) 在原 axtest-frequency 固定 CPU、IRQ 守卫和 VM 创建前/退休后位置，增加 physical、virtual 与无额外 ISB 的 physical_raw 三类序列，每类 256 个完整原始值。采集在周期计数借用之前；不新增全局状态、PMU 所有者或 feature，不读写 Secure 计数控制、参考频率、比较器、GIC 或 OPP。数组随原快照保存，全部 VM 退休与追踪关闭后才输出。默认关闭显式声明没有序列。

新分析入口严格校验版本、完整键集合、时钟、u64、物理包围与任务窗口。串行化序列逆序或无进展拒绝；virtual 不假定 offset=0，raw 只作读序诊断并保留逆序统计。有限样本的增量、GCD 和最小正值不自动成为硬件最大步长或校准证明。

### 20.2 实际结果与验证

[连续读报告](results/counter-report.md)、[完整序列](results/counter-series.csv) 和 [频率敏感性](results/counter-frequency-sensitivity.csv) 记录三次独立完整链启动。真板四核 Linux 内存 + SGI 与 QEMU 开启各取得 48 段、12288 个原始读数；默认关闭无序列。共 192 条有效任务观察，完整链、周期、围栏、IRQ 分段与新序列验收通过，dropped/incomplete 均为 0。QEMU 只作为功能证据，不混合作物理分辨率推断。

29 项 Clippy、42 项分析测试通过。临时移除串行化逆序拒绝时同一测试稳定失败，恢复原字节后通过，见 configs/counter-reversal-contract.json。五文件增量 patches/counter-increments.patch 在 configs/counter-before.tar.gz 的副本隔离应用后匹配。CPU 核心、Host 热路径、PMU 恢复、驱动、压力实现、manifest、锁文件及原 RAM 修复不变；每次冻结相关源码和实际构建产物，measurement 原始字节不改。

configs/counter-check-plan.json 与 results/counter-check-status.json 保存一次性计划及终态；禁止盲目重启。当前审计为 results/counter-audit.json，封存入口为 finalize-counter.py；旧 finalize 只描述各自历史时点。

### 20.3 解释与后续门

Arm 规范允许减少可见计数更新而保持名义时间尺度，不能从 CNTFRQ 推定每次只更新一 tick。本轮保留三个模式的原始分布及 q=1/观察 GCD 的敏感性，不认证硬件配置、未来最大更新步长或参考时钟准确度，也不回填第 19 原始结果。后续性能比较应报告名义参考、观察粒度及假设，不能冒称绝对物理误差保证。

新配置记录器和残余握手成本、其余阶段边界、固件逐次身份以及随机重复四组、运行级 I_AB 不确定性仍待完成。[下一步开销对照](design/current-probe-cost-plan.md) 已据源码将差值范围明确为记录操作，包含被门控的时间戳、预留和写入，不能只称纯内存写入。M1/M2 继续 false，无稳定耦合、联合优化或严格 WCET/WCRT 结论。本轮不提交或合入。
'''
readme = archive/'README.md'
text = readme.read_text()
if '\n## 20.' not in text:
    readme.write_text(text+section)
else:
    assert text[text.index('\n\n## 20.'):].strip() == section.strip()
for name in ('platform-observation-gap.md', 'm1-next-measurement-gate.md'):
    path = archive/'design'/name
    text = path.read_text()
    note = '第 20 检查点增加 EL2 物理/虚拟/无额外 ISB 的连续读，见 [原始分布与敏感性](../results/counter-report.md)。观察增量不是硬件最大步长或绝对校准；后续须据明确假设报告名义时延，新配置成本和重复四组仍待完成。'
    if note not in text:
        first, rest = text.split('\n', 1)
        path.write_text(first+'\n\n'+note+'\n'+rest)
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
paths = sorted(p for p in archive.rglob('*') if p.is_file() and p.name != 'SHA256SUMS' and '__pycache__' not in p.parts)
for path in paths:
    if path.suffix == '.json':
        json.loads(path.read_text())
manifest = archive/'SHA256SUMS'
manifest.write_text(''.join(f'{digest(p)}  {p.relative_to(repo)}\n' for p in paths))
result = subprocess.run(['sha256sum', '-c', str(manifest)], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
assert result.returncode == 0, result.stdout
print(f'COUNTER_CHECKPOINT_OK files={len(paths)} boots=3 tasks=192 native_series=48 native_reads=12288 M1=0 M2=0')
