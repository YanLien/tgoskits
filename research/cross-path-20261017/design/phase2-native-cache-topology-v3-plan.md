# 严格相位缓存目录修订 v3 计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development task-by-task.

**Goal:** 修复缓存副本丢失空Git目录的构建缺陷，在单独标识的新候选中验证完整生产准备入口，再恢复原定三项真板功能验证。

**Architecture:** 沿用隔离普通源、独占cache/target和单次控制器。全部Rust和普通源码保持容量v2字节，保留缓存目录结构，新增只读目录身份门；仅替换必要路径、准确身份和输出根。原v1真板失败、v2构建失败与已消耗marker不改。

**Tech Stack:** Python3 stdlib、固定Rust工具链、项目cargo xtask、原Zephyr/工具链/cache、RK3588板卡。

用户已连续授权阶段2、提交和推送；缓存修复属于既定方案中的实现纠错，不改变研究变量，无需再次询问继续。设计及离线实施仍先经独立审阅，正常Host功能与研究结果不能由准备报告推定。

## 1. 缺陷与选择

[新v2失败报告](../results/strict-native-trace-capacity-v2-AB1-prepare-failure-v1.json)SHA为`f142c02ec9ff99d4db01cbc409cfa35ffb3933d77b0e435e3dc13c1f762044c5`。真实xtask、driver及原统一exec均退出1，失败发生在申请/启动证据之前的`host_prepare`；没有新Guest或Trace，release保持unknown，AB0/0停止。

### 1.1 因果证据

`task1/prepare.py::copy_manifest()`复制文件与symlink，以文件父目录重建树，遗漏空目录。新cache的25份Git文件虽匹配，缺少`.git/refs`，Git拒绝识别仓库。Root在[独立临时元数据副本](../raw/strict-native-phase-v2/zephyr-git-readonly-diagnosis-v1/empty-refs-causal-proof.json)仅增加空refs目录后，真实rev-parse由128变0，固定revision为`32229d0b6cc60a1906307311b8e79ec483ad1e88`，真实只读工作树status为空；元数据文件字节未变，原cache仍拒绝128。

该实验只解释Git构建入口失败，不证明追踪容量或正常Host通过。旧cache缺失的已观察目录为branches、objects/info、refs、refs/heads、refs/tags，权限均0775；它们来自当前只读父cache的实际目录观察，旧平面文件清单并未历史冻结目录身份。

### 1.2 方案取舍

采用保留目录的`shutil.copytree(..., symlinks=True)`复制新副本，补齐经核实的五个空Git目录，再为新cache全部真实目录冻结独立身份。这保留既有缓存与工具链，避免重新下载或改生产Git校验。仅补当前失败cache会覆盖冻结历史及已消耗额度；跳过Git校验会削弱固定来源条件；两者均不采用。

新目录门直接进入`capture_native.verify_static()`，与原文件/链接门共用现有os.walk，不引入另一套硬件运行器。完整FIT/newc/工件捕获函数保持已接纳修复的字节；capture新SHA必须单独审阅，不能继承旧SHA为新批准。

## 2. 身份与边界

新候选原始输出根为`raw/strict-native-phase-v3/`。目录修复是构建环境版本变化，Rust测量协议与容量保持v2；它不授予失败v2重试额度。

### 2.1 文件范围

父普通源为`/tmp/crosspath-native-capacity-v2-src-z2au9vz8`，702清单SHA为`0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb`，普通树清单SHA为`f4bd9bb6dadd056e35faa2b3243a1be410a588f531f6bceb7d71c89e520e3c86`。从此树创建新的`crosspath-native-cache-v3-src-`普通副本，准确9642文件与702源不变。

父工具为`/tmp/crosspath-native-capacity-v2-tools-ksjtks3x`，freeze SHA为`6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9`。新工具、target分别用`crosspath-native-cache-v3-tools-`、`crosspath-native-cache-v3-target-`前缀mkdtemp。父源码、工具、cache、target、失败材料和用户询问清理的三个目录不写入。

新建`raw/strict-native-phase-v3/task1/`保存实施、准确argv/env/wait、目录manifest、cache入口重定位差异、源码/控制/工具清单及最小补丁；报告为`results/strict-native-cache-v3-task1.json/md`。归档预算1GiB，临时cache/target另按实际登记；不复制整批历史研究结果或删除旧证据。

### 2.2 目录身份门

新增`evidence/cache-directory-identities.json`，以现有`cache-identities.json`和`cargo-cache-identities.json`两个名称分组，记录对应cache根及每个非symlink目录的相对路径与`stat.S_IMODE`，根路径记`.`。必须与现有os.walk的实际目录集合、类型、模式完全匹配。路径须规范化，拒绝绝对路径、`..`、不规范形式和目录symlink替代；现有文件及批准symlink检查继续生效，Cargo runtime例外仍仅为原四种bookkeeping文件。

目录检查复用文件清单现有遍历，在大文件hash之前拒绝缺目录。冻结清单绑定新的目录manifest与capture字节；原ordinary/source/external/主96/单次/所有权/退出门不弱化。生产`verify_zephyr_source()`仍执行真实Git固定revision和clean-tree验证。

## 3. Task1离线准备

本任务不启动板卡或QEMU。先由新实施者准备，之后独立Spec→Quality、Root工具副本检查；不把任何离线通过称为正常功能或零丢样。

### 3.1 副本与缓存

- [ ] 读取新v2实际失败、因果证据及父输入身份，核可用空间；记录保护材料开始SHA，不重扫完整主96封存。
- [ ] 创建普通源/工具/cache/target新路径。普通源按父普通树精确复制；cache以copytree保留现有目录/模式/批准symlink，不带凭证或新Cargo配置。以原平面清单核父及新不可变文件，Cargo bookkeeping前后另列。
- [ ] 在新Zephyr `.git`副本补齐上述五个空目录，先核父对应项确为目录、模式相符且无额外文件。不修改原cache，不做git init/clone/fetch，不删除旧marker。
- [ ] 仅在新venv入口及metadata做v2前缀→v3前缀重定位，沿用13项精确替换边界；保存全部diff/mode/SHA，vendored源码、site-packages算法、工具链和ELF不改。真实新Python prefix/module/CMake binary及直接cmake入口须归新cache，实际wait0。
- [ ] 保留真实Git命令的RED128来由，在新cache执行同一个`git -C <zephyr> rev-parse HEAD`及`status --porcelain`，要求固定revision、clean且实际wait0。不得以文件SHA或人工填HEAD替代真实Git入口。

### 3.2 生产准备与回归

完整Host-preparation CLI缺少独立xtask入口，已读取`ktest::run_board()`与`axvisor/test/guest_build.rs::run_host_prepare()`：准备先于Host build和`board_prepared_elf()`，`guest-builds.toml`的准确argv为`python3 virtualization/axvm/tests/guests/virq/prepare.py --linux-peer`，cwd为普通源，`AXBUILD_TARGET_DIR`为独占target。单独执行该同一argv只构建Zephyr/Linux资源，不构建AxVisor或请求板卡；不使用原生Cargo。后续完整板卡运行仍只能走原cargo xtask入口。

- [ ] 以空继承环境加冻结白名单和AB1环境，在新source执行上述真实完整host_prepare一次，保存env、stdout/stderr、准确父Popen.wait及实际生成资源/RT ELF/BIN/DTB、Linux build.json/rootfs/worker身份。全部固定配置及known worker不变，不能只运行到Git函数就宣称完整准备通过。
- [ ] 离线prepare总预算300秒；若timeout，只按原`native_once.cleanup_owned()`对准确自持start_new_session子进程组和唯一token做原10秒清理，保存实际wait及未知项，不信号旧进程/外部工具，不自动再跑。任何缺输入、下载、源码变动或意外cache变化均停止冻结。
- [ ] 所有Rust/Cargo.lock/普通文件与父相同，因此继承v2真实fmt0和项目Clippy29/29的准确收据，字段明确“未在v3重跑”；本修复不改变Rust，不为参数或路径迁移重编全部功能矩阵。实际目标构建和运行证明仍由后续单次xtask取得。
- [ ] 复制已批准capture副本，仅在verify_static增目录身份门；controller仅输出根v2→v3，其余所有权/单次/完整主96/真实wait规则逐字节保持。
- [ ] 复用或增强原只读AUDITED_ENTRY实际入口：在最终freeze前对实际暂存cache移除空refs，调用新capture的真实verify_static或真实check-ready入口，要求在新目录门明确拒绝（尚不需要走到末尾freeze读取）；再恢复准确目录/模式，原文件hash不改。实际最终ready0在3.3节冻结后执行。此为新门的局部环境回归，不模拟Guest或录制器，不重跑旧cleanup矩阵。负例恢复后生成最终准确manifest/freeze，不改已冻结记录。

### 3.3 冻结与独立验收

- [ ] 完成host_prepare及入口证明后，再生成完整新cache文件和目录身份；记录新增/变更成员，任何非允许变化须解释并停止静默继承。源702及普通树SHA应与父完全相等。
- [ ] 生成新freeze、inputs、控制/目录/缓存清单及tar、明确父子关系和最小补丁。旧v2目录、source、freeze及原失败保持字节。
- [ ] 新候选实际ready需要最终freeze；目录负例在最终freeze前的可恢复副本操作，或在另一个完整独立测试副本中操作，并明确输入SHA。不能修改冻结原执行root来取得负例。
- [ ] 交独立Spec，再Quality；Root准确身份复核后复制冻结工具（不复制缓存），真实只读ready通过，副本正式执行按单一执行根拒绝，保存实际wait、无marker及target前后状态。只认可离线准备。

## 4. Task2真板与继续条件

[原严格真板计划](phase2-strict-native-verification-path-plan.md)3.1/3.2继续为完整正常判据，source702保持本次准确SHA，tool/inputs/capture/freeze必须换成真实新SHA。外部正常审计工具的三处Spec阻断在新副本修复并经Spec→Quality；无正常端到端GREEN时明确标注，真实新AB1可提供该正路径验证，失败则仍拒绝。

### 4.1 单次启动

Root准确复核离线验收、当前真实宿主无竞争及服务可用性，为新AB1登记一次准确输入。Root successor wrapper继承已审阅`1558c98da`中的finally实际wait和精确target metadata绑定，预存target现为真实prepare结果，不能套旧“target必须不存在”。Cargo runtime approval取最近真实ready快照，不能填空字典。

板卡900秒、总920秒包含本次build/request/upload/run，cleanup10秒、capture30秒及512MiB捕获预算保持。fresh host witness仍60秒，若因真实门耗时过期则拒绝，不放宽界限。先AB1，完整正常功能/实际退出/工件链/释放及Spec→Quality后才AB0，再0，各项最多一次。任何失败、未完成或release不明均停余项，不能在同一候选重试。

### 4.2 后续研究

全部三项真板通过后才另做原legacy生命周期RED/GREEN、完整Host交付、同版本匹配开销、相位分析及随机重复四组。稳定均值交互及不确定性由重复数据判断，分位数非加性不证明耦合；机制未成立不实现Joint。最大观测时延不称严格WCET/WCRT，PMU及带宽控制能力不作假设。

## 5. 文档与交付

正式材料保存在用户指定根目录树内，当前README与研究进度同步反映实际状态。源码英文注释说明目录语义和身份边界，历史报告不回写。

### 5.1 提交与复现

已推送的8笔提交保持；新修复按精确已验收文件提交，不混入无关工作区修改。原始Trace、完整cache和构建目录仍按本地报告保存，不宽泛git add。源码/工具补丁、必要manifest、验证收据和报告保留可复核身份；本任务无合并授权。

### 5.2 状态解释

离线Git/host_prepare成功只修复构建可用性。真实容量丢样、正常Host、M2、Joint及阶段0～2整体仍须各自真实证据；本计划与任何准备报告均不改变这些状态。
