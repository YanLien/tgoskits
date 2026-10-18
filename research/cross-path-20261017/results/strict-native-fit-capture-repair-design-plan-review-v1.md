# 原生 FIT 捕获修订设计与计划审阅

设计、计划及总评均为 **Approved**，无阻断问题。本审阅先判设计，再判计划与设计一致；没有实施补丁或执行原工具。

最终[设计](../design/phase2-native-fit-capture-repair-design.md) SHA为 `32725712e6d5f90620091236b887d1c8e539f31297ec0e649cc6fdd4e60c0337`；[计划](../design/phase2-native-fit-capture-repair-plan.md) SHA为 `7076274263d4076b7cefe1cce9c0e8de469c0f07d62f6233f1fbac3399637bba`。

设计恢复实际无hash FIT的消费能力，仍核所有存在hash，并保留外部BIN/initramfs、准确FDT转换、Host内嵌资产、rootfs/init、worker编译来源和case门。只有完整流水线末端可以完成补充post-exit使用链；没有签名或boot前认证宣称，也不改写原AB1失败。

计划中的同输入完整RED/GREEN、真实capture的单payload损坏拒绝和真实fit_components的最小错误hash拒绝，分别保护恢复能力与两项必要拒绝门。最终稿已明确旧package证明使用解析器替身，不能冒充真实FIT证明。依赖与输入引用可定位，三个任务捕获加一个私有工件负例集等材料估算467.89MiB，预算512MiB可行。

实施时需注意：capture_native将错误收入报告后返回；回归入口须断言完整链和准确错误并传播实际退出，不能仅凭进程退出0判绿。原Trace丢样19839、逐事件导出0、Host功能false、release unknown，以及goal/M2/Joint未完成状态保持不变。

局部stdlib文档、3处引用及选定保存身份检查实际wait=0；未运行capture、分析器、build、board、QEMU、proc或Git，新增硬件任务0。本审阅没有重复全量17工件核验，也未读取live target；实施前的17份精确比较仍按设计执行。

实际阅读来源SHA、判断理由和边界见[审阅JSON](strict-native-fit-capture-repair-design-plan-review-v1.json)；原stdout及真实退出见[执行记录](../raw/strict-native-followup-v1/fit-capture-design-review-v1/check-execution.json)。
