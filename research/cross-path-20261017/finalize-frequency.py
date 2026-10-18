#!/usr/bin/env python3
"""Seal the frequency snapshot checkpoint while retaining the full M1/M2 gates."""
import hashlib
import json
from pathlib import Path
import subprocess

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
subprocess.run(['python3', str(archive/'audit-frequency.py')], cwd=repo, check=True)
section = '''

## 19. 保持 PMU 状态的逐核频率快照

### 19.1 所有权与观测边界

[短窗口设计](design/pmu-frequency-observation.md) 在现有本核 Pmu 所有者内增加受限只读回调与私有恢复守卫。PMCR 全局、counter、IRQ 或用户权限非空闲即无写入拒绝；仅核对过的版本 1/4/5/6 可借用，不复位全部 PMU，不写 OPP/SCMI/MDCR。恢复完整 64 位周期值、过滤器、原溢出与控制，原 PmuError 与调用方不改。Host PMCR 本来就保存恢复；本轮不声称修复其遗失问题。

axtest-frequency 显式启用。在每个策略的 VM 创建前、全部退休后，逐核固定亲和性，在屏蔽 IRQ 的约 2 ms 忙循环里用两组时间戳包围周期读；控制器亲和性随后恢复 CPU0，输出在全部 VM 退休和追踪关闭后。所得区间假设单 tick 的参考分辨率并计入一个周期粒度，依赖公布的参考频率。真板紧邻时间戳正差值全部为 7 ticks，单 tick 有效分辨率尚未验证，表中细小区间不能视作完整物理误差边界；约 816 MHz 仅为名义参考下的 PMU 快照估计，不是统计置信区间或运行窗口恒频保证。测频会预热核心、延迟本核 IRQ 并可能影响固件策略；温度在每组测频前查询。

### 19.2 实际验证与身份

[快照报告](results/frequency-report.md) 和 [原始值汇总](results/frequency-snapshots.csv) 记录三次独立完整链启动的 192 条任务观察。真板 Linux 内存 + SGI 压力取得 A55 四核的 16 个频率快照和 4 个温度快照；QEMU 开启取得 16 个功能快照，关闭保持不可用。三组完整链、周期、围栏与 IRQ 分段验收通过，dropped/incomplete 均为 0；QEMU 数值不作为物理频率证据。

75 项 Clippy、41 项分析测试通过。既有 PMU 正式用例在四核 Cortex-A53、四核 max QEMU 与八核真板通过，覆盖版本 1/6/4。八核只是独立寄存器功能测试，论文配置仍是四核。暂时截断恢复高 32 位后同一 QEMU 用例稳定失败，finally 恢复原字节后通过；没有其他实验在变异期间运行。较新未支持版本尚无真实执行证据。分析套件首次失败因拒绝输入未命中，修正输入后原规则通过，旧失败日志保留。

configs/frequency-check-plan.json 与 results/frequency-check-status.json 保存一次性计划及终态，不盲目重启。每次冻结 Host/tests/ax-cpu/驱动、feature、锁文件及实际镜像/DTB/FIT，measurement 字节未改；审计为 results/frequency-audit.json。真板同 tick 端点暴露初版分析缺少粒度边界，全部原计划结束后才修改两个分析文件，以同一测试先红后绿并重算三组数据；原源码及旧输出完整保留，差异见 configs/frequency-quantization-correction.json，旧数值已被替代。17 文件补丁 patches/frequency-cycles.patch 在 configs/frequency-before.tar.gz 的完整副本隔离应用并逐字节匹配，原 RAM 修复与 Host 热路径源码不变。当前封存入口为 finalize-frequency.py，以前 finalize 仅描述各自历史时点。

### 19.3 仍未完成的门

快照不证明活跃 VM 窗口内的频率、最高温度或固定 OPP；参考计数器有效分辨率和更新语义须先核对。新配置探针/残余握手成本、其余 T0～T6 边界、EL3 固件逐次身份、随机重复四组及运行级 I_AB 不确定性仍未完成，旧版本成本不能移用。M1/M2 继续 false，无耦合、优化收益或严格 WCET/WCRT 结论。高风险共享硬件 API 合入前仍需合格领域设计和 unsafe 审查，本轮不提交或合入。
'''
readme = archive/'README.md'
text = readme.read_text()
if '\n## 19.' not in text:
    readme.write_text(text+section)
else:
    assert text[text.index('\n\n## 19.'):].strip() == section.strip()
for name in ('platform-observation-gap.md', 'm1-next-measurement-gate.md'):
    path = archive/'design'/name
    text = path.read_text()
    note = '第 19 检查点已取得 A55 四核的 VM 创建前/退休后 PMU 周期快照，见 [频率报告](../results/frequency-report.md)。这只补部分实际频率证据，窗口内覆盖、新配置成本和重复四组仍未完成；本文件前述历史缺口不回填旧数据。'
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
print(f'FREQUENCY_CHECKPOINT_OK files={len(paths)} boots=3 tasks=192 native_snapshots=16 M1=0 M2=0')
