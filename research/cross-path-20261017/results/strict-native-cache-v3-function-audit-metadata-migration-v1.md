# 外部正常功能审计器新缓存合同迁移

本次为同一审计器交付的集成尾步，新增 [`strict-native-phase-v3/function-audit-v1/`](../raw/strict-native-phase-v3/function-audit-v1/README.md)，没有覆盖已封口的前v3或任何历史材料。

17项引用已先逐一按实际新path/bytes/SHA核定。源码与source702不变，实际内容变化仅freeze、inputs、capture、driver四项。审计器只改 `CONTRACT_SHA` 和 `FREEZE_SHA`：35个顶层/嵌套/方法函数源码字节和AST相同，屏蔽这两项赋值后全模块AST相同。新冻结输入可由现有函数直接消费，无需行为修改或任意合同泛化。

新freeze准确为 `0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8`，新合同SHA为 `8ff5e4a14fc159d0b0ec81bd26c00fe1860c62611d9e6a0f38c15989e6518d0e`，新审计器SHA为 `6fa57d1bb99a9fbdb49613ffc90cb4b648aa9511465957aec25b9e58e34e76aa`。完整前后清单、实际Popen.wait收据和历史逻辑证据绑定见 [`status.json`](../raw/strict-native-phase-v3/function-audit-v1/status.json)。

本次未运行audit/新case，也未重跑已过18规则、2继承检查或Rust/cache/主96。前v3的身份红绿与两实际失败仅作准确SHA历史引用，不把它们改称新Host成功。完整正常端到端GREEN仍未取得，当前新AB1无审计运行，AB0/0未执行；本候选等待Spec→Quality，不自行批准硬件或下一阶段，Host/M2/Joint/goal均未完成。
