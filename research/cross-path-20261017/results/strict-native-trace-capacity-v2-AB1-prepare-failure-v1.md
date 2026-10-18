# 新追踪容量 v2 AB1 构建准备失败

本次单次验证失败，尚未取得新Guest或Trace。xtask、准确父进程driver wait和原统一exec会话15037实际退出均为1；后续AB0/0停止，不重试本候选。

## 1. 运行与失败

[最终身份报告](strict-native-trace-capacity-v2-AB1-prepare-failure-v1.json)绑定原始日志、工件捕获、真实退出和只读诊断。原有离线Task1验收保持其窄范围，不回填为完整构建通过。

### 1.1 原始终态

`host_prepare`在`ensure_zephyr_source()`调用`verify_zephyr_source()`时失败，`git rev-parse HEAD`返回128。日志共2283B，没有Guest数据或Trace；capture无工件，报告缺失实际kernel路径。清理signals为空、owned group为空，release仍记unknown；原始单次marker保留。

### 1.2 缓存目录缺口

原缓存Git HEAD正常；新缓存含相同25份Git文件，却漏了空目录。`copy_manifest()`只复制文件和符号链接，未保留`.git/refs`及其空子目录；现有文件身份门覆盖不到这个条件。

## 2. 诊断与后续

Root仅在独立临时元数据副本验证原因，没有修改冻结缓存、源码、时间界或原始失败。此处的局部成功不是正常Host或真板容量证明。

### 2.1 局部因果证据

同一25份Git文件，初始`rev-parse`为128；仅在临时副本增加空`refs`目录后，该命令退出0并解析到固定提交`32229d0b6cc60a1906307311b8e79ec483ad1e88`，对真实只读工作树的`status --porcelain`退出0且为空。前后所有元数据文件字节相同，原冻结缓存复查仍返回128。[诊断证据](../raw/strict-native-phase-v2/zephyr-git-readonly-diagnosis-v1/)保留准确命令与实际wait。

### 2.2 恢复条件

下一候选须另行保存所需缓存目录结构及准确身份，并验证真实Git固定版本、干净工作树和生产准备入口，再取得新的单次启动记录。旧v1真板丢样、v2构建失败、未执行后项和未完成正常功能分别保留。完整正常审计器正在准备；相位重复、匹配开销、M2、Joint和研究目标均未完成。
