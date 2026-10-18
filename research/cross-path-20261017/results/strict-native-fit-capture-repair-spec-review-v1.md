# 原生捕获修订独立 Spec 审阅

结论为 **PASS**，无 Spec 阻断项。认可范围是独立工具对已保存真实 AB1 工件完成 post-exit 补充使用链核验；后续仍须独立 Quality 审阅及 Root 当前身份接纳。详见[机器审阅结果](strict-native-fit-capture-repair-spec-review-v1.json)。

## 1. 合同实现

对照[设计](../design/phase2-native-fit-capture-repair-design.md)、[计划](../design/phase2-native-fit-capture-repair-plan.md)与[追加格式补充](../design/phase2-native-fit-capture-repair-append-format-addendum-v1.md)，最终补丁只改变两项格式假设。`capture_native()`、`parse_newc()`、`verify_rootfs()`、`verify_fdt_transform()`及其余模块 AST 与原工具一致。

### 1.1 FIT 使用链

[`fit_components()`](../raw/strict-native-followup-v1/fit-capture-repair-v1/repaired/capture_native.py)保留 default 组件选择，缺 hash 时明确保存 `hashes=[]` 与 `integrity_hash_present=false`。原有全部 hash 算法和值检查循环 AST 完全相同。`capture_native()`仍核外部 kernel/initramfs SHA、准确 FDT 转换、Host 嵌入和资源、rootfs、worker/compiler/build 与 AB1 case，全部通过后才置 `artifact_chain_complete=true`。最终工具 SHA256 为 `e1e573ed9ecd8a1dd77c80d6a06fff3739e4fa8114815cc2b6b5c826206a14b2`。

### 1.2 追加档案

`_newc_entries()`保留递归成员类型、mode、大小与payload；跨档案仅允许两边都是空目录且mode相同。空普通文件也属于禁止重复的载荷，嵌套gzip的文件/目录冲突和目录权限冲突仍拒绝；同档案重复、路径、link、截断、padding由未变的`parse_newc()`继续拒绝。公开`newc_members()`仍返回原flatdict。真实Host两档案唯一重复是`.`，两边均0755空目录。

## 2. 执行证据

独立核查[收据](../raw/strict-native-followup-v1/fit-capture-repair-v1/spec-review-v1/execution.json)实际 `Popen.wait()=0`，标准错误为空。[核查结果](../raw/strict-native-followup-v1/fit-capture-repair-v1/spec-review-v1/check-result.json)保存327项已读身份，重算204个索引条目、原89个封存文件和17个当前live/原保存/最终保存工件均匹配；另含索引自身，原材料连同报告共627614757B，低于768MiB。此轮只执行新身份/AST/收据核查，没有重跑产品capture或已有测试。

### 2.1 红绿与反例

保存运行的退出状态直接取自`run_command.py`的`process.wait()`收据，另核原始stdout/stderr与准确拒绝原因。完整合同调用真实`capture_native()`，hash与newc合同也直接调用真实接口，没有替换项目绑定逻辑。

| 保存运行 | 实际 wait | 结果 |
| --- | --- | --- |
| 原工具完整合同 | 1 | 准确无hash拒绝 |
| FIT-only完整合同 | 1 | 准确追加gzip重复目录拒绝 |
| 最终完整合同 | 0 | chain=true、errors=[]，全部原尾门通过 |
| 单payload字节损坏 | 1 | 准确FIT外部绑定拒绝 |
| 内置hash合同 | 0 | 正确值接受、损坏值准确拒绝 |
| 追加newc合同 | 1→0 | 同mode空目录接受，不同普通文件完整保留，三类负边界仍拒绝 |

独立字节比较确认负例FIT只有offset2584968一个字节改变，其他16个工件保持原SHA。该负例及hash合同执行于FIT-only候选；保留快照的`fit_components()`和`capture_native()`与最终工具AST一致，只据此复用相同逻辑的历史证据，没有声称最终整份工具重新执行过这些负例。

### 2.2 失败留存

首次fixture因相对path在`actual kernel is outside independent target`提前拒绝，原输出与wait1均保留，不计为payload绑定负例通过。准确绑定拒绝来自后续新目录。sandbox ENOSPC时子进程未启动，保存wait=null；后续启动恢复不能解释其根因，因此仍记为未知。原89文件seal及原失败capture SHA保持匹配。

## 3. 结论边界

此结论只批准Spec合同，没有解除原板卡停止条件。原capture使用链false、Host正常功能false、Trace dropped19839、正常逐事件导出0、releaseunknown；本次修订及审阅hardware启动0，M2、Joint、goal及阶段0～2整体均为false。

签名、可信启动、boot前认证、PID1/drain、释放与Trace修复仍无证明。当前未重遍历整个source/cache树；已核原工具、必要evidence、17live工件与89封存文件。本轮未改现存文件，未执行Git写入、构建、QEMU、board、proc、signal或正式分析，未访问另行清理的三个临时目录。接续独立Quality审阅后，由Root核当前身份决定此新工具的后续离线使用。
