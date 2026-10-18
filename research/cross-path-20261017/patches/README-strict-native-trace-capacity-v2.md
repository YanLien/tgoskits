# 严格真板追踪容量 v2 补丁

本候选增加测量缓冲容量，供新的真实板卡功能验证使用。它不证明原丢样问题已经解决，也不构成优化收益；当前研究状态以根目录研究进度为准。

## 1. 源码重建

容量补丁以原严格真板702份正常候选为父版本。主树继续保存原强度实验的696份冻结源码，不能在主树应用本补丁后再声称其旧身份仍匹配。

### 1.1 父版本

先按[原相位候选说明](README-strict-native-phase-v1.md)在普通副本重建702份父源码，清单SHA为`9e2fe24f40d95cf54390ad476d89c8162e2bfba9e257966a4a2cb3b9c31b918f`。不要在原数据、封存或运行中的目录覆盖源码。

### 1.2 容量增量

再执行`git apply -p1`应用[容量补丁](strict-native-trace-capacity-v2.patch)。补丁SHA为`5ffc51f9742283c69dc7ee2251ed34960f78dc52de05406ed527b5e24be0be62`，仅修改`diagnostics.rs::CAPACITY`及两行英文说明；每CPU容量16,384→65,536，四CPU槽位内存估算2.5→10MiB。追踪写入、原子序、IRQ守卫、loss拒绝和导出逻辑保持父版本。

新702清单SHA为`0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb`，tar SHA为`072c67c53641c3428ddfaa031692a506443105b0a023376dff90e307e1f8f29d`。Root在独立普通文件副本实际完成`git apply --check`和应用，结果逐字节等于新候选；[检查收据](../notes/code-commit-20261018-v1/capacity-v2-patch-check-v1.json)保留两次真实wait=0。

## 2. 验证边界

[离线Task1报告](../results/strict-native-trace-capacity-v2-task1.md)绑定完整普通树、702源码、工具、输入及缓存身份。报告按当时状态保持原字节；后续独立验收另行追加。

### 2.1 离线准备

fmt和项目`cargo xtask clippy --package axvm`实际退出0，Clippy29/29。真实只读ready通过，错误source及approval被拒绝；新cache的Python/CMake入口已证明使用新路径。准确单次工具冻结SHA为`6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9`，现行授权与顺序见[计划v2](../design/phase2-native-trace-capacity-v2-plan-v2.md)。完整运行归档与缓存不全纳入Git，仍保存在研究目录及报告指向的独占路径。

### 2.2 真实板卡

离线检查不能证明零丢样。新AB1、AB0、0须逐项单次验证并完成各自功能、完整Trace、工件链、实际退出和释放验收，失败即停止后项。新版本还须补匹配的记录开/关开销和随机重复相位实验；原AB1失败、原release未知及M2未通过的结论保留。
