# 原生 FIT 捕获修订设计

本修订恢复实际RK3588启动工件的离线使用链核验，不改变Host、Guest、压力源或追踪行为。依据为[AB1失败审计](../results/strict-native-phase-v1-AB1-failure-audit-v1.md)及[保存FIT结构](../raw/strict-native-followup-v1/FIT-structure-readonly-v1.json)：实际default配置的kernel、ramdisk、fdt均没有hash子节点，原`fit_components()`却强制要求它。用户已有持续研究授权适用；原单次AB1与后两项的停止状态不变。

## 1. 工件核验

`capture_native.py`已经从真实日志定位FIT、Host BIN和最终Host initramfs，并比较提取内容及Host DTB的准确转换。内置hash不是实际打包器提供的能力，应将其存在性与外部输入绑定分开记录。

### 1.1 方案选择

保留强制hash会持续拒绝现有真实格式；修改ostool打包器添加hash会改变生产/构建路径。采用最小消费方修订：允许缺少内置hash，但任何存在的hash仍须验证；外部BIN/initramfs字节身份及FDT转换全部匹配后，才可声明该post-exit工件使用链核验完成。不能因此声称签名、可信启动或boot前认证。

### 1.2 行为约束

`fit_components()`继续按default配置选择组件，计算保存payload的SHA，拒绝不支持的hash算法与错误hash，新增字段明确内置hash缺席。`capture_native()`保留kernel/ramdisk外部SHA比较、`verify_fdt_transform()`、Host newc嵌入配置/资源/Guest载荷、rootfs三普通文件、worker编译源/参数和准确case核验。只在这些原有条件全部通过后完成使用链；不得仅删除报错而略过绑定。

## 2. 离线验证

验证使用已保存AB1 raw及17工件；原target文件如仍被读取，必须先与保存引用逐项匹配，禁止重建。原工具、原失败capture.json和89文件封存均不修改。新增结果只说明事后补充验证，不能改写原失败、释放unknown或零逐事件导出的事实。

### 2.1 最小回归

同一真实格式的完整捕获合同先对未改副本执行并观察`FIT component has no integrity hash`失败，再修消费方并执行。核验仍须经过完整真实`capture_native()`流水线。另用明确标为software-only的私有fixture将FIT中一个选定payload字节改坏，保持外部期望输入不变，要求真实调用拒绝`FIT bytes differ from actual kernel/initramfs`；不得用测试自行实现绑定规则或生成正常Guest日志。原v2 package证明替换了FIT/FDT解析，尚未找到可复用的独立纯FIT hash合同。因此以最小software-only FIT直接调用真实`fit_components()`验证存在hash但校验值错误时仍拒绝，不扩为格式或算法清单。

### 2.2 接续条件

本项不修Trace丢样、不增加追踪容量、不开始分析或板卡任务。单独交付补丁、红绿实际退出、补充使用链结果与限制，实施完成先Spec后Quality。随后再处理CPU3追踪容量及失败导出，冻结新的测量版本并验证真实完整功能、同版本开销与随机重复；任何缺项不宣布阶段2完成。
