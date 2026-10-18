# 严格真板相位候选源码

[组合补丁](strict-native-phase-v1-candidate.patch)保存此前离线审阅通过的702源候选，包含有限C worker、计数域、Host相位消费与生命周期接入。它是可审阅的实验候选快照；原正常真板功能失败状态不变。

## 1. 源码身份

补丁将已交付强度版本的696份源恢复为严格真板候选的702份源，共23份修改或新增。它不含容量v2的65,536条配置，也不改变当前主工作树的运行源。

### 1.1 复现基底

基底使用[强度计划](../configs/intensity-v3-plan.json)的696份源SHA，代码与提交`6d2443c9b`一致。只在独立普通副本应用补丁；当前正式控制器仍核主树的既有696源，直接应用到主树会改变该输入身份。补丁不能替代板卡配置、缓存、镜像和准确运行环境。

### 1.2 重建核验

Root在普通临时目录先逐项复制696份源，再执行真实`git apply --check`及`git apply`，两者实际wait均为0；得到的702份文件集合和SHA逐项匹配已审阅清单`9e2fe24f40d95cf54390ad476d89c8162e2bfba9e257966a4a2cb3b9c31b918f`。记录见[补丁身份](../notes/code-commit-20261018-v1/native-phase-candidate-patch-identity.json)和[重建收据](../notes/code-commit-20261018-v1/native-phase-candidate-patch-check.json)。首次生成缺少新文件mode头而拒绝的草稿另存，没有作为通过证明。

## 2. 验证范围

源代码可追溯与目标正常功能分别判断，不能因为代码已提交便改写实验结果。

### 2.1 原候选状态

该702候选完成[离线准备验收](../results/phase2-strict-native-task1-offline-acceptance-v2.md)。随后[原AB1失败证据](../results/strict-native-phase-v1-AB1-failure-audit-v1.md)观察到64条T6及完整DATA/ACCEPT，但Trace dropped=19839、正常逐事件导出0，xtask及driver实际退出1；原正常功能未通过、releaseunknown，后项未执行。补丁重建不补写这些状态。

### 2.2 新容量接续

后续[容量v2计划](../design/phase2-native-trace-capacity-v2-plan-v2.md)在另一份独立副本中调整测量容量，必须重新冻结源码和工具，经验证后才能单独批准新真板任务。旧版开销不能直接用来校正新版；本补丁不证明M2、传播机制或联合优化收益。
