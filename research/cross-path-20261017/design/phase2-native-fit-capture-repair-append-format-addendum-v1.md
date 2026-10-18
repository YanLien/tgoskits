# 原生捕获追加格式补充

本补充基于完整离线合同实际到达的第二处格式拒绝，保持[原设计](phase2-native-fit-capture-repair-design.md)及[原计划](phase2-native-fit-capture-repair-plan.md)字节不变。FIT修订已经通过真实组件提取、外部kernel/ramdisk匹配和准确FDT转换，随后`newc_members()`因重复目录误拒绝；整体合同仍未通过，不把局部修复写成成功。

## 1. 实际格式

[成员定位](../raw/strict-native-followup-v1/fit-capture-repair-v1/host-newc-rejection-diagnosis.json)的SHA为`e579f09f94da37280810ae067576a1854bfcfb048b48bb1ed4f356b357ea07ec`。原Host包包含1364B raw newc，后接gzip，解压后54086784B newc；两个档案唯一重复项为`.`，均为0755空目录，没有重复普通文件。

### 1.1 生产者与消费语义

`scripts/axbuild/src/axvisor/bundle.rs::append_guest_bundle()`在最终包超过48MiB时追加gzip。`fs/ax-fs-ng/src/initramfs.rs::unpack_stream()`按顺序消费流，`apply_entry()`复用已存在目录。捕获器却在合并时丢弃`parse_newc()`返回的类型/权限元数据，因而把合法重复目录当成重复载荷。

### 1.2 最小修订

在新工具副本内递归保留成员类型/权限/大小及payload，跨档案仅允许两份均为空目录且权限一致的重复项。重复普通文件即使空或字节相同也仍拒绝；目录/文件冲突或权限不同仍拒绝。同一档案的重复、非法路径、link、截断与padding规则不改。公开`newc_members()`仍返回原payload字典，Host嵌入文件和后续全部原身份门不变；不支持或容忍任意覆盖。

## 2. 验证与预算

本修订必须继续使用原真实AB1完整合同，不以独立目录合并小测替代。先保留hash-only候选与实际wait1的追加目录拒绝，再修改这一处格式处理；任何后续门失败仍保持未通过。

### 2.1 最小行为证明

通过真实`newc_members()`验证跨raw/gzip档案的同权限空目录可以合并，并保留全部不同普通文件；以空普通文件重复及目录权限/类型冲突证明拒绝边界，避免以empty bytes判断目录。原完整capture合同实际再执行，必须经过rootfs、worker编译元数据和case尾门。此前准确FIT单byte拒绝、内置hash损坏拒绝继续保留，不因新修订重复硬件或统计。

### 2.2 材料与停止边界

原512MiB估算未包含新暴露格式问题所需的完整再次执行。为保留所有先前失败和fixture入口错误，本次仅把离线材料上限调整为768MiB；不删除或覆盖证据，不为节省空间mock捕获。Root随后已验证默认沙箱命令可启动、当前约6GB可用，早前ENOSPC来源仍未知。板卡900秒、外层920秒、cleanup10/capture30均不改变；本项硬件启动仍为0，原Trace丢样和releaseunknown不回填。补充按原Spec→Quality实施流程审阅后执行。
