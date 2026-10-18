# 严格原生缓存 v3 Task1 Quality 审阅

本次独立只读 Quality 审阅结论为 **PASS**，阻断项与必须修订项均为空。结论只接纳准确 Task1 离线实现的质量；完整核对与证据 SHA 见 [JSON 审阅](strict-native-cache-v3-task1-quality-review-v1.json)。

## 1. 接纳身份

准确报告、候选工具和已完成 Spec 是同一条证据链。本审阅重新定向计算关键文件身份，并直接阅读实际代码及差异，没有执行候选函数。

### 1.1 报告与候选

[Task1 JSON](strict-native-cache-v3-task1.json) SHA 为 `e1ce19382c35cc1c7c791bf618b07c7ea2840aa6a284efebf1d7da44038a9e59`，Markdown 为 `a3f42ef837f6df2652e2f0699d06223e6ac91c550730c4372520588ee5ba184d`；[Spec JSON](strict-native-cache-v3-task1-spec-review-v1.json) SHA 为 `996b32e95319ea5a3a94096b141153cf0b11b2bdaec39a8aea7de30e3cbd90f7`，Spec Markdown 为 `faccf08315e13b25afed8f35b761f3bd3cf9b138a153e32e5938fb33cc03d0be`。

source、tools、target 分别为 `/tmp/crosspath-native-cache-v3-src-hr23qnrs`、`/tmp/crosspath-native-cache-v3-tools-jrhcn15t`、`/tmp/crosspath-native-cache-v3-target-wg0fd7ru`。freeze 为 107 项，SHA `0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8`；capture 为 `61717a37b528e2e93d8cbcae1c1dafbc6249ac3417fbf0b8011b984a03a4c683`，controller 为 `8b871b1ea3cfb8a8ad8272bc7fa5ca37dc648b3efed45fe4af9ae0f374a24902`，inputs 为 `8fac8a1fb86d79a1e74bf9591bf68fa2dd88f6d261edcf0ea576dfbd6ace0060`。这些当前身份与正式报告及冻结项一致。主 HEAD `97f5bdecd0c24ed6f27da331ef036f76a519a949` 只采用任务给定上下文，未运行 Git。

### 1.2 差异与源

直接比较父/候选实际文件，`capture_native.py` 仅 `verify_static()` 变化，函数外全部字节与其他函数 AST 相同；`native_once.py` 仅输出根 v2→v3。原完整 FIT/newc、主96、所有权、单次、实际退出及 Root 精确批准逻辑保持。

9642 普通文件清单 SHA `f4bd9bb6dadd056e35faa2b3243a1be410a588f531f6bceb7d71c89e520e3c86` 和 702 源清单 SHA `0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb` 与父逐字节相同。完整源一致性采用已有实际 source/ready 证据；本审阅另核准确生产 prepare、sidecar 和 `run_host_prepare()` 源码身份。Rust 只继承实际 v2 fmt0、xtask Clippy29/29 的准确收据，v3 未重跑。

## 2. 目录保护

`verify_static()` 在原 `os.walk` 内增加目录身份收集，保持同一套接纳入口。目录差异可以直接拒绝缺失空目录，不再依赖文件集合推断其存在。

### 2.1 门禁与错误传播

目录清单 SHA 为 `dca2a114c1ec0241196d7d7e2163504239076f283ec034e8d39f5e97bc8e738e`，两组含根 `.` 的真实目录数为 9874 和 17749。组名、根路径、规范相对路径、真实目录类型与 `S_IMODE` 精确约束；目录被 symlink 替代明确拒绝，改成普通文件也因目录集合不符拒绝。比较位于该组缓存文件大 SHA 之前，复用原遍历，原文件、批准 symlink 与 Cargo 四种 bookkeeping 边界继续执行。

`native_once.main()` 在 `run_once()`、marker 和 Popen 前执行 `check_ready()`；目录错误沿原 `STRICT_NATIVE_NOT_READY` 退出2路径传播。[真实负例](../raw/strict-native-phase-v3/task1/directory-missing-refs-negative.receipt.json) wait2 的输出准确缺 `refs`、`refs/heads`、`refs/tags`，来自真实 `verify_static()`。helper 在 freeze 不存在时移除空层级，`finally` 恢复后另核完整目录与 mode，之后才生成 freeze 并取得真实 ready0；setup或恢复失败会阻止冻结。保存收据的 stdout/stderr 当前 SHA 与身份相符。

### 2.2 准备与精确缓存

`prepare.py` 使用 `copytree(symlinks=True)`，只在新副本补五个已观察的 0775 Git 空目录；13 项 venv diff 仅换准确前缀。生产 `verify_zephyr_source()` 仍调用真实 Git 检查固定 revision 和 clean tree。现有完整 host_prepare 父 wait0、72.17154478497105秒、预算300秒，准确 argv/cwd/AB1白名单环境相符，只增加原控制器式所有权 token。390字节 init 与已知 worker 的 rootfs 验证仅证明准备资源。

直接比较已落父/最终文件 manifest，VIRQ 恰为父54019项覆盖13重定位和一份log新身份，再加45项，最终54064项；Cargo108002项逐项全同。45个能力结果与追加27058字节/45行的日志已由[精确补充](../design/phase2-native-cache-topology-v3-generated-cache-addendum-v1.md)和[独立补充审阅](strict-native-cache-v3-generated-cache-addendum-review-v1.json)批准并进入不可变清单。当前补充/差异/因果报告的 SHA、authorities 副本、reviewed-identities 与 freeze 一致，Cargo runtime 策略完全继承，未增例外。首次冻结拒绝 wait1 与首错原样保留。

## 3. 封存与后续门

封存和错误历史能追到准确报告；离线 Quality 接纳不能替代后续独立运行验收。

### 3.1 证据完整性

本审阅新核准确报告、Spec、freeze及8个关键冻结项，107个相对路径安全。完整83条证据、107冻结项及108个tar payload的 SHA/size/mode 与路径安全承接 Root 已实际执行的[复核收据](../raw/strict-native-phase-v3/task1/root-evidence-check-v1.json)，其当前 SHA 为 `986826edcf3a4b1b11b1d1525f16b4036c1181bc9c1909cb84c3a2a1dce115fd`；本审阅未重复读取全部tar payload。`complete_report.py` 归档集合只为107项加freeze，无cache/target；tar SHA `8a64c8b14183c7124299cc2fa9d1e7dcfcc1fee826d368617875203a7892fc97`、30870837字节，原始材料210003658字节，小于1GiB。

两项prepare前helper错误、generated-cache首次拒绝、TarInfo.mode比较错误均分别留有首错、修订和退出记录。归档使用 `S_IMODE` 的纠正只改离线权限比较，最终helper实际wait0。原v1/v2失败与已耗marker由保护收据承接。存在一条低优先级维护备注：`prepare.py::command()` 的“成功路径不读/proc”注释与spawn后记录准确自持PID的代码不一致，正式报告披露正确，不影响接纳。

### 3.2 接纳范围

定向只读一致性核对实际exit0（chunk `b9ebc1`），准确源码/继承收据核对亦exit0（`e1fd1e`）。本审阅只新建两份Quality报告，未运行build、prepare、ready、tests、Git、network、proc、signal、板卡或QEMU，未扫描cache/源/主96树。一次定向源码路径猜测返回不存在，随后从已有ordinary清单定位准确路径；未发生扫描或写入。

本次 `Task1_quality_accepted=true`。Root 工具副本验收仍须完成真实只读ready、单一执行根正式拒绝、准确wait、无marker与target前后metadata绑定；Task2外部normal审计器同次运行身份及规定三处Spec阻断须另行修复并经Spec→Quality。Root 单次硬件批准、准确v3 cache/input/freeze绑定、最近Cargo runtime快照、60秒fresh host witness与原预算继续适用。Task1最终独立接纳、正常Host、容量零丢样、稳定交互、M2、Joint、goal_complete及本次硬件授权均为false。
