# 新缓存 v3 AB1 实际失败记录

AB1实际导出42,768条完整Trace，dropped/incomplete均为0；两策略DATA、相位时间界和压力门通过。整轮仍失败：外层920秒超时，xtask最终退出未知，driver和原工具会话均实际退出1，release未知。AB0/0停止，本候选单次额度已耗，不生成相位性能或正常功能通过结论。

## 1. 原始运行

[机器报告](strict-native-cache-v3-AB1-failure-v1.json)保存原始引用、SHA、24项正式审计的通过与失败门，以及未完成项。源702清单为`0f46afee`，工具冻结清单为`0bf9ff1c`；[最终交接](../raw/strict-native-phase-v3/AB1-root-final-handoff-v1.json)绑定本次case、完整输入、原始日志和实际退出收据。

### 1.1 Guest与Trace

[完整原始日志](../raw/strict-native-phase-v3/AB1/xtask.log)为6,496,391B，SHA256为`c74a5a24106e3e59a4c03316b428f9591e5e481bce5f65a874f4231b7d10814b`。实际逐事件`VIRQ_RUNTIME`行共42,768条，与全局冻结和导出汇总一致；两策略各32个任务、完整DATA及相位ACCEPT，两个VM组回收标记，suite pass1/fail0。独立审计确认事件序列、物理IRQ身份、压力覆盖和零丢样门通过。这些事实证明本次数据范围，不能替代整轮退出与释放门。

### 1.2 退出与释放

原工具会话77494的最终chunk为`36f9ce`、实际退出1；[原父进程wait](../raw/strict-native-phase-v3/AB1-root-wait.json)为driver退出1。冻结控制器记录外层920秒超时和`owned group leader argv changed`，xtask wait为null，cleanup组空状态及release未知。最终交接中的`forced_signals`也保持null，不能改写为空数组或推定历史无信号。

13:05 UTC的[独立宿主观察](../raw/strict-native-phase-v3/AB1-host-terminal-observation-v1.json)显示原PID消失、原进程组当时为空、板卡服务可用1；该检查没有发送信号。这仅证明后来状态，不恢复原Popen退出码或认证历史release。

## 2. 正式审计

[实际正常功能审计](../raw/strict-native-phase-v3/function-audit-v1/AB1-actual-audit-v1/report.json)由原子进程真实wait1及原工具会话42886的最终chunk`9be3c5`、实际退出1支持。24项门中20项通过、4项拒绝；审计器逻辑与生产捕获分别保留，不能用一个工具的局部通过覆盖另一个拒绝。

### 2.1 四项拒绝

四项拒绝涉及退出证据及两个审计解释问题，具体原因保存在原报告的`gates`和原始诊断跨度中。

| 门 | 原始拒绝 |
| --- | --- |
| 同次启动、wait和完成绑定 | xtask最终wait未知，不能完成退出绑定 |
| 全suite失败及残尾检查 | 两条含有`error`词的DTS Warning未分类而拒绝 |
| 实际工件使用链 | `newc trailer/tail`；生产捕获同时记录artifact_chain_complete=true |
| 实际退出及显式release | 退出绑定不完整，release仍未知 |

修订日志分类或拼接包解析不会补回原始退出证据，也不能追认本轮正常功能通过。没有在本次失败数据上计算正式相位交互、尾延迟、DMR或吞吐结果。

### 2.2 捕获标签

生产`capture_native.py`无条件写入`capture_phase=post-exit`，本轮控制器却在最后一次`child.poll()`仍为None时调用它。该标签缺少实际退出门禁，不能作为退出证明。capture时间为12:59:02.040272962 UTC，日志最终mtime晚约5.774秒；mtime只说明后续文件写入，不能换算为Guest事件或进程退出时刻。已保存工件的身份核验与历史释放仍分开判断。

## 3. 定位与剩余工作

失败后的调查只使用保存材料及隔离的新本地进程，没有重试本候选或启动AB0/0。新调查报告与本次原始审计保持独立，原始拒绝及未知项均保留。

### 3.1 控制器调查

[退出原因报告](strict-native-cache-v3-AB1-exit-cause-v1.md)确认：cleanup把立即启动时的argv当作永久身份条件，合法exec可触发同样拒绝；拒绝后仍执行一次`child.poll()`，该次为None，之后capture/static与返回之间没有最终poll/wait。本地真实Cargo exec及新Python子进程支持此机制，但历史AB1实际变成哪个argv未被记录，不能指定为唯一历史成因。局部测试的wait0或wait23均不是硬件退出码。

### 3.2 后续门槛

先完成保存材料的格式与日志分类定位，以及独立控制器候选的所有权、合法exec和实际父子进程收尾验证；未来候选使用新身份和新额度，保留当前预算及设备语义。相位功能后仍有legacy、同版本匹配开销和真板随机重复四组实验，M2、Joint及整个研究目标均未完成。原四组和96次强度批次的既有交付不受本次候选失败回填。
