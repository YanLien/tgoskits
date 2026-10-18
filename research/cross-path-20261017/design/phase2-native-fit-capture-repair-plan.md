# 原生 FIT 捕获修订实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development task-by-task.

**Goal:** 在不改运行时或已封存失败的条件下，修复捕获工具对实际无内置hash FIT的错误假设，并用真实保存工件验证完整使用链。

**Architecture:** 在研究raw目录创建原工具的独立普通副本，只修FIT消费方。复用原完整捕获与后续字节绑定，不创建新控制器；输出一律新增。

**Tech Stack:** Python3 stdlib、fdtget/dtc、原捕获工具及准确AB1保存工件。设计见[修订设计](phase2-native-fit-capture-repair-design.md)。

## 1. Task1 工具修订

本任务只产生离线候选，不能越过既有板卡停止规则。采用新实施者，先Spec后Quality；Root核当前身份后方可用于未来新候选。本轮不进行Git写入。

### 1.1 输入与文件

原工具`/tmp/strict-native-phase-tools-kevemo32/capture_native.py`须为`388d83afc7ed92459e6fbae38601e8481a9e80f077fc7a2099d76219f6bde19b`，inputs.json为`78249f99440bf7b37a31d44f31b6ba1754e3bfca70142d8aa94aa355883e135b`。最终AB1 raw为1723337B/`c1e909ae2b747e178f2a6a82ebab719cea3a069a7e28ab2712841115f1adc5ec`；保存工件由原capture.json及Root最终handoff绑定。新代码、必要evidence副本与检查入口放`raw/strict-native-followup-v1/fit-capture-repair-v1/`，最终简报放`results/strict-native-fit-capture-repair-v1.json/md`。保留所有原文件SHA。

### 1.2 执行步骤

先复制原模块、inputs和实际需要的批准evidence（原始rootfs成员、init期望、worker/build与两份比较binary）；不复制cache、源码树或target。以完整`capture_native()`输入合同写最小回归，记录未修副本的准确拒绝为RED；随后仅修改缺hash处理及必要英文解释/元数据，执行同一合同为GREEN。保留已有hash核验、外部输入比较及全部后续身份门。再用私有software-only副本验证payload损坏拒绝，并以最小FIT通过真实`fit_components()`验证错误内置hash仍被拒绝；禁止改原target或保存FIT。任何后续真实身份问题先记录证据，不弱化原判据求绿。

## 2. Task2 审计与交付

本任务将代码验证和真实运行结论分开。离线新工具不能补写旧板卡成功或释放，也不能代替新的真板功能。

### 2.1 最终材料

交付最小diff、全部实际命令/原始stdout/退出、输入/新工具SHA、17工件比较结果、完整补充capture/rootfs结果及software-only负例。报告分列原capture链false、本次补充验证状态、Host正常功能false、原Trace loss19839、releaseunknown、硬件启动计数0。所有新输出用未存在路径；如已有结果则拒绝覆盖。原source/工具/封存不改；不运行正式分析、汇总、bootstrap、QEMU、board、proc或signal。

### 2.2 验收步骤

Root独立核新增文件身份和关键语义；先独立Spec后Quality，修正重要发现后复核。文档写清实际得到与仍欠缺的证据，更新根进度索引。仅在本离线合同全部证明后标本修订完成，goal、M2、Joint和阶段0～2整体均保持未完成。当前磁盘约3GB可用，材料预算512MiB以内；不删除历史证据腾空间。
