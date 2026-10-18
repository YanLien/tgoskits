#!/usr/bin/env python3
"""Seal the thermal checkpoint without upgrading partial environmental coverage."""
import hashlib
import json
from pathlib import Path
import subprocess

archive=Path(__file__).resolve().parent
repo=archive.parent.parent
subprocess.run(['python3',str(archive/'audit-thermal.py')],cwd=repo,check=True)
report=json.loads((archive/'results/thermal-audit.json').read_text())
assert report['thermal_snapshots']==4 and report['task_observations']==128
assert not report['M1'] and not report['M2']
section='''

## 18. 独立于 CPU 调频的温度观测

### 18.1 唯一设备所有者与显式配置

[rk3588-thermal 设计](design/independent-thermal-observation.md) 将原调频模块内的 TSADC 探测/初始化、永久映射、保护校验与温度转换迁到独立 thermal 模块。CPU 调频包含并复用它，OTP/PVTM/regulator/OPP/governor 不因单独测温启用。新的公共查询只读、缺失/无效/失去保护时返回明确错误；原 cpufreq refresh 收紧阈值的行为仍由原 feature 使用。SoC 通道 0 与 A55 簇通道 3 分开命名，不混用 VM/逻辑 CPU 编号。

axtest-thermal 显式启用测温；默认配置不变。冷启动有 CRU/TSADC 初始化写入，继承的 CRU 核心还可能归一化 PPLL，不能称为整机完全被动插件。每个策略的 VM 创建前和全部退休后各查询一次两传感器，只保存值和计时包围区间，待全部 VM 退休与追踪关闭后批量输出。这些点不证明窗口最高温度或恒温，也不等价于固定 CPU 频率。

### 18.2 真实验证与拒绝

本轮 2 次有效独立启动共 128 条任务观察：真板 Linux 内存 + SGI 压力在启用测温时取得 4 组前后快照，默认 QEMU 保持温度不可用/null。两组完整链、周期、围栏、压力和 IRQ 分段验收通过，追踪 dropped/incomplete 均为 0。真板实际温度与两次查询的包围耗时详见 [温度观测报告](results/thermal-report.md)，仅作有边界的快照证据。

另一次 QEMU 开启测温但无 TSADC，在 VM 创建前按预期拒绝，0 条有效任务；没有补零、使用旧温度或跳过要求。原控制器对串口错误文本的匹配被 runner 插入的诊断行分割而中断，原计划、失败终态和原始日志保留。新恢复计划严格验证原错误的唯一诊断插入行，不改变原始字节或修复性能数据，之后只运行尚未执行的两组。证据为 configs/thermal-check-plan.json、configs/thermal-recovery-plan.json、results/thermal-negative-audit.json 和 results/thermal-recovery-status.json。

### 18.3 源码与测试证据

93 项定向 Clippy 和 40 项 Python 分析测试通过。当前源码的隔离副本只将自己的 std 测试清单限定 ax-driver，再运行原 cargo xtask test 的四个正式 profile；主树清单不改、未创建提交。隔离的“查询写寄存器”变异稳定失败，恢复后同一套件通过。原刷新阈值规则继续覆盖，但本轮未执行 CPU 升降频硬件测试，纯寄存器规则测试不替代真板设备证据。

增量 patches/independent-thermal.patch 共 16 文件，包括新增独立驱动、feature、测温记录/分析和完整运行侧车配置。在 configs/thermal-before-complete.tar.gz 的副本隔离应用后逐文件匹配；原始基线归档未改，补入的唯一 axvm manifest 来源核验见 configs/thermal-before-completion.json。三次启动的 Host/tests/驱动、feature manifest、锁文件与实际构建产物冻结，分析输入的测量字节保持原样。results/thermal-audit.json 验证身份和阶段边界，原 RAM 修复 SHA 不变。当前封存入口为 python3 research/cross-path-20261017/finalize-thermal.py；以前的 finalize 仅描述各自历史检查点，不能对当前驱动/测试源码直接运行。

### 18.4 剩余门

CPU 实际频率与窗口内环境覆盖仍缺失，当前 Guest 上下文会保存/恢复 PMCR_EL0，不能将跨 VM 的计数差直接当送达频率。本轮不写 PMU、不强制 OPP。新版本记录器/残余握手成本、其余 T0～T6 边界、EL3 固件逐次身份和随机重复四组仍未完成；旧 +5～9 µs 不能移用于新配置。M1/M2 继续 false，无耦合、联合优化或严格 WCET/WCRT 声明。高风险共享驱动在合入前仍需独立领域设计审查，本轮不提交或合入。
'''
readme=archive/'README.md'
text=readme.read_text()
if '\n## 18.' not in text:
    readme.write_text(text+section)
else:
    assert text[text.index('\n\n## 18.'):].strip()==section.strip()
notes={
 'design/platform-observation-gap.md':'本文件保留第 16 检查点的缺口。第 18 检查点已独立启用 TSADC 并取得真板策略前后温度，见 [温度报告](../results/thermal-report.md)。CPU 实际频率、窗口内最高温度与固件身份仍未补齐，旧配对数据不回填。',
 'design/m1-next-measurement-gate.md':'本文件保留第 15 检查点的测量门。第 17 已验证 IRQ 路由/低 EL 计时器分段，第 18 已取得独立 TSADC 前后快照，见 [当前报告](../results/thermal-report.md) 与 README 第 17～18 节；新配置成本、CPU 实际频率和重复四组仍待完成。',
}
for path,note in notes.items():
    target=archive/path;content=target.read_text()
    if note not in content:
        first,rest=content.split('\n',1)
        target.write_text(first+'\n\n'+note+'\n'+rest)
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
paths=sorted(p for p in archive.rglob('*') if p.is_file() and p.name!='SHA256SUMS' and '__pycache__' not in p.parts)
for path in paths:
    if path.suffix=='.json':json.loads(path.read_text())
manifest=archive/'SHA256SUMS'
manifest.write_text(''.join(f'{digest(p)}  {p.relative_to(repo)}\n' for p in paths))
result=subprocess.run(['sha256sum','-c',str(manifest)],cwd=repo,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
assert result.returncode==0,result.stdout
print(f'THERMAL_CHECKPOINT_OK files={len(paths)} accepted_boots=2 expected_rejected_boots=1 tasks=128 snapshots=4 M1=0 M2=0')
