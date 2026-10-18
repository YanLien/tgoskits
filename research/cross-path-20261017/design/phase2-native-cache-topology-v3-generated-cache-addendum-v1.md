# v3 生产准备生成缓存的冻结补充

本补充针对[原 v3 计划](phase2-native-cache-topology-v3-plan.md) SHA256 `5e355eb109871df9791d85953ff158dbe54b7416f615aea5a27b3d866e8eeb7d` 的 Task1 中间停止。原计划和第一次冻结拒绝记录保持原字节。候选尚未最终冻结；本补充只明确接纳这次成功生产准备实际生成的有限文件，供最终不可变清单登记。

## 1. 已核证据

本次核验把实际准备退出与固定源码的缓存写入规则连接起来，限定可接纳的准确成员。

### 1.1 生产入口

真实生产入口为 `python3 virtualization/axvm/tests/guests/virq/prepare.py --linux-peer`，cwd 为 `/tmp/crosspath-native-cache-v3-src-hr23qnrs`。原父 `Popen.wait` 为 0，用时 72.171544785 秒；没有启动板卡。准确收据与输出见 [Task1](../raw/strict-native-phase-v3/task1/host-prepare.receipt.json)。

### 1.2 输出来源

[差异清单](../raw/strict-native-phase-v3/task1/post-prepare-unexpected-zephyr-cache.json) SHA256 为 `ed18aef34492553ded7763856eed42fdd4cb488706f75823fd4129da9d849aec`，[因果诊断](../raw/strict-native-phase-v3/task1/zephyr-capability-cache-cause.json) SHA256 为 `b863d65a1e58c8876f75a6554ad9591992edee5ba74cacc5e8fad53959bb434c`。差异仅限新工具根 `cache/vcpu-runtime-cache/zephyr/.cache/ToolchainCapabilityDatabase/`：

- 新增 45 个能力结果文件，各 1 字节，内容为 `0` 或 `1`，准确路径、模式及 SHA 由差异清单列出。
- 原 `log.txt` 从 26,042 字节追加到 53,100 字节，原内容保持前缀；新增 27,058 字节、45 行。新 SHA256 为 `fc299dd97eb043daa14b3f38f9f4f153ffd8dd5a01be4202a97f72c179339a76`。
- Root 重新读取了全部新增文件及追加行：每行 key_string 的 MD5 与新文件名一致、结果与文件内容一致、包含当前新工具链绝对路径，45 行与 45 文件一一对应。没有将 MD5 用作证据完整性哈希；最终身份仍为 SHA256。

固定 Zephyr 源码解释了这些产物：`cmake/modules/user_cache.cmake:32–98` 选择并打印实际缓存路径；`cmake/target_toolchain_flags.cmake:20–25` 把编译器内容及绝对路径/ID/version 纳入签名；`cmake/modules/extensions.cmake:1138–1232` 生成能力 key、写入结果并追加诊断日志。三份源码 SHA256 依次为 `ef232cd93f3645c098ec8efc3234caa4e5090cad3dab6c0edb9081a9b01c4c74`、`c6ab0156ed86133f8202b7cf31eaf0d7c2ad3775faa299e4b42e9c2fabee9615`、`2ab40de151bc73503c65e730df2f6962cfe8997b2f0d4d12b051fc138328af68`。Root 精准核验命令实际退出 0，工具输出 chunk 为 `021d98`；此前一次只读命令因猜错第三个源码路径退出 1，未修改任何候选文件。

## 2. 冻结边界

接纳发生在最终冻结前。`verify_static()` 的不可变文件及目录检查仍覆盖这些生成缓存。

### 2.1 准确接纳

实施者可在当前未冻结候选中，将上述准确差异作为生产准备的生成缓存接纳，继续原计划的目录负例、恢复、最终清单、freeze 与实际 ready。最终报告须绑定本补充、差异清单及因果诊断，核其他不可变成员不变，并保留第一次停止、helper 修订和生产准备的原始收据。

不得重新执行生产准备、删除新增能力文件、回写父 cache、把整个 `.cache` 加入 runtime 例外，或忽略未来变化。最终冻结须覆盖全部实际文件及目录；此后缺失、增添或内容变化仍由原不可变门拒绝。源 702、普通树、Rust、worker、测量参数、压力变量、预算、单次规则和正常功能判据保持原要求。若发现本补充之外的新差异，停止并记录具体成员。

### 2.2 验收范围

本补充只处理构建产物分类，不批准真板，不证明零丢样、正常 Host、稳定交互、M2 或 Joint。Task1 仍须完成原 Spec→Quality 和 Root 验收；外部功能审计器的同次运行身份绑定缺陷须另行修复。
