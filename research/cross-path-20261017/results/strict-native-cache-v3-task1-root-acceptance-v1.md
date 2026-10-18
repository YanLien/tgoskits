# 严格原生缓存 v3 Root 离线验收

本次接纳新缓存候选及其准确正常功能审计器的离线实现。真实板卡正常功能仍待执行，完整证据身份见 [Root JSON](strict-native-cache-v3-task1-root-acceptance-v1.json)，SHA256 为 `79d2b66a2f6291b2f6cf25dbb3749c1636c7967482030a1b65139ceac8d53f83`。

## 1. 离线结果

Root 在 Spec→Quality 通过后使用独立工具副本验证准入和单一执行根，并沿准确收据核对实际退出。

### 1.1 工具副本

真实只读 `--check-ready` 退出 0，副本正式执行按冻结根限制拒绝 2；完整父 `Popen.wait` 和原统一 exec 会话 81327 均实际退出 0，完成 chunk 为 `e0cb5d`。原 target 的 7784 项 metadata 前后一致，摘要为 `9b601bda1535cdff156a8e0dd2e9111a73583e9b44a6e5a7a43843d3d6db9b66`。原工具与副本均无新 marker，没有板卡或 QEMU 启动。

准确冻结为 `0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8`，107项文件；源702保持 `0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb`。此前 Root 已逐项重新读取83份证据、107冻结项和108个归档成员，核 SHA、大小、权限及路径安全通过。

### 1.2 正常功能审计器

[同次运行修订](strict-native-function-audit-v3-revision-v1.json)、[Spec复审](strict-native-function-audit-v3-spec-review-v1.json)、[新合同附录](strict-native-function-audit-v3-spec-binding-addendum-v1.json)及[合并Quality](strict-native-function-audit-v3-quality-review-v1.json)均已准确核定。新工具 `audit.py` SHA 为 `6fa57d1bb99a9fbdb49613ffc90cb4b648aa9511465957aec25b9e58e34e76aa`，合同 SHA 为 `8ff5e4a14fc159d0b0ec81bd26c00fe1860c62611d9e6a0f38c15989e6518d0e`。

新合同只替换两项身份常量，35个函数保持原样，17项实际来源一致。旧合同的八条收据错配、18条规则、两项继承检查和两次真实失败均按历史身份保留；没有在新合同上执行正常审计或取得完整 GREEN。

## 2. 后续边界

离线接纳只关闭构建环境和审计工具的准备缺口；硬件、追踪和研究结论继续各自取证。

### 2.1 单次运行

Root 启动副本只迁移准确路径和 SHA，保留原 `finally` 实际等待、target metadata、真实宿主所有权检查、60秒见证、单次与原预算。定向继承复核后，仍须取得当时的真实宿主及服务状态，才能批准一次新 AB1。任何失败或释放不明均停止后续案例，AB0/0不得提前执行。

已封存 prepare helper 的一处旧注释误称成功路径不读 `/proc`；实际会记录准确自持 child 的启动身份。对应[英文注释补丁](../patches/native-cache-v3-prepare-comment.patch)更正这一说明，适用于复现副本，原证据文件不回写。该补丁仅改两行注释，不改变执行或清理行为。

### 2.2 研究状态

真实新 AB1 的完整 DATA、全局零丢样、Trace导出、suite、工件链、实际退出和明确释放尚未验证。legacy生命周期、同版本匹配开销及随机重复相位实验仍待完成。正常Host、容量零丢样、M2、Joint和阶段2整体均未因此完成。
