# 严格真板追踪容量 v2：Task1 离线准备

离线准备通过，等待独立 Spec→Quality 及 Root 复制检查。`hardware_started=0`、`qemu_started=0`；本报告不是板卡启动批准。

唯一 Rust 修改为 `virtualization/axvm/src/diagnostics.rs` 的容量 16,384→65,536 及英文测量说明。702 项中另 701 项和其余普通树字节、模式均保持父版本；`Cargo.lock` 与三份板卡控制 TOML 不变。四 CPU 槽位存储从 2.5 MiB 变为 10 MiB，是测量版本变化，未证明零丢样，后续开销须重新进行同版本 matched recording-on/off 测量。

- source：`/tmp/crosspath-native-capacity-v2-src-z2au9vz8`
- tools：`/tmp/crosspath-native-capacity-v2-tools-ksjtks3x`
- 独占 target：`/tmp/crosspath-native-capacity-v2-target-j4ca0hcp`
- 新 702 清单 SHA：`0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb`
- 新 702 tar SHA：`072c67c53641c3428ddfaa031692a506443105b0a023376dff90e307e1f8f29d`
- 候选 freeze SHA：`6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9`

新副本仅重定位 venv/bin 执行入口、激活脚本及 pyvenv.cfg 中实际存在的严格工具和历史 workspace 前缀。13 份修改保存准确 SHA/mode/diff；vendored Zephyr、工具链、site-packages 算法及 ELF 保持原字节。新 Python 入口的 sys.prefix、cmake 模块及所选 binary 均归新 cache；真实宿主解释器仍为批准的 `/usr/bin/python3.12` 链接目标。直接 exec 新 venv/bin/cmake 与 Python -B 探针真实 wait 均为 0。

首轮真实 readiness 因原固定路径下 kernel/base initramfs 缺失而拒绝 2，外层阶段退出 1，原收据保持原字节；丢失原因未知。Root 从 `configs/reproduction-base-inputs` 将同 SHA/大小/mode 的两份归档资产恢复到原路径，没有下载或重建。恢复记录为 `raw/strict-native-phase-v2/base-input-restoration-v1.json`（SHA `a0d90cb91d8ad68a16af12b92598f7eadd758b1965811cc504f764ef1af1142f`）。当前复验位于 `readiness-after-assets-v1/`，冻结身份未变，未回填旧正常功能或 release。

`cargo fmt -p axvm` 和 `cargo xtask clippy --package axvm` 真实 wait 均为 0。随后复核完整 9,642 普通文件、701 父源、锁文件和 Cargo/VIRQ immutable cache；Cargo bookkeeping 前后单列。真实 `native_once.py --check-ready` 的静态和主96完成门通过；正式入口错误 source 与错误 approval 均拒绝 2。复用原 AUDITED_ENTRY 限制写入、网络、子进程、signal，前后 target 状态相同，无 `.once` 或 AB1/AB0/0 输出。旧 offline-check 的“主96尚未完成”假设没有复用。

controller 仅有输出根 v1→v2 一处差异，AST 比较通过。capture 与已批准修订逐字节相等。新工具冻结副本及必要证据在 [task1](../raw/strict-native-phase-v2/task1/)；准确命令、环境来源、实际 Popen.wait 与 stdout/stderr 见该目录各 receipt。父工具、父普通源、父 cache 与列明保护证据开始/结束一致；未额外扫描全96封存。

普通宿主验证=false；真板容量修复已证明=false；M2=false、Joint=false、goal=false。新三项均未执行，旧 AB1 仍失败。后续必须先审阅当前准确身份，再另行取得 Root 单项硬件批准。

末次报表 helper 曾因重复解析 Cargo manifest 而拖长；该 helper 属于未冻结的离线审计脚本。Root 只对这个新 helper 做 host/proc 身份核验及一次精确 SIGTERM，原统一 exec 实退 143（没有自定义 Popen 父 wait）。修正版由父进程持有 Popen，真实 wait=0。实施者没有读 proc 或发 signal；板卡、runtime、旧进程、parent 与进程组均未 signal。原加载脚本明确保存为 reconstructed copy，首轮 partial 与停止证据保留；候选冻结未变。
