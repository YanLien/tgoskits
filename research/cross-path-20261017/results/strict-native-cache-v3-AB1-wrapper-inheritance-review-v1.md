# v3 AB1 wrapper 继承差异复核

本次窄范围离线附录结论为 **PASS**，阻断项为空。仅复核 Root 启动准备的准确迁移及原保护门继承，详细身份见 [JSON 附录](strict-native-cache-v3-AB1-wrapper-inheritance-review-v1.json)。

## 1. 准确迁移

新 wrapper 继承已审 v2 实现，其运行控制流可由完整字节与 AST 等价核对承接原审阅，不需要为身份迁移增加测试。

### 1.1 源码身份

[新 wrapper](../raw/strict-native-phase-v3/AB1-launch-supervisor.py) SHA 为 `d7ebb6948ac065c3fddfd1e618bfb381e9355029d7261cd0a4a9808e704d90f2`；父 wrapper 为 `74806ad5a84b3078cd6afe88438a6ba3a9c242724f09f68222f0c355a1acfc0e`，[继承审阅](strict-native-trace-capacity-v2-AB1-wrapper-review-v1.json)为 `9a6f0a1d9582ba93632b70d5307e050030da474597d23354e560da1def54c63c`。父源码经10项各一次的精确替换后，与新源码全部字节及完整 AST 相同，保存 patch 与实际 diff 相符。替换只含 v3 路径、四个工具 SHA、acceptance 文件名及 prepare 描述字段。

新工具根为 `/tmp/crosspath-native-cache-v3-tools-jrhcn15t`，freeze SHA 为 `0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8`。当前 native/capture/inputs/freeze 四文件 SHA 与 wrapper 常量一致；准确 inputs 的 source/target/source702 对应本次 v3。

### 1.2 实际等待继承

含唯一 `subprocess.Popen` 的实际 `With` 块逐字节及 AST 不变，块 SHA 为 `cc1652e2157b4f3642d47d5247cfec250fa48e2c5c9f5a502b72dda3297de99b`。Popen 后的 identity、launch-save 和 sha 仍在 `try` 内，`finally` 对同一原始 `child` 调用真实 `wait()`；记录失败不能跳过等待，原异常仍进入外层 error 收据。原已审异常路径回归证据据此继承，本次未重跑。

## 2. 接纳与保护

Root acceptance 把独立副本结果、target metadata 和准确新输入连在一起；wrapper 在启动时仍须重新通过原实时门。

### 2.1 副本与输入绑定

[Root acceptance](strict-native-cache-v3-task1-root-acceptance-v1.json)当前 SHA 为 `79d2b66a2f6291b2f6cf25dbb3749c1636c7967482030a1b65139ceac8d53f83`，21项引用当前 SHA/size 均相符，含 wrapper、Task1 Spec/Quality 与 normal 审计器的准确已审材料。normal Quality SHA 为 `04c99a4182148523e862acb6d20af07fdd74df7be42b95ecb1a04179e7f87b28`；其逻辑和端到端 GREEN 未在本附录重审。

wrapper 要求 acceptance 的准确参数 SHA、offline通过、同freeze和未启动硬件；Rootcopy须 `passed` 且同freeze。metadata引用须准确指向Rootcopy结果同目录的 `target-metadata.after.json` 并核SHA；该文件SHA为 `f91761e8a96b380f8c529cc5e62ee472111bb2c7cf47de27539d35def7d9c523`，内容为7784项、metadata SHA `9b601bda1535cdff156a8e0dd2e9111a73583e9b44a6e5a7a43843d3d6db9b66`。原逐项 `lstat` 比较代码保持。本次只读既有收据：copyready0、正式拒绝2、直接父wait0及原工具exit0/session81327/chunk e0cb5d，target未变且无marker。

### 2.2 实时门与结论

case/output/marker、exclusive receipt、host namespace/boot、只读所有权检查与有界服务GET均保留。approval仍使用Rootcopy实际Cargo runtime快照，正式native要求与最新ready相同；60秒fresh witness、900/920/cleanup10/capture30秒及512MiB预算不变。准确静态一致性核对exit0，chunk为 `79292d`。

本次只新建两份附录，未执行被审代码、ready、prepare、build、tests或硬件，也未操作Git/network/proc/signal或扫描候选/target/cache/源/主96。已封Task1 Quality JSON/MD的SHA保持。Root随后仍须取得当前真实host witness与availability；实际AB1完整证据另行审阅，通过前停止AB0/0。本附录不授予硬件权限，正常Host、零丢样、M2、Joint与goal均未成立。
