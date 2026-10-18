# v3 生成缓存冻结补充独立审阅

结论：**PASS，无阻断，可继续当前未冻结候选的原 Task1 剩余步骤。** 审阅绑定[补充最终字节](../design/phase2-native-cache-topology-v3-generated-cache-addendum-v1.md)：3958 字节，SHA256 `cae498e3864857a19282d1d3238367e1ba84bc1883b74d85831dfed7c5995a07`。原计划 SHA `5e355eb109871df9791d85953ff158dbe54b7416f615aea5a27b3d866e8eeb7d` 继续适用，详细证据身份见[同名 JSON](strict-native-cache-v3-generated-cache-addendum-review-v1.json)。

## 1. 证据判断

补充处理的是同一次成功 production preparation 的有限生成产物。原 helper 对未批准差异停止冻结，符合原计划；明确解释和审阅这些产物后，才可登记最终不可变身份。

### 1.1 准确差异

定向读取差异清单中的 45 个准确文件，各为 mode0664 的一字节结果，44 个 `1`、1 个 `0`，SHA 与记录一致。父日志 26042 字节是新日志 53100 字节的准确前缀；新增27058字节、45行。每行 `key_string` 的 MD5 与对应文件名一致，结果与文件内容一致，并含新工具链绝对路径，45 行与新增45文件构成一一对应。

新日志 SHA256 为 `fc299dd97eb043daa14b3f38f9f4f153ffd8dd5a01be4202a97f72c179339a76`。MD5 用来核对 Zephyr 的实际 key 命名规则；冻结完整性继续使用 SHA256，没有以 MD5 替代证据身份。

### 1.2 源码与执行

三份实际 CMake 源码的 SHA 均与补充相符，字节与容量 v2 父 cache 相同。`user_cache.cmake` 选择缓存路径，`target_toolchain_flags.cmake` 将编译器内容与绝对路径/ID/version 纳入签名，`extensions.cmake` 将签名、语言、选项和 required flags 形成 key，写能力结果并追加日志。新路径生成新 key 与已观察差异相符，没有修改该机制。

保存的完整 `host_prepare.receipt.json` 为真实父 wait0、耗时72.17154478497105秒，argv/cwd 与补充相符；stdout/stderr 的当前大小和 SHA 与同次收据一致。本审阅没有重跑准备。原 `finalize.first-error.json` 及停止状态保留；当前准确工具根尚无最终 freeze 和三项 `.once` marker。

## 2. 继续条件

本补充可以在最终冻结前作出产物分类决定，无需先存在最终 freeze。接纳范围只覆盖已解释的准确45个结果文件及准确日志新身份。

### 2.1 最终冻结

实施者可继续原目录门真实负例、恢复、最终清单、freeze 和实际 ready0。最终材料须绑定补充、差异清单、因果诊断与本次审阅，保留第一次拒绝、helper 修订和 production preparation 原始收据。除此之外的不可变成员仍按原要求核对，新增未知差异继续停止。

完整文件和目录身份必须覆盖这些生成结果；未来缺失、增添或内容变化仍由 `verify_static()` 拒绝。不重跑 preparation、不删除新增文件、不回写父 cache，也不把 `.cache` 加入 runtime 例外。源702、普通树、Rust、worker、测量参数、压力变量、预算、单次规则及正常功能判据保持原要求。

### 2.2 验收边界

Task1 最终实现仍须独立 Spec→Quality 和 Root 工具副本验收；外部功能审计器的同次运行身份绑定缺陷继续单独修复。本次 PASS 只允许继续未冻结候选的剩余离线步骤，不批准真板，不证明正常 Host、零丢样、稳定交互、M2 或 Joint。

本审阅仅执行小文件与明确路径的只读一致性检查，未遍历大 cache 或普通源，未运行 build、prepare、ready、测试、Git、网络、进程操作、板卡或 QEMU。计划、补充、候选和父 cache 均未由审阅者改动。
