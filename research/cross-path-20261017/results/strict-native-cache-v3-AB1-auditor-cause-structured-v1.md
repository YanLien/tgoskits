# AB1 审计拒绝原因结构整理

本文是原报告的结构整理版，仅调整标题层级与段落组织，技术事实和原引用保持不变。

只读调查已定位两个拒绝点，正式 AB1 失败保持不变；本报告不实现修复，不重跑完整审计。原完整审计 SHA `1a9257ef78caf570267dcb89c60d3143cf97dd033f9460b56176347f594d0b25`、实际 Popen.wait=1；最终 handoff SHA `cf25d62d4ff106f0e6d3315ce4e0b58ce5f4d78ac2e90b7b79fe814116e9b72f`。完整正常功能 GREEN 仍为 false，AB0/0 未执行。

## 1. 审计拒绝原因

工件拒绝需要结合实际拼包格式与解析合同判断，套件拒绝需要结合原始候选跨度与分类规则判断。

### 1.1 Host 拼包格式

Host 实际保存 initramfs 为 17,797,682B，SHA `4683cb2cefc30679221e09d4f65cc0a2c533a7bc93d2e765acc0cef8517bbf92`；FIT 默认 `/configurations/config-ostool` 的 `/images/ramdisk` 与它全字节相同。它由原始 newc `[0,1364)` 与 gzip `[1364,17797682)` 拼接，gzip 内是 54,086,784B 的第二份 newc。首个 TRAILER header 偏移 1240，mode=0、size=0、结束于 1364；该处原字节为 `1f8b08000000000000ff`。两份实际 archive 单独均被两套严格解析器接受，Guest rootfs 也被两者接受。

### 1.2 解析合同差异

封存 auditor SHA `6fa57d1b...` 的 [audit.py](/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017/raw/strict-native-phase-v3/function-audit-v1/audit.py:668) 将整个 Host 容器交给单 archive `newc()`；[第 557 行](/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017/raw/strict-native-phase-v3/function-audit-v1/audit.py:557) 用 `any(raw[pos:])` 拒绝首个 TRAILER 后的合法 gzip。

冻结 capture SHA `61717a37...` 的 [_newc_entries](/tmp/crosspath-native-cache-v3-tools-jrhcn15t/capture_native.py:296) / [newc_members](/tmp/crosspath-native-cache-v3-tools-jrhcn15t/capture_native.py:343) 明确支持该拼接，并检查 gzip EOF、逐 archive 合法性和重复项。

原 capture `artifact_chain_complete=true/errors=[]` 与本次纯格式结果一致。结论是 auditor 不兼容已批准 Host 拼包格式，不能把合法 gzip 称为任意残尾；本次未重跑完整 use-chain 门。

### 1.3 套件候选跨度

suite 原始候选仅两条，位于 xtask.log 第 24/52 行、偏移 2695/5173、各 228B，同 SHA `c83438e2c6ba62743446b3445873b1486bb7309f41bb7c3cfef9cff3477e0283`。原文是 `Warning (simple_bus_reg): ... simple-bus unit address format error, expected "fe600000"`。

### 1.4 分类规则边界

命中为文本偏移 201 的独立单词 `error`，对应原日志偏移 2896/5374；[候选 regex 第 24 行](/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017/raw/strict-native-phase-v3/function-audit-v1/audit.py:24) 和 [分类第 135 行](/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017/raw/strict-native-phase-v3/function-audit-v1/audit.py:135) 将其保留为 `unclassified-reject/requires_rejection=true`，[suite 第 525 行](/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017/raw/strict-native-phase-v3/function-audit-v1/audit.py:525) 因此拒绝。

没有额外 explicit/protocol failure 候选，也无未换行残尾。实际 suite pass/summary/OK 仍在第 50101/50102/50103 行，但不能覆盖整轮失败。这是 DTS 警告文案的分类边界，不是 CMake 失败旗标或编译 fatal error；DTS 地址差异本身是否可接受未在此验证。

## 2. 缓存路径观察

实际 [xtask.log](/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017/raw/strict-native-phase-v3/AB1/xtask.log:11) 偏移 1138、63B、SHA `a213fe1b38cdb90f43d77e485c347185b6a36081534f7dd25da046a7500ba2bd` 明确选择 `/home/yanlien/.cache/zephyr`。冻结离线 witness SHA `b863d65a...` 的 `actual_stdout_selects_user_cache` 明确记载候选目录下 `.../zephyr/.cache`，两者不同；本任务未追查选择原因、未读改 cache/env，不能声称一致。

## 3. 修订边界

最小建议仅供后续审批：Host 容器读取应匹配已批准 append-newc/gzip 合同，保留逐 archive、gzip EOF/残尾、重复冲突和实际 payload SHA 检查；Guest rootfs 继续严格单 archive。

### 3.1 日志分类

日志若调整，应只针对有准确构建上下文的这条 DTS Warning 语法显式分类并保留原始证据，不作通用 Warning 放行。

### 3.2 负例要求

修订必须有截断/垃圾尾/重复 payload/非法 gzip，以及真实错误、非零 counters、未知 error 文案和 `LINUX_PHA` 残尾负例；当前 null xtask wait/unknown release 仍须拒绝完整正常门。

## 4. 调查范围

已做：准确 17 工件的流式 SHA/size 核对、纯格式函数和孤立 regex 调用；完整偏移/头字节/归档跨度/源码行见 [JSON](/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017/results/strict-native-cache-v3-AB1-auditor-cause-v1.json)，微小原字节保存在 `/home/yanlien/Program/hypervisor/tgoskits/research/cross-path-20261017/raw/strict-native-followup-v3/auditor-cause-v1`。

### 4.1 命令收据

每条实际命令的 argv/env/stdout/stderr 和真实 Popen.wait 收据均在 `commands/`。

### 4.2 未执行项

未做：修复、完整 audit/tests、硬件、build/ready、Git、网络、proc/signal、cache/source 修改。控制器根因另由独立任务处理；本次不宣称 Host/M2/Joint 或整体目标完成。
