# function-audit-v3 独立 Spec 复审

结论：**PASS（限定为同次运行身份绑定纠错）**，`blockers=[]`，可继续 Quality 复审。本结论不接纳新cache/freeze或硬件执行。

绑定 `audit.py` SHA `35efe04deacc18de5556505b8567cabc988b1c85eefe6455cf3da1c2c4deb6c8`、`status.json` SHA `72e0b3ad003fc3e4eb2494f1fec6d1f4bbfc9f1b03a2c589310209570e2476a0`、修订报告 SHA `4f8fd9170d72d9b3de87a4f494ab387d724deadb2bb7a2ebabc889f6dce09498`。原唯一阻断 `QUALITY-EXIT-RUN-IDENTITY` 来自准确v2 Quality报告 `1aaae343…`。

| 必要连接 | 已落实位置 |
| --- | --- |
| SHA绑定approval/root_launch/root_tool_completion | `audit.py:836–845` 将三份真实文件与原材料一起read_bound，缺失保持失败。 |
| case与准确批准、输入、环境、driver CLI | `audit.py:727–753` 连接run/wait/launch/approval case、完整case env/argv/source/freeze/input SHA及三份完整driver argv。 |
| 原Popen child与launch/wait | `audit.py:755–774` 比较driver/supervisor PID/PGID/starttime/argv，核Popen直接child PID及准确launch/run-result SHA。 |
| 原Root completion | `audit.py:775–800` 沿completion→wait SHA→launch连接；session/chunk只取原completion，不向launch捏造重复字段，数值与各实际退出收据一致。 |
| 成功退出/显式释放 | `audit.py:803–816` 仍要求同次身份、xtask/driver/Root全0、无强停/timeout、owned group empty及冻结ostool显式释放；identity通过不能替代这些门。 |

静态diff/AST确认仅增加 `validate_run_identity` 并修改 `validate_exit/audit`，其余25个函数和原18规则/2检查源字节未变，原三个Spec纠错及全部正常门未放宽。仍使用准确 `0f46…` 源与 `6d83…` freeze；新 `0bf9ff…` 身份没有迁入或接纳。

只核现有真实收据与stdout/stderr准确SHA，未执行audit或tests：同一身份行为在v2真实wait1、8项漏拒/0 error；v3真实wait0、8项全拒。反例的changes逐项相同，基线始终为真实失败1/1/1，没有成功Popen/Guest/Trace构造。继承18条规则、2项检查分别真实wait0；两份整体真实失败仍wait1。

当前AB1身份门通过，原session15037/chunk6268a7经准确completion保留；退出/释放门仍拒绝，1/1/1、release unknown、DATA/Trace/工件缺失。旧v1缺原completion明确拒绝，不回填，dropped19839继续失败。AB0/0未执行，原quota不重试。

本次读取限于精确候选diff、已有报告和收据；没有build/ready/QEMU/board/Git/proc/signal/network或全树/cache/702/主96扫描，只新增本审阅JSON/MD。完整正常端到端GREEN、Aoff/Bzero、成功Trace/suite/工件/释放、legacy RED/GREEN和完整Host仍未验证。容量、Host、M2、Joint、goal均未因此完成。
