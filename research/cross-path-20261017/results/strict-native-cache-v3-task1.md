# 严格原生缓存 v3 离线准备

## 1. 准备结果

本次候选完成离线实施和实际 ready，状态为 `OFFLINE_READY_PENDING_SPEC_QUALITY_ROOTCOPY`，待独立 Spec→Quality 和 Root 工具副本验收。完整身份与收据见 [JSON 报告](strict-native-cache-v3-task1.json)。未启动板卡或 QEMU，未消耗正式案例额度。

### 1.1 输入与入口

普通源为 `/tmp/crosspath-native-cache-v3-src-hr23qnrs`，工具为 `/tmp/crosspath-native-cache-v3-tools-jrhcn15t`，target 为 `/tmp/crosspath-native-cache-v3-target-wg0fd7ru`。全部 9642 普通文件与 702 源保持父容量 v2 字节和模式；普通清单 SHA 为 `f4bd9bb6dadd056e35faa2b3243a1be410a588f531f6bceb7d71c89e520e3c86`，702 清单 SHA 为 `0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb`。缓存使用 `shutil.copytree(symlinks=True)` 保存目录语义，仅在新副本补齐五个模式 0775 的已观察空 Git 目录，并重定位原批准的 13 项 venv 入口及 metadata。

新 Python prefix、CMake 模块和实际 binary 均归新缓存，直接 CMake、真实 Git 固定 HEAD 和 clean status 均实际 wait 0。准确生产命令 `python3 virtualization/axvm/tests/guests/virq/prepare.py --linux-peer` 只运行一次，同一父 `Popen.wait` 为 0，耗时 72.172 秒，预算仍为 300 秒。环境沿用父白名单和 AB1，仅替换五项路径，另有原控制器同式 `STRICT_NATIVE_RUN_TOKEN` 所有权标记。只读取准确自持子 PID 身份，未扫描宿主进程，也未触发 timeout、cleanup 或信号。

### 1.2 实际产物

真实 Zephyr ELF、BIN、DTB、Linux worker、rootfs、build.json 与资源配置已保存身份。`capture_native.verify_rootfs()` 对实际 rootfs 验证通过，init 为 390 字节，worker SHA 保持 `b9db9b8fc7925bf2c18e2d9edfbd3c0ee10a5a0f57985151e2f7b0073122ffc2`，固定 kernel/base 路径与 SHA 不变。v2 的 fmt wait 0 与项目 Clippy 29/29 收据仅因普通源全同而继承，明确未在 v3 重跑。

## 2. 冻结与边界

最终 freeze SHA 为 `0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8`。工具归档仅含冻结工具与 evidence，未包含 cache/target；归档 SHA 为 `8a64c8b14183c7124299cc2fa9d1e7dcfcc1fee826d368617875203a7892fc97`。原始材料目录总文件字节为 210003658，小于 1 GiB，临时 cache 和 target 容量在 JSON 单列。

### 2.1 生成缓存与目录门

第一次 finalizer 真实 wait 1 和首错保持原样：生产准备新增了 45 个单字节能力结果，并向既有 `ToolchainCapabilityDatabase/log.txt` 追加 27,058 字节、45 行。Root 精核和独立 PASS 的[精确补充](../design/phase2-native-cache-topology-v3-generated-cache-addendum-v1.md)已绑定最终材料；最终只接纳这 45 项、准确 log 新身份和原 13 项入口重定位，所有其他 VIRQ 不可变文件与父相同，Cargo 不可变文件全同。生成缓存已进入不可变清单，没有新增 runtime 例外。

新 `verify_static()` 在原 `os.walk` 收集两组全部非 symlink 目录、根 `.` 和 mode，并在大文件 hash 前核集合、类型与模式。冻结前对实际暂存 cache 移除空 refs 层级，真实入口实际 wait 2，明确因目录身份门拒绝；随后完整恢复目录与模式。最终冻结后，真实 `native_once.py --check-ready` 实际 wait 0，target metadata 不变且无 `.once`。capture 仅该函数变化，其余所有字节与批准父版本相同；controller 仅换输出根。

### 2.2 证据范围

父 source/cache 的完整 lstat 身份和成员集合、所选父工具/manifest/旧失败材料的前后 SHA 保持一致；没有修改主源码、旧候选或论文封存。两个本地 helper 前置错误已分别保留准确快照、首错和纠错 diff；它们发生在首次生产 prepare Popen 之前，不计作生产准备失败或重试。后续工具归档 helper 曾将含文件类型位的原始 TarInfo.mode 直接与权限字段比较并退出 1；失败部分 tar 与收据保留，修正为 stat.S_IMODE 后对实际序列化 tar 再核完整 mode/size/SHA，未触碰冻结候选。首次冻结拒绝与后续精确补充接纳分列，历史收据不回填。

本报告只接纳离线准备实施候选。正常 Host、容量零丢样、M2、Joint、goal_complete 和 hardware_authorized 均为 false；Spec、Quality 和 Root 副本验收仍待独立执行。后续真实硬件运行仍须 Root 单独准确批准，并沿用原单次与预算门。
