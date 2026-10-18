# function-audit-v3 同次运行收据绑定修订

## 1. 范围与合同

本次只处理 [v2 Quality FAIL](../../../results/strict-native-function-audit-v2-quality-review-v1.md) 的 `QUALITY-EXIT-RUN-IDENTITY`，JSON SHA `1aaae34325c49b66d381ebd8e6e266623b662b65f824954abc16fff6da3a20f3`。v1/v2 与旧报告不改，当前 source702 仍为 `0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb`，当前工具 freeze 仍为 `6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9`。Root 后续通知的新缓存 freeze `0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8` 不在本版输入；本版先封口、审阅，迁移另起准确新合同副本。

新增 `validate_run_identity()`，独立于正常退出与释放。`audit()` 对原有 `root_launch`、`root_tool_completion`、`approval` 也先按 final handoff 的准确 SHA/size 加载，再执行同次运行身份门；`validate_exit()` 必须再次消费该门。真实失败收据可以身份完整，但不能因身份完整就成为正常成功。

| 连接 | 独立判定 |
| --- | --- |
| 当前 case → 实际 xtask/批准 | run_result、root_wait、root_launch、approval 的 case 一致；actual_command 按该case完整合并冻结环境；批准的 source/freeze/inputs/argv/env 与实际 command 一致 |
| 批准 → 原 driver 启动 | launch、launch.driver、wait.driver 的完整 argv 相等，准确包含 `--run`、source、freeze、approval路径及SHA；launch 的基础环境/cwd 匹配冻结producer |
| launch → 原 Popen wait | driver 与 supervisor 的 PID/PGID/starttime/argv 一致，`driver_pid_from_Popen` 是该 driver；原 wait_method 与 supervisor_source_sha256 一致；wait 的 launch/run_result SHA 指向准确文件 |
| wait → Root 原始完成 | completion 的 `driver_Popen_wait_receipt_sha256` 指向准确wait；保留实际session/chunk；driver完成值与父进程wait和handoff一致，Root实际退出取原completion，并与handoff/已有outer_wait一致 |

现有 launch 没有另一份 unified session 字段，不增加虚构字段：原session只来自准确completion，沿其wait收据SHA传递连接到launch。过程不读proc、不推测进程消失；state快照不充当退出结果。缺失或矛盾拒绝，不能退回只信handoff外层退出标量。原有全0、无强停/timeout、owned-group-empty、完整工件链和冻结ostool显式释放合同保留。

## 2. 最小规则证明

`test_exit_binding.py` 只使用真实失败 AB1 的准确收据组，保留实际 xtask/driver/Root 为1和releaseunknown。八个局部反例分别断开跨case、原child、driver受控source、command批准、launch SHA、completion SHA、完成退出值或原completion存在性；相互依赖的内部SHA按实际保存字节重算，避免只测格式错误。原件引用、变化字段、测试收据准确字节和结果都归档。

同一测试在准确v2上执行原身份表达式切片，出现8个预期漏拒（真实wait1）；在v3执行正式独立身份门，8个反例全拒（真实wait0）。切片仅去掉无关的零退出/释放前置，既没有把真实失败改成成功，也没有伪造Popen运行、Guest或Trace。该GREEN只证明同次运行收据绑定规则。

原三个组18条规则与两项继承检查保留并通过。两份真实完整失败仍审计退出1；当前新AB1身份门通过，正常退出/释放门仍拒绝。旧v1没有原工具completion，明确缺证据，不补造。

## 3. 交付限制

全部实际命令由本目录 `run_command.py` 的原直接子进程 `Popen.wait()` 保留 argv/env/stdout/stderr 收据。仅新增当前目录和独立修订报告；不改冻结工具、缓存、Rust、Root材料或历史，不运行硬件、QEMU、build、ready、proc、signal、network、Git，不扫主96/702/cache。

完整正常端到端GREEN、AB0/0、Aoff/Bzero成功、完整成功Trace/suite/工件链/释放及legacy生命周期仍未取得；本修订等待先Spec后Quality，不自行放行下一阶段，Host/M2/Joint/goal均未完成。
