# 严格真板功能审计器 v3 独立质量复审

本报告复审上轮唯一退出收据绑定阻断，并在正式 Spec 附录通过后合并核验新合同副本。结论仅覆盖准确实现候选及既有工具证据。

## 1. 质量结论

本次为 **PASS，blockers=[]**。`QUALITY-EXIT-RUN-IDENTITY` 已在静态实现和现有规则证据范围内闭合；纯元数据副本也保持相同行为并绑定准确新合同。Root 可接纳这两份候选，仍须独立取得新合同实际运行的完整证据。本次不批准硬件或重试。

### 1.1 两份准确候选

逻辑修订仍绑定原 capacity-v2 freeze；集成副本只改 `CONTRACT_SHA` 与 `FREEZE_SHA`。两者不能互换运行证据，准确 status、Spec、报告及全部引用见[本次 JSON](strict-native-function-audit-v3-quality-review-v1.json)。

| 候选 | 审计器 SHA256 | 工具 freeze |
| --- | --- | --- |
| [phase-v2/function-audit-v3](../raw/strict-native-phase-v2/function-audit-v3/audit.py) | `35efe04deacc18de5556505b8567cabc988b1c85eefe6455cf3da1c2c4deb6c8` | `6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9` |
| [phase-v3/function-audit-v1](../raw/strict-native-phase-v3/function-audit-v1/audit.py) | `6fa57d1bb99a9fbdb49613ffc90cb4b648aa9511465957aec25b9e58e34e76aa` | `0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8` |

[逻辑 Spec](strict-native-function-audit-v3-spec-review-v1.json) 的准确 SHA 为 `cd8ea9a2820235bfdcd2a71a3abd22668f26e2e3e1d30c9c2cb48aeb4223d628`；[绑定 Spec 附录](strict-native-function-audit-v3-spec-binding-addendum-v1.json) 为 `265cc08b54998f117807fc408e1351ce1304bca37833f9becd5290e355ca1adc`。二者均已 PASS。本次在收到正式附录 PASS 后才审阅元数据副本，未改已封报告。

### 1.2 继承范围

上轮 [完整 Quality](strict-native-function-audit-v2-quality-review-v1.json) SHA `1aaae34325c49b66d381ebd8e6e266623b662b65f824954abc16fff6da3a20f3` 已通读原 813 行实现。本次鲜核 v2→v3 仅新增 `validate_run_identity()`，修改 `validate_exit()/audit()`；其余 25 个顶层函数及其余模块 AST 不变，按准确实现继承既有结论。

原完整 DATA/R/ACCEPT、工作量、64 个 T6、每策略 32 槽/2 快照、generation/counter、250µs/4ms、A 覆盖/skip0/off、Bzero、退休与前后校时、完整合法 Trace/逐 CPU sequence/zeroLoss、suite 和工件门均保留。没有因本次修订弱化原三个 Spec 修订或正常功能判据。

## 2. 退出身份闭合

`validate_run_identity()` 将收据归属从数值成功中分离：真实失败可以有完整身份，身份完整不能代替零退出或释放。这个结构解决上轮“可借用别项匹配成功 wait 对”的缺口，同时保留原始失败。

### 2.1 启动到完成的证据链

[audit.py:728](../raw/strict-native-phase-v2/function-audit-v3/audit.py#L728) 将 run、wait、launch、approval 的 case 逐一核对，并连接完整 case 环境、实际命令、source/freeze/inputs、准确批准 SHA。`expected_driver` 从冻结输入生成完整 CLI；launch、launch.driver 与 wait.driver 的 argv 必须精确一致。

[audit.py:756](../raw/strict-native-phase-v2/function-audit-v3/audit.py#L756) 比较 driver/supervisor 的 PID、PGID、starttime 和 argv，并核原始 `driver_pid_from_Popen`、wait 方法与 supervisor 源 SHA。wait 的 launch/run_result SHA 必须指向 final handoff 的准确字节；state 快照没有被用作退出证明。

[audit.py:777](../raw/strict-native-phase-v2/function-audit-v3/audit.py#L777) 再以原 completion 中的 wait 收据 SHA 连接原工具 session/chunk，核 driver、xtask、Root 实际完成值。launch 本来没有 session 字段，实现没有补造重复值；session 的归属沿 completion→wait→launch 的准确哈希链传递。Root 退出从 completion 取得，删除了仅信 handoff 标量的退路。

### 2.2 错误传播与保留证据

[audit():838](../raw/strict-native-phase-v2/function-audit-v3/audit.py#L838) 对新增 approval、root_launch、root_tool_completion 也先按 final handoff 的 SHA/size 加载，并将身份门纳入完整判定。`validate_exit()` 再次要求身份门，随后仍要求全 0、无强停/timeout、owned group 已空、tool_errors 为空和固定 ostool 的显式释放。

报告的 Root 退出、session/chunk 同样来自原 completion；缺失材料保持 unknown/None 和失败。当前真实新 v2 AB1 身份门通过，但实际退出 1/1/1、release unknown，正常退出门及完整功能仍失败。原 v1 缺 completion 且 dropped19839，继续拒绝；没有补造收据或回填成功。

## 3. 合同迁移与检查证据

元数据集成只允许准确新合同，未增加接受任意合同的逻辑。历史规则运行属于旧 6d830c 合同；新 0bf9ff 合同尚未执行或审计任何 case。

### 3.1 纯绑定核验

新副本的 35 个函数源码字节逐一相同，屏蔽两项准确常量后全模块 AST 相同，全文件只改变第 17、19 行。新合同 SHA 为 `8ff5e4a14fc159d0b0ec81bd26c00fe1860c62611d9e6a0f38c15989e6518d0e`，source702 仍为 `0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb`。

已按准确路径核 17 个普通文件引用的 SHA/size；只有 freeze、inputs、capture_source、driver_source 四项内容变化，其余 13 项内容不变。指定源码匹配 source702 清单，driver/capture/inputs/source manifest 匹配新 freeze；新 inputs 在精确 source/tools/target 三个前缀迁移后与旧版等值，case 矩阵、argv、限额和非路径环境保持。这个范围只接纳审计器绑定，不重做新 producer 的另一份完整实现审阅。

### 3.2 规则证据与限制

本次新执行的两个 `python3 -B` 内联只读检查均为 0：准确引用、SHA/JSON/AST 及输入迁移；现有规则报告、保存变异字节和真实失败判定。另静态通读新函数、两处调用、报告路径、完整 patch 与 `test_exit_binding.py`。没有导入或执行候选，也没有运行任何既有 audit/tests、build、ready、硬件、Git、proc、网络或 signal，没有扫描主96/cache/702/9642。

现有八条反例的语义变化逐项一致，16 份保存的测试 handoff 及其引用字节已核：原 v2 实际 RED wait1、8 漏拒/0 errors；v3 GREEN wait0、8 全拒/0 errors。它们使用真实失败组，基线仍为 1/1/1；相关内部 SHA 按保存字节重算，拒绝来自具体连接。原 18 规则、2 继承检查实际 wait0，两份真实整体失败仍 wait1。六份逻辑、两份元数据收据及 stdout/stderr 已核，未重跑。

完整正常端到端 GREEN、新合同新 AB1 完整审计、AB0/0、Aoff/Bzero 正常成功、完整成功 Trace/suite/工件链/释放、legacy RED/GREEN 和完整 Host 均未取得。历史 Trace 规则仍只涉及两条真实 Marker/HostIrqEntry，不能当成成功 Guest 或整套 Trace。Host、容量修复、M2、Joint、goal 均保持未验证/未完成；未来启动仍需 Root 当前所有权见证与一次性准确批准。
