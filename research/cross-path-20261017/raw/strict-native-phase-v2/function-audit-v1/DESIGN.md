# v2 正常功能外部审计映射

适用已批准计划 Task2；仅审计 Root 最终 SHA 绑定的 AB1、AB0、0，不启动任何目标。归档新增预算 100 MiB，引用原大文件，不复制整份历史日志。每个实际准备/审计命令由 `run_command.py` 的原始 `Popen` 调用 `wait()`，保留 argv、完整传入白名单环境、stdout/stderr 字节与实际退出。

| 条款 | 独立判定与保留证据 |
| --- | --- |
| 身份 | final handoff 的准确 SHA；新 702、新 freeze 与所用具体源码逐项绑定；实际 argv/env/cwd 与冻结 inputs 相等 |
| T6 | fair/fifo80 原始 1..32 不删端点、不重复，固定 4096 已知答案、ISR 与 Host 因果边界及同代 RT counter mapping |
| DATA/R | 两份真实原始 DATA 完整留存，AST 只提取 checksum/memory_sum/verify_work/decode_data 和其常量；2 snapshots/32 slots、CRC、规范 wire、工作量已知答案、R 全字段重算 |
| 时间域 | PLAN/ACK/ACCEPT 的 VM key/run/cookie 全相等；Linux/RT 映射频率同域；fence 原始计数、完整 64 probes 的交集及每个 snapshot/slot 的 250µs/4ms Host 判据 |
| A/B | sgi 窗口包含全部 B 与 T6；事件逐项顺序、checksum、固定网格、summary 与数目/skip0 一致。off 无压力事件/summary。B off 所有原始工作量零实际内存访问 |
| 生命周期 | 准确源码先 stop/join/Inactive 再后校时调用；每策略完整 after probes、RT COMPLETE、ACCEPT、独立 VM_GROUP_RETIRED，最后单一 FROZEN 两组已退休 |
| Trace/suite | dropped/incomplete0；逐 CPU 唯一连续 sequence；逐事件数量等于 FROZEN/runtime/recording summaries，物理 IRQ64；完整 begin/case/summary/suite，无额外失败或协议残尾 |
| 工件 | frozen capture 使用链 true 且 errors 为空；保存工件按 SHA 逐一读取；实际日志路径/FIT default payload/Host initramfs 嵌入资源及 Guest/RT/DTB/rootfs/worker 链独立核对 |
| 退出/释放 | xtask、driver、Root 真 wait 均 0，未 timeout/强停，owned group empty；冻结 ostool 显式 finalize/release 合同与 actual release 完整绑定 |

输出 `report.json`、`observations.jsonl`、`data.raw`、`diagnostics-errors.raw` 和 handoff 副本；每条观察保留原日志 line/offset/bytes/SHA、完整 DATA/R、错误及未验证项。Trace 保留按 SHA 引用及逐事件跨度，不复制大日志。不产出性能、相位重叠或 I_AB 数据。

兼容旧 handoff：`case_id`, `state=final`, `files.{raw,capture,run_result,root_wait,actual_command,freeze_manifest,frozen_inputs}`；每引用为绝对 `path/bytes/sha256`。新增 `source_702_sha256` 与 `tools_freeze_sha256`（也接受 `normal702_sha256`/`freeze_sha256`），Root 外层实际 wait 用 `root_wait.outer_wait_exit` 或 `actual_root_wait_exit`，`forced_signals=[]`。缺失视作未验证，不补 true。

验证先使用真实封存旧失败 AB1 拒绝与其真实 DATA 的纯 wire 解码，并对该 DATA 的损坏 CRC 作一个必要错误输入检查。这个 RED 不证明正常功能成功；新 AB1 只能在 Root 完全 wait 后以 final handoff 准确 SHA 审计。AB0/0 未执行时保留未验证。旧 dropped=19839/release=unknown 保持原状。
