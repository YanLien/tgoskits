# 新缓存 v3 的外部功能审计器合同迁移

本候选由已封口的 [`function-audit-v3`](../../strict-native-phase-v2/function-audit-v3/README.md) 复制而来，只替换 `CONTRACT_SHA` 和 `FREEZE_SHA` 两个准确身份常量。35个顶层函数、嵌套函数及方法的源码字节和AST完全相同；屏蔽这两项赋值后全模块AST也相同。没有放宽为接受任意合同。

先按实际新路径逐项核17个引用，再写新合同和常量。9个实际源码、source702、worker build以及两份ostool源码内容均未变；实际改变的只有工具freeze、inputs、capture和driver，逐项前后path/bytes/SHA见 `contract-migration.json`。精确代码差异与AST证据见 `metadata-only.patch`、`identity-AST-comparison.json`。

| 合同 | 准确SHA256 |
| --- | --- |
| source702 | `0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb` |
| 新工具freeze | `0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8` |
| 新source-identities.json | `8ff5e4a14fc159d0b0ec81bd26c00fe1860c62611d9e6a0f38c15989e6518d0e` |
| 新audit.py | `6fa57d1bb99a9fbdb49613ffc90cb4b648aa9511465957aec25b9e58e34e76aa` |

本次仅执行离线哈希、输入schema与字节/AST比较，没有运行审计器或重跑18规则、2继承检查、Rust、cache、主队列及任何新case。前v3的身份RED/GREEN与两份真实失败是历史逻辑验证，按准确SHA引用于 `status.json`，不能作为新Host成功或新版本实际运行结果。

等待同一独立Spec及后续Quality合并审阅逻辑修订和纯迁移两个准确候选。新AB1尚无本候选审计；完整正常端到端GREEN未取得，AB0/0未执行，Host/M2/Joint/goal未完成。未来调用仍须Root提供新的准确final handoff，不能使用旧6d830c版本handoff作为新成功输入。
