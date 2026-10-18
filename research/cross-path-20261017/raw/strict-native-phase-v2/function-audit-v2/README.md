# v2 审计器修订候选

`audit.py` 沿用只读、准确 final handoff SHA 与 case/source/freeze 绑定；输出必须是本目录下新子目录。退出0仅表示完整正常门通过，退出1表示功能不通过，退出2表示输入身份拒绝。每条实际命令由 `run_command.py` 的直接 `Popen.wait()` 记录准确 argv/env/stdout/stderr。

修订说明与逐项合同见 `DESIGN.md`；精确文件与收据身份见 `status.json`。

- `v1-final-rule-red.json`：同一规则测试对原v1产生18个预期漏检失败，实际wait1。
- `v2-final-rules-green-v2.json`：三个规则组的18个局部反例均拒绝，实际wait0。仅是工具规则GREEN。
- 继承两项检查实际wait0：封存失败不升级，以及真实DATA原件解码/CRC损坏拒绝。
- `old-AB1-red-v1/report.json`、`new-v2-AB1-red-v1/report.json`：两份真实完整失败输入都实际wait1，正常功能仍false。

完整正常端到端GREEN未取得；Boff规则已实现，真实Boff成功路径仍未验证。未来新freeze不在本次范围内。v1、冻结源/工具/cache、Root材料和历史报告未修改；不执行board/QEMU/build/ready/proc/signal/network/Git。无性能、相位重叠或I_AB输出，Host/M2/Joint/goal没有完成声明。当前等待Spec复审，尚未进入Quality。
