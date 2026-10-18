# 新缓存 v3 AB1 失败交付质量审查

本次 Quality 结论为 **PASS_TRUTHFUL_FAILURE_EVIDENCE_ONLY**，`blockers=[]`。通过范围仅为如实失败交付：原 AB1 仍失败停止，正常功能、修复、硬件重跑、性能、M2、Joint 和整体目标均未验收。[机器审查](strict-native-cache-v3-AB1-failure-quality-review-v1.json)保存范围、核对项、精确引用及检查结果。

## 1. 交付判定

[原失败报告](strict-native-cache-v3-AB1-failure-v1.md)与其[机器报告](strict-native-cache-v3-AB1-failure-v1.json)把局部数据通过和整轮失败分别陈述，没有用后续解释覆盖原始拒绝。[独立 Spec](strict-native-cache-v3-AB1-failure-spec-review-v1.json)的 SHA256 已核实为 `28d3b9caa0f8b73850bfbf46cec1a4e86839e83734c51d07045414a6fb8d6b85`，其结论同样仅限如实失败证据且无阻塞项；本次不重复 Spec 的完整引用清单验证。

### 1.1 数据范围

既存 Spec 与[原正式审计](../raw/strict-native-phase-v3/function-audit-v1/AB1-actual-audit-v1/report.json)支持 42,768 条完整 Trace、零 dropped/incomplete、两份 DATA、两次相位 ACCEPT 及压力门通过。原日志也确有 suite pass/summary/OK；本次仅按已保存偏移核对其中三条 suite 记录，没有重新扫描事件序列或运行审计。这些事实没有被提升为 Guest 整轮正常功能通过。

### 1.2 失败范围

[原运行结果](../raw/strict-native-phase-v3/AB1/run-result.json)仍保存 `outer_timeout=true`、920 秒预算、cleanup argv changed、`xtask_wait_exit=null` 和 `release=unknown`。[原父进程 wait](../raw/strict-native-phase-v3/AB1-root-wait.json)实际得到 driver 退出 1，[原工具完成记录](../raw/strict-native-phase-v3/AB1-root-supervisor-completion-v1.json)独立绑定 session 77494 / chunk `36f9ce` / 实际退出 1。子进程自己保存的 `driver_wait_exit=null` 没有被当作外部父进程未 wait 的证据。

[最终交接](../raw/strict-native-phase-v3/AB1-root-final-handoff-v1.json)的 `forced_signals=null`、未知历史 release 和 AB1 额度已耗均保留。AB0/0 未执行，没有以失败样本生成正式相位性能或正常功能结论。

## 2. 原因解释边界

两个原因报告只解释已有失败证据，未修改封存报告，也未追认原始审计通过。其技术结论、未证明事项和建议均与失败交付范围一致。

### 2.1 控制器机制

[退出调查结构版](strict-native-cache-v3-AB1-exit-cause-structured-v1.md)与[机器报告](strict-native-cache-v3-AB1-exit-cause-v1.json)明确区分了合法 exec 可触发同样 cleanup 拒绝的局部机制与历史 AB1 实际 exec。历史新 argv/exe、改变时刻、cleanup 时 token、xtask 最终退出码及历史 release 仍未知；局部 wait0/wait23 没有被当作 AB1 退出码。拒绝后的一次 `child.poll()` 仍为 None，随后 capture/static 没有最终显式 poll/wait 的缺口也被准确保留。

`capture_phase=post-exit` 是缺少退出门禁的生产标签；日志 mtime 仅为文件写入元数据。后来 PID 消失、group 当时为空、service available1 和该次观察未发信号，只证明后来状态，不能补回原 wait/release 或将原 `forced_signals` 改成空数组。

### 2.2 审计解释

[审计调查结构版](strict-native-cache-v3-AB1-auditor-cause-structured-v1.md)与[机器报告](strict-native-cache-v3-AB1-auditor-cause-v1.json)将 Host append-newc/gzip 合同差异和两条 DTS Warning 的分类规则分别定位；局部格式函数与 regex 调查没有被称为完整 use-chain 或完整 suite 重新通过。原正式审计仍是 24 门中 20 过、4 拒；[原审计 child wait](../raw/strict-native-phase-v3/AB1-actual-audit-v1.receipt.json)与[原工具完成记录](../raw/strict-native-phase-v3/AB1-actual-audit-original-tool-completion-v1.json)均实际为 1，后者绑定 session 42886 / chunk `9be3c5`。

两条 Warning 的原偏移和 SHA 与实际保存字节一致；DTS 地址差异是否可接受仍未验证。实际 USER_CACHE 选择 `/home/yanlien/.cache/zephyr`，不同于冻结离线 witness 的候选 `/tmp/.../zephyr/.cache`；原因和 mutation 范围仍未知。两项限制不阻塞如实失败交付，但不能用作未来正常验收的通过证据。

`suite_refusal.unframed_nonempty_final_rows` 保存 20 条未加宿主框架的串口记录，不能把该数组非空理解为存在 EOF 残尾。本次精确核对其原字节跨度：各跨度以 CR 结束且紧随 CRLF，原文件末字节为 LF。结构版所称“无未换行残尾”与此没有冲突。

## 3. 文档与核对范围

本次只新增本 Quality 的 JSON 与 Markdown；原失败报告、原因机器报告、原原因 Markdown 及已有证据保持原字节。新结构版提供编号章节，原原因 Markdown 继续作为封存引用使用。

### 3.1 正文保全

逐段比较[原退出报告](strict-native-cache-v3-AB1-exit-cause-v1.md)及[原审计原因报告](strict-native-cache-v3-AB1-auditor-cause-v1.md)与各自结构版，忽略标题、结构版说明段、空白和原项目符号后，原技术文字和引用全部保留，无删除或替换；每份结构版另增加一段与原结论一致的解释性连接文字。旧文档的结构不要求回写封存字节。

`pending_cause_reports` 保留失败机器报告创建时的状态，后续原因报告独立追加；这一历史字段不表示原因报告现在仍不存在，也不要求回写历史文件。

### 3.2 精确检查

已核对 18 个选定报告和小型原始收据文件的 SHA/bytes、5 份被审 Markdown 的 30 个链接、两条 Warning、一条 cache 选择及三条 suite 标记的精确跨度，并静态核对 JSON 字段和编号结构。没有重复 Spec 的全量 hash、完整 Trace 扫描、主 96 次封存扫描、格式探针或测试复跑；没有硬件、QEMU、网络、宿主 proc、信号、构建或 Git 操作。

未发现必须修改原交付才能完成本范围验收的问题。未来控制器或审计器候选、独立负例、硬件新额度及正常功能和性能验收均不在本次 Quality 通过范围。
