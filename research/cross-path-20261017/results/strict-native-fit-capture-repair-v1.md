# 原生 FIT 捕获修订离线交付

新增独立副本已通过完整真实 AB1 post-exit 捕获合同，实际 `Popen.wait()=0`、`artifact_chain_complete=true`、`errors=[]`。待独立 Spec→Quality 审阅。原失败 capture 不回写。

修订仅允许缺内置 hash 并明确记录缺席，存在 hash 仍验证算法与值；追加 newc 保留递归元数据，只合并同权限空目录，空普通文件重复、类型和权限冲突仍拒绝。公开返回格式和所有原捕获尾门保持不变。见[最小 diff](../raw/strict-native-followup-v1/fit-capture-repair-v1/capture-repair.patch)。最终工具 SHA256 为 `e1e573ed9ecd8a1dd77c80d6a06fff3739e4fa8114815cc2b6b5c826206a14b2`。

| 证明 | 实际 wait 与结果 |
| --- | --- |
| 原完整合同 RED | 1，准确无 hash 拒绝 |
| FIT-only 完整合同 | 1，保留追加 gzip 重复目录拒绝 |
| 追加格式合同 RED→GREEN | 1→0；重复文件、类型和权限冲突仍拒绝 |
| 最终完整真实合同 | 0；外部 BIN/initramfs、准确 FDT、Host 嵌入/资源、rootfs、init AST、worker/compiler/build 和准确 AB1 case 全部门通过 |
| 单 payload 字节损坏 | 1，准确 `FIT bytes differ from actual kernel/initramfs` |
| 内置 hash 值损坏 | 检查 0，真实 `fit_components` 准确拒绝；正确 hash 对照接受 |

17 个 live target 工件在每次完整捕获前均与原保存 SHA/bytes 逐项一致。最终 rootfs 恰有 busybox、ordinary-load、init 三个普通文件，两份 binary 等于原字节，仅 init 内容变化，且等于实际 source AST。见[完整捕获](../raw/strict-native-followup-v1/fit-capture-repair-v1/full-green/capture.json)、[rootfs](../raw/strict-native-followup-v1/fit-capture-repair-v1/full-green/rootfs.json)与[实际命令和身份索引](../raw/strict-native-followup-v1/fit-capture-repair-v1/output-index.json)。

唯一真实跨档案重复是 `.` 空目录，两边均0755。依据[追加格式补充](../design/phase2-native-fit-capture-repair-append-format-addendum-v1.md)，离线材料预算调为768MiB；旧两层拒绝、首次 fixture 相对路径错误、一次子进程未启动的 ENOSPC 均保留。相对路径错误没有计为负例通过；后续实际负例在 FIT 绑定层准确拒绝。没有 mock 项目绑定规则。

| 结论边界 | 状态 |
| --- | --- |
| 原 capture 使用链 | false |
| 本次补充 post-exit 使用链 | true |
| 正常 Host 功能 | false |
| 原 Trace dropped | 19839 |
| release | unknown |
| 本次 hardware_tasks_started | 0 |
| M2 / Joint / goal_complete | false / false / false |

本次不提供签名、可信启动、boot前认证、PID1/drain 或释放证明。原 source、工具、cache、target、AB1 与 sealed 材料不改，未运行 Git、生产构建、板卡、QEMU、proc、signal 或正式分析。
