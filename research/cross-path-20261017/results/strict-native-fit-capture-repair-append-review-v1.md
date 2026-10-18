# 原生捕获追加格式补充审阅

**Approved**，无阻断问题。本结论仅批准[追加格式补充](../design/phase2-native-fit-capture-repair-append-format-addendum-v1.md)的局部设计与验证安排，补充SHA为 `eb388336e4fbc73ebb1caaaaa4a0360a77f3c58cd9757e67232a56fd5d471502`。

实际hash-only完整合同已过FIT组件、外部kernel/ramdisk和FDT门，随后因追加gzip中的重复空目录`.`拒绝，wait1、链false。定位记录与生产者追加gzip、Host按顺序解包并复用目录的源码一致；还没有完整GREEN。

递归保留真实parse_newc元数据，仅合并同权限空目录，可以修复该格式误拒绝。重复普通文件包括空文件、相同字节，以及类型/mode冲突仍拒绝；单档案重复、路径/link/截断/padding检查、公开返回字典及全部后续身份门保持。目录合并和必要拒绝的小合同充分，仍须再执行原真实完整capture以证明尾门，不能以小测替代。

两份选定生产/消费源与原身份清单匹配：bundle.rs SHA `4a4b4e30c80c5b3deac3af32a126202342df518dc42f10c480643b1e2a813f5d`；initramfs.rs SHA `95deabb7596200eea8d0db53260487fd0244a7915c15c0f47435c178dc7b2bf5`。

为保留全部失败材料，768MiB离线预算合理；已有材料加一次完整捕获约626714200B。未删历史、未改变900/920/10/30秒原预算。空间记录只证明命令恢复启动，ENOSPC根因仍未知。

局部stdlib身份、引用及证据状态检查实际wait=0，原设计/计划SHA保持。未执行原工具、分析器、构建或硬件；本项硬件0，原Trace丢样19839、Host失败、release unknown及goal/M2/Joint状态不回填。完整身份与退出见[审阅JSON](strict-native-fit-capture-repair-append-review-v1.json)及[检查执行记录](../raw/strict-native-followup-v1/fit-capture-append-review-v1/execution.json)。
