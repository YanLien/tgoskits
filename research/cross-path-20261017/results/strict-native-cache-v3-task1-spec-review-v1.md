# 严格原生缓存 v3 Task1 Spec 审阅

本审阅把缓存目录修复、实际准备退出和最终不可变身份逐项对应，判断离线候选是否符合已批准计划及精确缓存补充。

## 1. 离线判定

本次独立本地 Spec 审阅结论为 **PASS**，阻断项为空。结论只适用于指定 Task1 冻结候选及准确正式报告；待 Quality 和 Root 工具副本验收完成后，才能判断 Task1 最终独立验收。完整逐条核对与证据身份见 [JSON 审阅](strict-native-cache-v3-task1-spec-review-v1.json)。

### 1.1 准确身份

审阅绑定 [Task1 JSON](strict-native-cache-v3-task1.json) SHA `e1ce19382c35cc1c7c791bf618b07c7ea2840aa6a284efebf1d7da44038a9e59`、[Task1 Markdown](strict-native-cache-v3-task1.md) SHA `a3f42ef837f6df2652e2f0699d06223e6ac91c550730c4372520588ee5ba184d`。候选 source、tools、target 分别为 `/tmp/crosspath-native-cache-v3-src-hr23qnrs`、`/tmp/crosspath-native-cache-v3-tools-jrhcn15t`、`/tmp/crosspath-native-cache-v3-target-wg0fd7ru`。当前主 HEAD 仅取任务给定上下文，未运行 Git 复核。

冻结清单 107 项，SHA `0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8`；capture SHA `61717a37b528e2e93d8cbcae1c1dafbc6249ac3417fbf0b8011b984a03a4c683`，controller SHA `8b871b1ea3cfb8a8ad8272bc7fa5ca37dc648b3efed45fe4af9ae0f374a24902`，inputs SHA `8fac8a1fb86d79a1e74bf9591bf68fa2dd88f6d261edcf0ea576dfbd6ace0060`，目录清单 SHA `dca2a114c1ec0241196d7d7e2163504239076f283ec034e8d39f5e97bc8e738e`。这些当前身份已独立定向新哈希核对。

### 1.2 源码与准备

源 702 清单 SHA 保持 `0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb`，9642 普通文件清单 SHA 保持 `f4bd9bb6dadd056e35faa2b3243a1be410a588f531f6bceb7d71c89e520e3c86`；两份清单与父版本逐字节相同。全树实际一致性由已落 `source-post-validation.json` 和 ready 收据证明，本审阅只另核准确生产源码、sidecar、`run_host_prepare()` 与 `Cargo.lock`，未重复全源扫描。父 v1/v2 失败报告、原 Trace 证据及已耗 `AB1.once` 保持，选定历史文件当前 SHA 与保护基线相同。

`prepare.py` 使用 `shutil.copytree(...,symlinks=True)`，保留目录与模式，仅在新副本补五个已观察 Git 空目录，模式 0775。批准的 13 项 venv 重定位 diff 只换前缀；真实新 Python/CMake、Git revision 和空 status 均有 wait 0 收据，输出当前 SHA 一致。`frequency/guest-builds.toml` 的完整生产命令与收据一致：`python3 virtualization/axvm/tests/guests/virq/prepare.py --linux-peer`。空继承环境精确匹配最终 inputs 的 AB1 白名单，只增加原控制器式所有权 token；完整准备仅一次，父 `Popen.wait=0`，72.17154478497105 秒，预算 300 秒。真实 Zephyr/Linux 资源与 rootfs 有准确身份，worker 不变，未启动 Host、板卡或 QEMU。

Rust 验证仅继承父实际 fmt 0 与项目 Clippy 29/29，收据 SHA 已核，明确未在 v3 重跑。inputs 除规定四个顶层字段、五个环境路径外精确相同；cases、测量参数、Cargo runtime 四类例外和原预算保持。

## 2. 不可变门

本次功能变化只把目录身份纳入现有 `capture_native.verify_static()`。其余捕获代码和 `native_once.py` 的单次与所有权门没有改变，避免把准备通过扩大为正常运行证明。

### 2.1 目录与真实反例

`verify_static()` 读取两组目录 manifest，分别冻结 VIRQ 9874、Cargo 17749 个非 symlink 目录，均含根 `.` 与 `S_IMODE`。它在原 `os.walk` 收集实际目录，核规范相对路径、真实目录类型、集合和权限，并在每组缓存文件的大 SHA 前拒绝目录差异；真实目录被 symlink 替代明确拒绝，原批准 symlink 及文件门继续工作。独立比较确认 capture 在该函数外字节全同，controller 仅将输出根 v2 改为 v3。

[目录负例收据](../raw/strict-native-phase-v3/task1/directory-missing-refs-negative.receipt.json) 保存真实 wait 2，明确报告缺 `refs`、`refs/heads`、`refs/tags`。`audited_entry.py` 调用真实 `verify_static()`；helper 在最终 freeze 不存在时移除空层级，再在 `finally` 恢复准确目录和 mode，恢复证明绑定最终清单。其后才生成 freeze 并取得 [最终 ready0](../raw/strict-native-phase-v3/task1/candidate-check-ready.receipt.json)。target 前后元数据相同由原 helper 和 receipt 证明，三项 `.once` 当前仍不存在。本审阅未运行负例、ready 或测试。

### 2.2 精确生成缓存

最终材料绑定 [精确补充](../design/phase2-native-cache-topology-v3-generated-cache-addendum-v1.md) SHA `cae498e3864857a19282d1d3238367e1ba84bc1883b74d85831dfed7c5995a07`、[独立补充审阅](strict-native-cache-v3-generated-cache-addendum-review-v1.json) SHA `7a54b78c549e79c94f2d007cabb6eac4d9f143b41d2dbd1f8104cbee3e9477c2`、[差异清单](../raw/strict-native-phase-v3/task1/post-prepare-unexpected-zephyr-cache.json) SHA `ed18aef34492553ded7763856eed42fdd4cb488706f75823fd4129da9d849aec` 和 [因果诊断](../raw/strict-native-phase-v3/task1/zephyr-capability-cache-cause.json) SHA `b863d65a1e58c8876f75a6554ad9591992edee5ba74cacc5e8fad53959bb434c`。当前 SHA、authorities 副本、reviewed-identities 和 freeze 的对应项一致。

独立比较现有父与最终 cache manifest，最终恰好接纳原 13 项重定位、45 个单字节能力结果和日志准确新身份；日志追加 27058 字节、45 行，新 SHA `fc299dd97eb043daa14b3f38f9f4f153ffd8dd5a01be4202a97f72c179339a76`。VIRQ 不可变项合计 54064，Cargo 108002 项逐项等于父清单，没有新增 runtime 例外。第一次 finalizer wait 1 与停止材料保留，精确补充发生在最终冻结前。

## 3. 归档与后续门

归档身份和错误历史均能从正式报告追到准确收据。Spec PASS 只表示 Task1 离线实施满足本轮规范；后续运行必须继续通过独立门禁。

### 3.1 归档和错误

工具 tar 当前 SHA 为 `8a64c8b14183c7124299cc2fa9d1e7dcfcc1fee826d368617875203a7892fc97`，30870837 字节。已落归档收据与实际归档 helper 证明 108 成员为 107 冻结项加 freeze 本身，逐成员 mode/size/payload SHA 已核；本审阅独立核归档整体身份，未重复读取全部成员 payload。cache/target 未包含，原始归档材料记录 210003658 字节，低于 1 GiB，临时 cache/target 容量另列。

初次普通源路径断言过宽、外部 GCC alias 身份比较错误，以及首次归档 `TarInfo.mode` 类型位比较错误都有原快照、输出、修复 diff 和准确退出记录；初次 exec 未单独采集直接 Popen wait 的限制明示。它们与首次生成缓存拒绝分列，均未被改称硬件失败或多次生产准备；归档改用 `stat.S_IMODE` 后真实 wait 0，未改冻结候选。

审阅只新建两份 review，未执行 build、prepare、ready、tests、Git、network、proc、signal、硬件或 QEMU，也未全扫主96、源文件或 cache 内容/哈希。操作偏差如实登记：最初定位 AGENTS 时一次 `rg --files` 包含工具根，遍历到了缓存路径名；没有读缓存内容或做哈希全扫，随后全部为定向读取，已即时告知 Root。定向只读一致性脚本实际退出 0。

### 3.2 验收边界

下一步是同一准确报告和冻结的 Quality 审阅，再由 Root 完成工具副本验收，包括真实只读 ready、单一执行根正式拒绝、实际 wait、无 marker 和 target 元数据绑定。Task2 的外部 normal 审计器同次运行身份与规定三处 Spec 阻断仍须修复并经 Spec→Quality；本次 PASS 不放行硬件。

正常 Host、容量零丢样、稳定交互、M2、Joint、goal_complete 和本次硬件授权均为 false。Root 的单次 AB1 准确批准、fresh host witness、Cargo runtime 快照、原预算与后续 AB0/0 顺序继续适用。
