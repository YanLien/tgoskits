# 原生捕获修订独立 Quality 审阅

结论为 **PASS**，阻断项为空。范围仅为已完成的离线 FIT/newc 消费方修订及保存合同证据。先独立核 Spec JSON/MD 当前 SHA，确认 `decision=PASS`、`blockers=[]`；未参与实施或 Spec 结论。机器结果见[Quality JSON](strict-native-fit-capture-repair-quality-review-v1.json)。

## 1. 代码质量

完整阅读最终 `capture_native.py` 与最小 diff，并独立重算 AST 边界。只有 `fit_components()`、`newc_members()` 被改，新增 `_newc_entries()`；其余模块 AST 保持不变。补丁与原/最终文件生成的 diff 逐字匹配，修改范围足够小且职责清楚。

### 1.1 FIT 身份

[`fit_components()`](../raw/strict-native-followup-v1/fit-capture-repair-v1/repaired/capture_native.py)保留 default 三组件选择与原 hash 算法/值循环。`hashes=[]`、`integrity_hash_present=false` 明确记录缺席；payload SHA 只说明字节身份。`capture_native()`仍须通过外部 BIN/initramfs 和准确 FDT 转换，再通过 Host 嵌入/资源、rootfs/init、worker/compiler/build 与 AB1 case 全部尾门，才能设置链完成。

最终工具 SHA256 为 `e1e573ed9ecd8a1dd77c80d6a06fff3739e4fa8114815cc2b6b5c826206a14b2`，diff SHA256 为 `27e636d38a3fd259d396516cffb34e5e0ab925190c812db6d58cb22d9d6a3532`。没有把无 hash 表述为已验证内置 hash、签名或 boot 前认证。

### 1.2 递归档案

`_newc_entries()`在 raw/gzip 递归中同时传回成员元数据与 payload，两路均经过同一个 `merge()`。先检查全部交集后更新，仅双方为目录、大小均为零、mode 相同才放行；同名空普通文件、类型冲突和权限冲突仍拒绝。重用目录的后写不会覆盖有效文件内容，`newc_members()`继续返回第二项 flatdict。`parse_newc()`原有路径、link、同档案重复、截断和 padding 判定均未改变。

## 2. 证据质量

新增[独立核查](../raw/strict-native-followup-v1/fit-capture-repair-v1/quality-review-v1/inspection-result.json)核了 50 个相关文件身份和 8 份保存收据，未重新遍历全索引、source/cache、17 工件或 89 seal。Spec 已完成这些身份核查，Root 也已 fresh 核引用与 AST；Quality 将精力集中于完整代码、递归规则和证据表达。

### 2.1 实际执行

本轮唯一核查子进程由 `run-inspection.py` 调用新增 `inspect.py`，保存的[收据](../raw/strict-native-followup-v1/fit-capture-repair-v1/quality-review-v1/inspection.execution.json)直接取 `process.wait()`，实际为 **0**，stderr 为空。只执行新身份/AST/保存收据检查，没有调用 capture 或重跑既有测试。所有输入 SHA 在核查结果中保存。

### 2.2 合同与历史映射

完整合同和最小 FIT/newc 合同均调用真实接口，没有 mock 绑定规则。按 `test-quality` 判定三类合同均保留：完整合同保护真实保存格式与全部尾门，组件合同保护缺 hash 放行后的校验及目录合并边界，旧 mock package 证明不能提供这些信号。

| 保存合同 | 实际 wait | 审阅结果 |
| --- | --- | --- |
| 原完整合同 | 1 | 准确无 hash RED |
| FIT-only 完整合同 | 1 | 准确重复 gzip 目录 RED |
| 最终完整合同 | 0 | chain=true、errors=[]，完整尾门 GREEN |
| 追加 newc 合同 | 1→0 | 同 mode 空目录接受，三类冲突仍拒绝 |
| 内置 hash 合同 | 0 | 正确值接受、损坏值准确拒绝 |
| 单 payload 字节负例 | 1 | 准确外部 FIT 绑定拒绝 |

历史 `argv` 中的 `repaired` 路径曾指向 FIT-only 候选。快照/checkpoint 绑定该 SHA，且该候选的 `fit_components()`、`capture_native()`与最终 AST 相同；`newc_members()`则与原版相同。因此仅复用相同逻辑的历史证据，不称最终整份工具重跑过这些负例。首次 fixture 路径错误 wait1 只留诊断，不计绑定负例；准确拒绝来自后续新目录。ENOSPC 时子进程未启动，根因仍未知。

## 3. 接纳边界

Quality 无阻断项。Root 接纳当前交付身份后可将本离线修订按批准范围接续；用户新授权的代码提交由 Root 独立处理，本审阅没有 Git 写入，也没有改动任何既有文件。

原 capture 链仍为 false，只有本次 supplementary post-exit 链为 true；正常 Host 功能 false、逐事件导出 0、原 Trace dropped19839、releaseunknown，hardware 启动 0，M2、Joint、goal 与阶段0～2整体均为 false。签名、可信启动、boot前认证、PID1/drain、释放和 Trace 修复仍未证明。本轮未运行构建、QEMU、board、proc、signal 或正式分析，未访问另行清理的三个临时目录。
