# 研究代码版本与实验归档

代码提交保存可审阅实现，实验归档保存实际运行事实。当前完整状态见工作区根目录[研究进度](../../../研究进度.md)；[旧README](README.md)属于已封存历史材料，原字节保留。

## 1. 已提交实现

每组代码按已核验的来源分别提交，不把新候选状态回写到已有真板版本。

### 1.1 测量与实验入口

`6d2443c9b`保存92份测量实现、分析器、Guest压力源及板卡配置，其字节逐项等于[强度计划](configs/intensity-v3-plan.json)的696份源清单。`052f74240`保存130份实验、统计、重放及冻结输入，逐项匹配既有控制清单或封存SHA。历史运行脚本仍须遵守各自报告的版本与前置条件，不直接针对当前树重跑旧finalize入口。

### 1.2 捕获修订

新`capture_native.py`允许实际FIT缺少内置hash并记录缺席，仍校验存在的hash和全部外部绑定；`_newc_entries()`只允许跨档案复用同权限空目录。完整真实保存AB1合同通过，且已完成[Spec](results/strict-native-fit-capture-repair-spec-review-v1.md)、[Quality](results/strict-native-fit-capture-repair-quality-review-v1.md)及[Root接纳](results/strict-native-fit-capture-repair-root-acceptance-v1.json)。[完整离线报告](results/strict-native-fit-capture-repair-v1.md)区分事后补充使用链与原正常功能失败。

## 2. 复现与证据范围

Git保存代码和明确选入的注册输入；实验工件留在同一研究目录的本地归档，通过清单逐项核验。未推送或合并。

### 2.1 运行前置

`native_once.py`须与批准的`inputs.json`、普通源码、缓存清单和`evidence/`配套冻结。捕获合同也需要已保存的实际raw及17工件；单独检出脚本不等于取得这些运行输入。禁止以新构建补写旧运行使用链。大体积raw、镜像和构建缓存未加入Git，完整材料仍在本地原位置；`.gitignore`只避免整目录误加入，已审阅的历史包内源文件可精确选入。

### 2.2 尚未完成

原AB1正常功能仍失败，Trace dropped=19839，原capture链false、releaseunknown。新捕获修订只使补充post-exit链为true，未启动新板卡任务。新容量候选、相位正常功能、对应版本的开销和随机重复仍须各自验证；M2、Joint及阶段0～2整体尚未完成。
