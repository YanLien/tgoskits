# 严格真板正常功能审计器

该工具在原始日志、实际工件和 Root 最终交接全部保存后，检查同一次运行的完整正常功能。当前阶段没有新的正常端到端 GREEN；离线规则验证和来源绑定不替代真实板卡验证。

## 1. 候选身份

审计逻辑与实验环境分别版本化。新的准确环境合同只能在单独副本中迁移，旧失败及其审计结果保留原字节。

### 1.1 当前工具

新缓存候选使用 [phase-v3/function-audit-v1](../raw/strict-native-phase-v3/function-audit-v1/README.md)，`audit.py` SHA256 为 `6fa57d1bb99a9fbdb49613ffc90cb4b648aa9511465957aec25b9e58e34e76aa`，`source-identities.json` SHA256 为 `8ff5e4a14fc159d0b0ec81bd26c00fe1860c62611d9e6a0f38c15989e6518d0e`。它绑定 source702 `0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb` 与工具 freeze `0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8`。

[准确元数据迁移报告](../results/strict-native-cache-v3-function-audit-metadata-migration-v1.json)记录 17 项真实引用，只有 freeze、inputs、capture、driver 四项内容改变。`CONTRACT_SHA`、`FREEZE_SHA` 两项赋值之外，35 个验证函数的源码与 AST 均保持前一逻辑修订；没有开放任意合同入口。

### 1.2 历史逻辑修订

[phase-v2/function-audit-v3](../raw/strict-native-phase-v2/function-audit-v3/README.md)修复同次运行身份连接，准确 `audit.py` SHA256 为 `35efe04deacc18de5556505b8567cabc988b1c85eefe6455cf3da1c2c4deb6c8`。更早的 v1/v2 保留缺陷与 RED 来源，只用于复核历史，不能作为当前正常接受工具。

[修订报告](../results/strict-native-function-audit-v3-revision-v1.json)记录真实失败收据的独立身份门及八种错配拒绝证明。18 项原规则和两项继承检查仍通过，两次真实整体失败仍拒绝；这些是原候选的逻辑证据，不能改称新环境运行结果。

## 2. 审计输入

`audit()` 只消费明确指定的最终交接及其准确 SHA。原始日志、来源、冻结输入、实际命令、工件、启动、等待和原工具完成收据均须通过绑定门；输出目录必须是当前审计器目录内全新的普通子目录。

### 2.1 同次运行

`validate_run_identity()` 沿 `root_tool_completion` 的等待收据 SHA 连接 `root_wait`，再由其 launch/run-result SHA 连接实际启动及 driver 结果。case、完整启动参数、批准输入、source/freeze、原 Popen child 和 supervisor 的 PID/starttime/argv 必须一致。真实失败也可能拥有完整身份，因此 `validate_exit()` 仍另行要求实际 xtask、driver、Root 全部退出 0、无强停且固定 ostool 显式释放。

执行时，`--handoff` 指向当前 case 的真实最终交接，`--handoff-sha256` 来自对该文件的重新读取，`--output-dir` 指向新的子目录。不得用另一次运行的成功收据替换失败项，也不得补造缺失的原始 session 完成证据。

### 2.2 正常判据

原始 Guest workload、双策略 DATA、known answer、时间/压力边界、完整 Trace schema、全局零丢样、生命周期、suite、实际工件使用链和退出/释放分别为必需门。缺失或歧义按报告保留并拒绝完整正常接受；检查通过之前不计算正常相位性能结果。

完整原始 Trace、工件与多 GB 构建缓存保存在本地证据树，Git 中的脚本和身份清单不能替代这些材料。重放需要报告列明的准确源、工具、输入和原始运行证据。M2、Joint 及阶段2整体状态继续以正式研究验收为准。
