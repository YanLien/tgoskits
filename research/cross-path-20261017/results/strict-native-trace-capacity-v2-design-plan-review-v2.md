# 严格相位追踪容量v2计划复审

新计划v2通过，首轮唯一阻断`P2-CACHE-RELOCATION`已在计划中闭合，未发现新的阻断。原容量设计的PASS结论继续适用；本轮通过仅覆盖设计与实施计划，不表示Task1候选已经完成或批准硬件启动。准确身份和逐项判断见[审阅JSON](strict-native-trace-capacity-v2-design-plan-review-v2.json)。

## 1. 缓存迁移结论

新计划1.3已把“复制目录”补足为可核查的新缓存入口迁移，并把冻结放在迁移之后。首轮容量、内存、串口和控制器判断直接继承，不重复计算或重hash35个原输入。

### 1.1 修改范围

新副本扫描`venv/bin`、`pyvenv.cfg`和激活metadata的当前严格cache及原workspace历史前缀，限定实际入口和有关metadata的最小替换。普通模式、批准symlink目标和旧cache字节保留；vendor Zephyr、工具链、site-packages算法、ELF和任意二进制均不修补。逐项保留旧/新SHA、mode、diff及历史前缀，足以审查迁移范围。

### 1.2 实际使用证明

计划要求新venv真实Python在`-B`、清除`PYTHONPATH/PYTHONHOME`后报告`sys.executable`、`sys.prefix`、`cmake.__file__`、`CMAKE_BIN_DIR`和实际binary SHA，再直接运行新`venv/bin/cmake --version`并保存shebang、binary选择实现及真实wait。已核真实cmake模块通过`distribution("cmake").files`、`script.locate().resolve()`定位二进制，由`_program_exit()`经`os.execl()`执行；这些证据可把模块解析与生产入口关联。系统Python可解析到`/usr/bin`且需独立记身份，不能混称新venv内独立binary。

## 2. 身份与前置门

完整新计划保留了首轮正确的离线、构建与硬件边界。新增证明只针对迁移风险，不重复旧cleanup矩阵或新增常量镜像测试。

### 2.1 冻结和当前捕获批准

Cargo与VIRQ cache manifest在重定位后生成，Cargo bookkeeping分记before/after；fmt/Clippy后再次核701、`Cargo.lock`和完整普通树，后续变化仍需新身份及审阅。真实捕获修订Spec、Quality均PASS，Root已接纳；三份审批SHA与计划相符，且Quality/Root绑定同一最终工具。接受范围仍仅离线post-exit捕获，旧正常功能false、releaseunknown和M2/Joint/goal状态保留。

### 2.2 后续执行范围

新旧计划Task2全文相同：Task1离线候选完成后仍须先Spec后Quality和Root独立复制复验，之后AB1→AB0→0各项仍由Root鲜批准。900/920秒、cleanup10、capture30、512MiB及失败/不完整/本次释放未知即停门未变。Git授权由Root处理，不改变正式源或硬件身份。本审阅没有执行新venv、Rust检查或硬件。

## 3. 版本与收据

本轮只新增v2报告和局部收据，原设计、原计划及首轮报告保持原字节。

### 3.1 准确绑定

本轮结论绑定新计划和原PASS设计，原审阅仍作为继承证据保存。

- 设计SHA256：`5dbf286e5275dde7f8553de3785835b246f8df6ef7ad2b2e010bbe9357bb3ccd`。
- 新计划v2 SHA256：`54a43488604d56ea9bf02b5cdf06d1ab9b6d8bceb4248f91504c00e491534e27`。
- 首轮审阅JSON SHA256：`12fac4fdce35713bbea4564be40cccca4a30aec61666cc5e183a53c25f1abf46`。

### 3.2 实际局部核查

[差异核查](../raw/strict-native-phase-v2/design-review-v2/local-checks.json)检查8份局部输入身份、Task2全文不变、迁移要求及捕获批准链，真实父进程对原直接子进程调用`Popen.wait()=0`，见[执行收据](../raw/strict-native-phase-v2/design-review-v2/check.execution.json)。[计划diff](../raw/strict-native-phase-v2/design-review-v2/plan-v1-to-v2.patch)只用于版本复审，没有修改原文件。

没有Git写入、构建、fmt/Clippy、QEMU、board、proc、signal或正式分析；没有重hash35原输入、全702/cache/96，没有访问三个禁读临时目录。缓存迁移、候选检查与正常功能仍须后续实际交付，M2、Joint和goal仍未通过。
