# 严格相位追踪容量修订实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development task-by-task.

**Goal:** 以最小容量变化交付可独立核验的新测量候选，随后按准确新身份逐项取得真板功能证据。

**Architecture:** 从原严格真板702普通树创建新副本，保持701份源不变；复用原单次控制器及已批准捕获修订，在新路径冻结源码、工具、缓存与输入，不改原失败和主树。

**Tech Stack:** Rust2024固定工具链、项目`cargo xtask`、Python3 stdlib、真实RK3588板卡。依据[容量修订设计](phase2-native-trace-capacity-v2-design.md)。

## 1. Task1离线候选

本任务仅准备，不启动板卡或QEMU。设计/计划独立审阅及捕获修订Spec→Quality均通过后，由新实施者执行；候选完成先Spec后Quality，Root再独立复制核验。不得以离线通过声明容量问题已经修复。

### 1.1 文件与来源

输入源`/tmp/crosspath-strict-native-src-ii_h4jde`，父702清单SHA为`9e2fe24f40d95cf54390ad476d89c8162e2bfba9e257966a4a2cb3b9c31b918f`，tar SHA为`51e1c5430da0cd4cc3e0538fd925f58da17e093f0e0aea94ae3d7cbc3a4d2b05`。旧工具目录`/tmp/strict-native-phase-tools-kevemo32`、target及全部AB1材料只读。捕获新工具输入为`raw/strict-native-followup-v1/fit-capture-repair-v1/repaired/capture_native.py`，SHA为`e1e573ed9ecd8a1dd77c80d6a06fff3739e4fa8114815cc2b6b5c826206a14b2`，还须绑定其实际Spec→Quality批准；不预填不存在的审批SHA。

新普通源前缀`crosspath-native-capacity-v2-src-`，工具前缀`crosspath-native-capacity-v2-tools-`，独占target前缀`crosspath-native-capacity-v2-target-`，均用`tempfile.mkdtemp()`建立。归档输出`raw/strict-native-phase-v2/task1/`及`results/strict-native-trace-capacity-v2-task1.json/md`，禁止覆盖既有路径。必要缓存可独立复制已有批准cache并生成新manifest，不能带入凭证或新增Cargo配置；不从用户询问清理的三个目录取输入或写入。

### 1.2 实施与检查

每一步保存真实命令、stdout/stderr、实际父进程wait和输入/输出身份。开始与结束均核原保护材料，不重新读全96批次封存，不复制整份历史研究归档。

- [ ] 创建普通源副本，排除.git、target、缓存、旧运行输出；逐项核全部702及完整普通树。保留原workspace内三份板卡控制TOML，环境除新source/tool/target/cache路径外与旧输入等值。
- [ ] 仅将`diagnostics.rs::CAPACITY`的16,384改为65,536，加必要英文容量/开销说明；其它701份源保持原字节，禁止改追踪热路径、loss ensure、压力或时间界。
- [ ] 运行`cargo fmt -p axvm`及`cargo xtask clippy --package axvm`，两个target变量指向新独占目录；遵守实际仓库入口，不能用原生Cargo检查替代。失败即保存并定位，不加allow或扩大无关验证。
- [ ] 复制原单次工具必要输入，以批准新捕获器替换其副本；`native_once.py`仅将输出根改为`raw/strict-native-phase-v2`。新路径/普通树、新702清单、控制及cache身份另生成并冻结；不抄旧.once或旧批准。
- [ ] 用真实`--check-ready`记录主96交付门及静态身份通过，精确错误source/approval按原正式入口拒绝2，确认没有新marker、板卡请求或硬件子进程；既有只读audit-hook入口可复用，旧检查器假设“主96未完成”不可原样当成成功判据。不为路径迁移重新运行旧清理替身矩阵。
- [ ] 新工具与原工具AST/diff核对：除输出目录外controller不变，捕获器与批准副本同字节；所有源/缓存/控制差异均在新输入内明确解释。归档最小补丁、准确manifest/tar和继承验证来源。

实现前确认当前空间，按实际大小登记临时构建/cache和归档材料；归档初始预算1GiB，不删除旧证据腾空间。若必要材料将超预算，在执行新增捕获前先记录具体原因及新预算，不默默继续。

## 2. Task2真板功能

本任务须先有Task1双审及Root独立复验。既有[严格真板计划](phase2-strict-native-verification-path-plan.md)3.1/3.2节的全功能、所有权、捕获和退出门继续适用，702父身份必须替换为本次准确新身份，其余判据不得弱化。Task1报告不是启动批准。

### 2.1 单次执行

- [ ] Root先核新版本批准、完整主96交付及当前真实宿主的无冲突和服务可用性，保存新候选准确SHA绑定及60秒内所有权见证。
- [ ] Root对AB1单项登记一次性准确批准；真实driver由其父进程持有`Popen`并记实际wait，target xtask也保留自己的真实wait。输出只在新v2目录。
- [ ] 对完整原始Trace、64任务、两份DATA/R/ACCEPT、同代计数域、250µs/4ms、A覆盖/skip0、已知答案、退休、全局零丢样、suite、工件使用链、退出和释放逐项独立审计，不以ACCEPT或标记计数替代完整判定。
- [ ] 先Spec后Quality，Root重核后才依次批准AB0及0各一次；每项失败、未完成或本次释放不明即停止余项，不自动重试。未进入的项保留未执行。

原AB1仍失败，旧后项未执行。新单项通过也只证明新测量版本在该条件的功能，不证明旧版本成功或稳定交互。

### 2.2 后续交接

三项真板均完整通过后，按原计划Task3另冻结并补足legacy生命周期RED/GREEN；其正式源改为本次新测量版本，旧父身份仅作来源。QEMU只用于这一功能义务，不用于Cache/内存结论，不重跑旧相位失败候选。随后才接相位分析、同版本开销及随机重复队列。阶段0～2、M2、Joint和goal均不因本计划或Task1交付变为完成。
