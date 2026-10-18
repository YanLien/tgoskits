# v3 审计器修订候选

本版只闭合同次运行收据绑定缺口。合同、输入范围与证据限制见 `DESIGN.md`，准确身份见 `status.json`。当前仍绑定capacity-v2的真实6d830c工具freeze；Root已通知的0bf9ff新缓存身份将另起副本迁移，不改本版字节。

- `v2-identity-rule-red-v1/report.json`：原v2同次运行规则缺失，8个反例漏拒，实际wait1。
- `v3-final-identity-green-v1/report.json`：真实失败收据组身份基线通过，8个错配均拒绝，实际wait0；只证明身份规则。
- `retained-18-rules-green.json` 与继承两项检查：实际wait0。
- `old-AB1-red-v1/report.json`、`new-v2-AB1-red-v1/report.json`：真实整体失败均实际wait1，releaseunknown保留。

按 `python3 -B` 运行 `audit.py`，传入Root最终handoff及准确SHA，输出只能新建在本目录子目录。完整正常门通过才退出0，功能失败退出1，输入身份拒绝退出2。当前没有正常端到端GREEN；等待独立Spec/Quality，未批准下一阶段。
