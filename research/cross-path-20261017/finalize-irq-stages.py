#!/usr/bin/env python3
"""Seal a verified stage-observation checkpoint while keeping the research goal open."""
import hashlib
import json
from pathlib import Path
import subprocess

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
subprocess.run(['python3',str(archive/'audit-irq-stages.py')],cwd=repo,check=True)
report = json.loads((archive/'results/irq-stages-audit.json').read_text())
assert report['task_observations'] == 256 and report['stage_observations'] == 192
assert not report['M1'] and not report['M2']
assert len(json.loads((archive/'results/irq-stages-patch-audit.json').read_text())['changed']) == 15
readme = archive/'README.md'
text = readme.read_text()
section = '''

## 17. IRQ 路由与低 EL 计时器同步分段

### 17.1 分段契约与范围

[设计与所有权](design/irq-stage-observation.md) 复用唯一 HostIrqCapture 和有界记录器，追加稳定编号 11～14 及 version=1 声明。以 CPU/INTID/T0 ticks 严格关联 Host 路由 begin/end；低 EL 从既有退出值传播关联标量，包围 synchronize_timer。没有新增物理 IRQ 所有者、硬件状态登记表或活动路径日志，原 IRQ/计时器/VGIC/错误传播与退休顺序保留。当前 EL 的对应 timer_sync 为 null；GuestEntryBoundary 仍是进入后端前的软件点。缺失、重复、孤立、未知版本和逆序均拒绝，旧日志保留旧能力，off 不能冒充完整链。

### 17.2 实际验证与源码身份

四次独立启动包含 QEMU 当前 EL、RK3588 真板 Linux 内存 + SGI 压力、QEMU Guest-running 低 EL，以及 QEMU off。共 256 条任务观察，其中 192 条有完整新分段、64 条关闭记录只作任务观察。三次 on 的 dropped/incomplete 均为 0；低 EL 每策略必须实际捕获低 EL T0，不能用合成记录替代。每次物理样本的唯一 IrqKick 均在自己的路由区间内。分平台/策略分布、计时器 null 及重叠分类见 [分段验证报告](results/irq-stages-report.md)。不同拓扑不混合作干扰或开销估计。

39 项分析测试和 21 项 Clippy 通过；增强的原 physical 拒绝测试先在旧实现上确定性失败，证据为 raw/irq-stage-contract-red.log。所有适用完整分析、周期、Linux 围栏与压力验收通过；off 额外保存 task/stages 拒绝日志。原控制器 run-irq-stage-checks.py 在低 EL 首试的装配失败处停止，计划/终态与原始失败均保留，未产生有效样本。新目录补齐既有 host-initramfs.toml 后，用 resume-irq-stage-checks.py 的 configs/irq-stage-recovery-plan.json 与 results/irq-stage-recovery-status.json 完成剩余两项；不覆盖或重启旧计划。每组真实原始字节、实际 Guest ELF/DTB、真板 Host FIT/DTB、配置、工具与完整源码均冻结，results/irq-stages-audit.json 验证四次 Host/测量实现一致及分析输入测量字节不变；测试源码树仅新增此前未使用的低 EL 装配清单，该配置差异显式列出。

增量为 patches/irq-stages.patch，共 15 文件，含新增 Host 模块和低 EL 专用四 CPU QEMU 配置；在 configs/irq-stages-before.tar.gz 的完整 Host/tests 副本应用并逐文件匹配。package-irq-stages.py 同时扫描 tests 和 src，避免遗漏新增 Host 文件。第 14 节生产 RAM 修复保持原 SHA。当前检查点入口为 python3 research/cross-path-20261017/finalize-irq-stages.py；第 16 节 finalize-recorder-cost.py 仅验证该历史时点，不能对本轮新源码直接运行。历史配对数据不更改。

### 17.3 解释边界与后续门

新增记录改变热路径开销，前一版本 +5～9 µs 不能移用于此版本；需要重新量化新记录器和残余握手成本。跨核 Ready/Running/ISR 可与路由区间重叠，分段不可机械相加；timer 与路由之间的间隙含 VGIC 保存等适配工作，不能单独归因。软件包围点不是纯寄存器操作成本，也不是引脚到达、硬件 ERET 或严格 WCET/WCRT。

频率/温度、其余 T0～T6 边界及随机重复四组、I_AB 不确定性与吞吐权衡仍未完成。M1/M2 继续 false，无耦合、优化收益或阶段 3～5 完成声明。该研究热路径变更在合入前仍需独立领域设计审查，本轮不提交或合入。
'''
if '\n## 17.' not in text:
    readme.write_text(text+section)
else:
    assert text[text.index('\n\n## 17.'):].strip() == section.strip(), 'unexpected checkpoint section'
# Preserve the original source audit as historical; publish the current capability separately.
contract = archive/'design/current-stage-contract.md'
content = contract.read_text()
if '## 4. version=1 实现检查点' not in content:
    content += '''\n## 4. version=1 实现检查点\n\n以上第 1～2 节保留第 16 检查点的缺口说明。第 17 检查点已增加 T1 Host 路由起止与低 EL T2 synchronize_timer 起止，具体所有权与兼容规则见 [分段设计](irq-stage-observation.md)，实际路径证据见 [分段报告](../results/irq-stages-report.md)。当前 EL T2 为 null；其余边界和跨核重叠解释不变，新探针成本尚未量化，M1/M2 未完成。\n'''
    contract.write_text(content)
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
paths = sorted(p for p in archive.rglob('*') if p.is_file() and p.name != 'SHA256SUMS' and '__pycache__' not in p.parts)
for path in paths:
    if path.suffix == '.json':
        json.loads(path.read_text())
manifest = archive/'SHA256SUMS'
manifest.write_text(''.join(f'{digest(p)}  {p.relative_to(repo)}\n' for p in paths))
result = subprocess.run(['sha256sum','-c',str(manifest)],cwd=repo,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
assert result.returncode == 0,result.stdout
print(f'IRQ_STAGE_CHECKPOINT_OK files={len(paths)} accepted_boots=4 failed_boots=1 tasks=256 stage_samples=192 M1=0 M2=0')
