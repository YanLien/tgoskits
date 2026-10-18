# strict native cache v3 AB1：控制器退出根因调查

原 AB1 仍是失败停止：Root 原 tool session 77494 / chunk 36f9ce 实际退出 1，driver 原父进程 `Popen.wait` 实际返回 1，xtask 退出码仍未知，`outer_timeout=true`，release unknown。AB1 配额已耗，AB0/0 未执行。本调查没有实现修复，也没有重跑硬件。

已证实的问题是：控制器把启动后立即采集的可变 argv 当作 cleanup 的永久身份条件，并在最后一次 poll 尚无结果时继续采证，之后不再显式收集原子进程退出状态。合法 exec 可以触发同样的拒绝；历史 AB1 到底变成哪个 argv 仍没有证据。

| 证据 | 实际结果与边界 |
| --- | --- |
| 冻结 `native_once.py:299-304` | 原 Popen 启动后立即记录 argv，再执行总预算 920 秒内的真实 wait。原 argv 与 expected 一致，实际是 20 项。 |
| `cleanup_owned:189-205,216-223` | 相同 PID/starttime/PGID 的 leader argv 不同即报 `owned group leader argv changed`；比较发生在 token 核验前。原拒绝没有保存实际新 argv/exe。该初始拒绝路径在首个 killpg 之前；这是源码控制流推导，不是独立信号 syscall 回执。 |
| `run_once:319-345` | 拒绝后仍有一次 `child.poll()`（322 行），所以“拒绝后从不再 poll”不准确；该次仍为 None。capture 与 static verification 后没有下一次显式 poll/wait。 |
| Cargo／项目入口 | launcher cargo 符号链接指向 rustup；`.cargo/config.toml:15` 的 xtask 是 `run -p tg-xtask --`。原 log:2 确有 target/debug/tg-xtask 启动记录，不能据此定位原 leader 的 exec 身份。 |
| 固定已安装 Cargo 的局部 strace | 仅运行一次隔离 `cargo --version`，同一 trace PID 从 rustup launcher exec 到固定工具链 Cargo，argv[0] 变为绝对路径，原 parent 真实 wait0。该次没有调用项目 alias，也不能还原 AB1。 |
| 自身新 Python Popen child | 合法 os.exec 前后 PID/starttime/PGID/token 相同；冻结函数 AST 未改，得到相同 argv changed。测试只把 `/proc` 枚举视图限制为该新 child，实际 stat/cmdline/environ 均来自内核；无宿主扫描、无信号，原 parent 真实 wait23。23 是局部测试退出码，绝非硬件退出码。 |

按原源码和结果可以确定如下路径：总预算 wait 超时 → finally cleanup 的首轮身份证明拒绝 → 存 cleanup unknown → 322 行 poll 仍 None → 继续 capture/static verification → 保存 None 并返回 1。超时错误已经足以要求 driver 失败；后来即使子进程成功退出，也不能恢复本轮成功或历史 release。

完整 raw log 记录两策略 phase ACCEPT、42768 条 frozen 事件（dropped0 / incomplete0）、`AXTEST_SUITE_OK` 以及 board stage done856.03s。普通源码 `context/mod.rs:481-487,509-515` 只在内部 board 调用返回 Ok 时打印 done；这不是原 Popen 的真实终止记录，也不证明整轮在外层预算内完成。

nonce 标记为 2026-10-18T12:43:41.988732487Z，加 920 秒约为 2026-10-18T12:59:01.988732487Z；该标记在 `start=time.monotonic()` 前，只可近似定位。capture 时间是 2026-10-18T12:59:02.040272962Z，raw 最终 mtime 是 2026-10-18T12:59:07.814214986Z（后约 5.773942 秒）。mtime 只说明文件写入时间，不能当作 Guest、板卡或进程退出的严格执行时间。capture 源码 432-434 行无条件写 `post-exit`，而本轮没有退出门禁支撑这个标签。

driver elapsed 为 955.909559556 秒，capture 为 6.273855062 秒。扣除 920 和 capture 后约 29.635704 秒没有分阶段计时，不能全部归为 cleanup，也不能把 driver elapsed 当作一次持续到终止的 xtask wait。

Root 在 2026-10-18T13:05:13.869986+00:00 已另行确认原 PID 消失、group 当时为空、board available1；这是后来的只读观察，不恢复原 xtask wait，也不证明历史 release。本调查没有再次观察或发送信号给原 PID/group。

仍不能证明历史 exec 目标、转变时刻、cleanup 时 token 是否仍存在、xtask 最终退出码、历史 release 成功或整轮正常功能验收。rustup 的真实 exec 行为支持一个具体机制，但不能直接认定它就是历史唯一成因。

最小下一步是由 Root 审查独立控制器候选的本地生命周期证据：精确列明并证明授权 launcher/exec 链，记录实际比较的 argv/exe 与 token 核验结果（不泄露 token），覆盖合法 exec、退出竞态、cleanup 拒绝与采证期间终止的真实父子进程路径。保留现有 board/outer/cleanup/capture/lease 时限和所有权约束；不要重用本轮配额，不把迟到的终止记录追认为本轮成功。该调查没有制作新候选。

原 final handoff SHA256：`cf25d62d4ff106f0e6d3315ce4e0b58ce5f4d78ac2e90b7b79fe814116e9b72f`。冻结 manifest SHA256：`0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8`；`native_once.py` SHA256：`8b871b1ea3cfb8a8ad8272bc7fa5ca37dc648b3efed45fe4af9ae0f374a24902`。43 项已有证据／源码／控制器的字节与元数据前后完全一致。

原始局部证据位于 [controller-cause-v1](../raw/strict-native-followup-v3/controller-cause-v1/)，包括脚本、真实 execve trace、真实 wait 回执、源码行号事实及前后 SHA 清单。[JSON 报告](strict-native-cache-v3-AB1-exit-cause-v1.json) 保存各引用精确 SHA 和全部限制。局部诊断命令工具 chunk f38982 实际退出 0；没有 board/QEMU、主源码构建、Git 或宿主 `/proc` 扫描。
