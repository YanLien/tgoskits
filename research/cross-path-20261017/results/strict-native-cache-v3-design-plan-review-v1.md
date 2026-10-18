# 严格相位缓存目录 v3 设计与计划独立审阅

结论：**PASS，未发现设计阻断，无需修订计划后才能进入已授权的 Task1 离线实施。** 本结论绑定 [v3 计划](../design/phase2-native-cache-topology-v3-plan.md) 的 11813 字节、SHA256 `5e355eb109871df9791d85953ff158dbe54b7416f615aea5a27b3d866e8eeb7d`。详细逐项判定和证据身份保存在[同名 JSON](strict-native-cache-v3-design-plan-review-v1.json)。本审阅没有执行 build、ready、测试、Git、板卡、QEMU、网络或进程探测，也没有修改实现、缓存和历史材料。

## 1. 设计判断

计划修正的是缓存复制的目录语义。`copy_manifest()` 只复制文件及链接，现有 `capture_native.verify_static()` 的 cache 遍历也未把真实目录作为独立身份，因此文件全部相等仍可能产生无法被 Git 识别的副本。

### 1.1 目录与入口

[已存因果实验](../raw/strict-native-phase-v2/zephyr-git-readonly-diagnosis-v1/empty-refs-causal-proof.json)保持 25 份 Git 文件不变，仅在独立元数据副本增加空 `refs` 后，真实 `rev-parse` 从 128 变为 0，固定 revision 为 `32229d0b6cc60a1906307311b8e79ec483ad1e88`，真实 worktree 的 `status --porcelain` 为空。原失败 v2 cache 保持拒绝，失败额度已消耗。

`shutil.copytree(..., symlinks=True)` 的实际标准库实现保留目录，并用 `copystat()` 复制模式。计划新增的目录 manifest 将两类 cache 的根 `.` 和所有非 symlink 目录纳入集合、类型及 `S_IMODE` 精确比较，覆盖原门遗漏；原文件、批准 symlink 及四种 Cargo bookkeeping 限制仍有效。五项恢复目录应绑定原正常父 cache `/tmp/strict-native-phase-tools-kevemo32/cache/vcpu-runtime-cache/zephyr/.git` 的已观察身份；容量 v2 副本本身正是缺目录的一方。

venv 重定位沿用原 13 项 bin/`pyvenv.cfg` 元数据边界，逐项 diff/mode/SHA 和真实 Python/module/CMake binary/直接 cmake 入口证明仍是必要条件。真实 `build_guest()` 直接执行 `venv/bin/cmake`，只核文件存在或继承旧入口收据不能验收新路径。vendor、site-packages 算法、工具链及 ELF 保持父字节，生产 Git revision/clean-tree 校验保持。

### 1.2 准备与继承

精读 `ktest::run_board()` 与 `guest_build::run_host_prepare()` 确认：Host preparation 在 `app.build()` 和 `board_prepared_elf()` 之前，以 workspace cwd、准确 argv 和 `AXBUILD_TARGET_DIR` 执行并等待。父副本控制文件的 `arceos_build_configs=[]`，准确命令为 `python3 virtualization/axvm/tests/guests/virq/prepare.py --linux-peer`。Python 调用链构建 Zephyr、Linux worker、DTB、资源和 rootfs，内部使用 `cargo xtask image pack-initramfs`，没有 Axvisor 构建、申请板卡或启动 QEMU 的调用。直接复用这个既有 preparation argv 符合当前缺少独立 xtask preparation 入口的边界。

完整准备仍须真实跑通并保存父 `Popen.wait`、环境、输出和实际工件，300 秒预算和准确自持进程组 cleanup10 按计划执行。入口含缺输入时的 venv 安装、clone 或工具链下载分支，实施时必须先核完整固定输入；触发这些分支或意外 cache/source 变化就停止冻结。只到 Git、Python 或 cmake 入口成功，证明范围仍不足。

保存的 `cargo fmt -p axvm` 收据实际 wait0，`cargo xtask clippy --package axvm` 收据实际 wait0，真实 stdout 汇总 29 passed、0 failed、0 skipped。v3 普通树、Rust、`Cargo.lock` 及 Rust 构建输入不变时可继承这些事实，并注明“未在 v3 重跑”。新 capture SHA、目录门、重定位和完整准备仍独立验收。环境纠错无需新增录制器模型或常量矩阵测试。

## 2. 实施准入

以下是计划已规定的后续证据条件，尚未由本审阅执行或接纳。它们区分设计可实施、离线准备通过和正常真板功能通过。

### 2.1 负例与冻结

真实目录门反例应在最终 freeze 前的可恢复暂存副本，或完整独立测试副本中执行。先准备准确的暂存目录预期，再移除 `refs` 层级并调用新 `verify_static()` 或真实 ready 入口，要求错误明确来自目录门；缺最终 freeze 或其他文件错误不能充作 RED。恢复时包括空 `heads`/`tags` 子层级及准确模式，文件身份保持。

完整 host_prepare、入口证明和负例恢复之后才生成最终文件/目录 manifest、inputs 和 freeze，再取得真实最终 ready0。新 capture 只增加目录检查，保留已接纳 FIT/newc/工件捕获函数字节；controller 只迁移输出根。之后 Spec→Quality，Root 精确复核并仅复制工具，保存只读 ready、单执行根拒绝、真实 wait、无 marker 及 target 前后状态。正式执行根不能为负例修改。

Root successor wrapper 要保留已审阅版本的 `finally: child.wait()` 和 `Root_copy_metadata` 准确路径/SHA 绑定。target 已有真实 preparation 产物，接纳须绑定其实际 metadata；Cargo runtime approval 取最近真实 ready 状态。所有权与清理边界继续限定准确 `start_new_session` 进程组、唯一 token 和原 cleanup10，未知项保持未知。

### 2.2 真板与研究

新候选按新 freeze、inputs、capture、source 和工具身份独立登记，不恢复失败 v2 额度。外部正常审计器的三项 Spec 阻断须在新副本修复并经 Spec→Quality；其正常端到端正路径仍待证明，可由本次真实新 AB1 提供，失败就拒绝。

Root 当前宿主无竞争、服务可用性和准确输入复核后，AB1 仅一次。board900、outer920 包含本次 build/request/upload/run，cleanup10、capture30、512MiB 和 host witness60 保持；过期拒绝。完整正常功能、工件使用链、真实退出/释放及 Spec→Quality 后才允许 AB0，再 0。失败、未完成、审计拒绝或 release unknown 均停止余项。

本次是静态设计/计划 PASS。v3 实现、真实完整 host_prepare、最终 ready0、正常 Host、容量零丢样、M2、Joint 和整体阶段目标都没有因此通过。三项真板之后才进入原 legacy 生命周期及后续匹配开销、相位和随机重复研究；既有失败、论文与封存报告保持。
