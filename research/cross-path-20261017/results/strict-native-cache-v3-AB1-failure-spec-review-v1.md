# 新缓存 v3 AB1 失败交付 Spec 审查

本次结论为 `PASS_TRUTHFUL_FAILURE_EVIDENCE_ONLY`，无阻断项。审查范围严格为 `truthful failure evidence only`：AB1 实际失败记录、原始完成收据及原因报告如实保留局部通过和整轮失败，不能据此验收正常功能、修复、正式性能、M2 或 Joint。[机器审查报告](strict-native-cache-v3-AB1-failure-spec-review-v1.json)保存逐项检查和精确 SHA。

## 1. 审查范围

本审查把[失败交付](strict-native-cache-v3-AB1-failure-v1.md)、[最终 handoff](../raw/strict-native-phase-v3/AB1-root-final-handoff-v1.json)和[原正式 audit](../raw/strict-native-phase-v3/function-audit-v1/AB1-actual-audit-v1/report.json)视为相互绑定的证据，核对失败事实、完成收据和后续解释的边界。

### 1.1 核对方法

仅以保存文件进行 SHA256、字节数、JSON 字段、日志文本和本地链接解析。核心引用 73 个唯一文件、128 处绑定全部一致；独立 auditor 原因补充 42 个唯一文件、47 处绑定全部一致。18 个 Markdown 本地引用均存在。未启动板卡或 QEMU，未访问网络、`/proc`，未执行构建、信号、Git、整轮 audit 或成功测试复跑。

### 1.2 固定引用

核心结果的精确身份如下，所有引用都已重新读取并计算 SHA；源 702 和工具冻结标识在原 handoff、失败报告与正式 audit 中一致。

| 固定材料 | SHA256 |
| --- | --- |
| failure JSON | `133badac82f4ba3c620ea61104b5a56af3fa85d385a4bbd95066afd484e91531` |
| failure MD | `5b457379b22901a9d41ff2bc91c72b3e2728b0b810c0c60f4dd4413cd62805e1` |
| 原 final handoff | `cf25d62d4ff106f0e6d3315ce4e0b58ce5f4d78ac2e90b7b79fe814116e9b72f` |
| 原 audit report | `1a9257ef78caf570267dcb89c60d3143cf97dd033f9460b56176347f594d0b25` |
| exit-cause JSON | `66212f18d135e70e198b978717f160fe9161e6354e6421539f66dc10fc23df0f` |
| 原封存 exit-cause MD | `838fe924a162128a38517b1410b472effd5f76a7580b563e540338ebc96f6b62` |
| auditor-cause JSON | `ed4c51ed436cf7cf1673a74cbbcc02ec7c94bc16833f50187d3c297dce8b3ab8` |

原 `controller-cause-v1/SHA256SUMS` 的 20 项全部一致。原 exit-cause MD 保留封存字节；编号整理版另存，不替代原封存引用。全部输入、原 wait、tool completion、capture、raw 和工件引用的精确 SHA 保存在机器审查报告中。

## 2. 失败事实

原始数据可证明本次局部采集完成；整轮是否成功仍由退出和释放证据决定。`run-result.json`、`AB1-root-wait.json`、原 tool completion 以及正式 audit 的字段保持这一区分。

### 2.1 数据范围

原 `xtask.log` 为 6,496,391B，SHA256 为 `c74a5a24106e3e59a4c03316b428f9591e5e481bce5f65a874f4231b7d10814b`。实际 `VIRQ_RUNTIME` 文本行共 42,768 条，所需字段和行终止完整，各 CPU sequence 连续；`VIRQ_TRACE_FROZEN`、`VIRQ_RUNTIME_SUMMARY`、`VIRQ_RECORDING_SUMMARY` 均为 records42768/dropped0/incomplete0。

原正式 audit 的局部门记录 64 tasks、两份完整 DATA、fair/fifo80 两项 phase 协议通过及两项 pressure 通过；raw 同时保留两条 ACCEPT、两组回收与 suite pass1/fail0/OK。这些记录仅支持本次局部数据范围，不覆盖整体正常功能门。本审查没有重做协议审计或计算性能。

### 2.2 实际终止

原记录为 `outer_seconds=920`、`outer_timeout=true`、xtask `Popen.wait=null`、release unknown。原父进程 `AB1-root-wait.json` 的真实 driver wait 为 1；Root 原 tool session 77494、chunk `36f9ce` 实际退出 1。`run-result` 自身的 driver wait 空字段不代替外部原父进程收据。

final handoff 的 `forced_signals=null`、cleanup group 空状态 null 均保留。13:05 UTC 后来观察到原 group 为空、board available1，且该检查未发信号，只证明后来状态，不能补回原 xtask wait、历史 release 或历史无信号证明。AB1 配额已耗，AB0/0 未执行。

### 2.3 正式拒绝

原 auditor 子进程真实 wait 为 1；原 tool session 42886、chunk `9be3c5` 实际退出 1。原 24 门仍为 20 过、4 拒，`full_function_passed=false`，与 failure JSON/MD 一致。

| 原始拒绝门 | 保留结果 |
| --- | --- |
| same-run-launch-wait-completion-binding | xtask exit disagrees with final same-run binding |
| full-suite-no-additional-failure-or-tail | failure/diagnostic/unclassified error candidate or unframed final bytes observed |
| actual-artifact-use-chain | newc trailer/tail |
| actual-exits-and-frozen-explicit-release | xtask exit disagrees with final same-run binding |

两条 DTS Warning 候选的原始行号 24/52、偏移 2695/5173、各 228B 及 SHA 均已核对。格式兼容和日志分类调查独立保存，不改写这四项原拒绝，也不将生产 capture 的 `artifact_chain_complete=true` 追认为正式 use-chain 通过。

## 3. 解释边界

原因报告能说明拒绝机制和证据收集缺口，但本次交付仍保留历史未知。后续调查或局部探针结果不作为 AB1 的退出、释放或整体成功证据。

### 3.1 原因报告

冻结 `native_once.py:203-206` 的 argv 比较在 token 核验之前；拒绝后 `run_once:322` 仍有一次 poll，其结果为 None，之后 capture/static 与返回之间没有最终显式 poll/wait。`capture_native.py:427-434` 无退出条件而写入 `capture_phase=post-exit`，所以该标签不证明实际退出。日志 mtime 仅证明后续文件写入，不能给出 Guest 或进程退出的严格时刻。

exit-cause 把合法 exec、Cargo 探针和新 Python 子进程真实 wait0/wait23 限于机制证据，未认定历史 AB1 的实际新 argv 或唯一成因。auditor-cause 保持原 audit 失败，限定为 Host 拼接归档解析和 DTS 警告文案定位；其 USER_CACHE 实际路径与冻结离线 witness 不同，选择原因及 mutation 范围未知，本审查不认定 cache 一致或验收修订候选。

### 3.2 交付状态

failure JSON 的 `pending_cause_reports` 是创建时状态；exit-cause 和 auditor-cause 后续独立追加不要求回写该快照。当前根目录 README 和研究进度属于可变状态，不在本次冻结审查范围。本任务只新增本审查 JSON/MD，未修改任何原始证据。

失败交付没有生成或宣称正式相位性能、尾延迟、DMR、吞吐、M2、Joint 或整体研究完成。原正常功能、legacy、匹配开销及随机重复实验仍未完成；本审查通过只表示失败证据交付如实，不能作为修复或下一次运行的验收。
