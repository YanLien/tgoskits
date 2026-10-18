# v2 功能审计工具检查点

`audit.py` 只读最终 handoff，`--handoff-sha256` 必须为 Root 通知的准确 SHA；用 `python3 -B` 运行。输出目录必须为本目录下不存在的新子目录。正常完整通过才退出 0；功能不通过退出 1；输入身份拒绝退出 2。`run_command.py <新收据名> -- python3 -B ...` 保存真实子进程 wait、传入环境和 stdout/stderr。

设计映射见 `DESIGN.md`。`source-identities.json` 固定本版 702/freeze 与具体纯解码、Host、生命周期和 ostool 源字节，禁止拿新源替旧证据回填。

当前仅有负例验证：

- `old-AB1-red-v2/report.json`：原真实 AB1 审计退出 1；两份真实 DATA 的纯 wire/已知工作量和两组各 32 T6 可复核，但 dropped=19839、suite 失败、使用链不完整、release=unknown 保持失败。`old-AB1-red-v1` 是本工具早一版的原始执行收据与报告，不覆盖。
- `new-v2-AB1-red-v1/report.json`：Root 最终 handoff SHA `30d2613204648b7ebd89a202ee642b725678c94c056dada23e58de34b88cdd91`；准确新源/工具/环境绑定通过，正常功能审计退出 1，任务/DATA/trace/工件皆缺失，实际 xtask/driver/Root 退出均 1，release=unknown。
- `test_audit.py` 两项工具检查退出 0：真实失败不被升级；真实 DATA 原件可解码且损坏 CRC 被拒绝。初始缺实现 RED 和中途语法错误均保留真实收据。

这不是正常端到端 GREEN。尚无成功真板日志验证完整成功路径，AB0/0 未执行；完整 Trace 导出、正常 suite、off/B0、完整 FIT/工件链和成功释放路径仍需将来准确版本的真实证据及 Spec→Quality 审阅。当前工具含完整门的实现候选，不宣称其正常覆盖已经被端到端证明。

不运行板卡、QEMU、构建、ready、proc、signal、网络或 Git；未修改冻结源/工具/cache、Root wrapper、Task1 报告和历史证据。没有性能、相位重叠或 I_AB 输出。Host、M2、Joint、goal 均不由此完成。
