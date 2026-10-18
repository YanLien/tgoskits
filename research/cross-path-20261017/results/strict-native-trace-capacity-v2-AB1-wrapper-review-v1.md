# Capacity v2 AB1 wrapper：离线复核

结论 **PASS**，`blockers=[]`。仅覆盖Root successor wrapper，不是硬件批准；Task1结论和原报告不变。

现时wrapper SHA：`74806ad5a84b3078cd6afe88438a6ba3a9c242724f09f68222f0c355a1acfc0e`。

初版审阅曾 **BLOCKED**：Popen成功后，identity、launch-save或SHA操作抛错会绕过wait。原快照SHA `1ba5948de6e40503ed5ee4a78f91139edf442b4dcd9829677e3c94c12cb5d9f2` 保留。修订171–185行把这些操作放入try，finally对同一真实child实际wait；原异常继续记录。

已只读核对局部红绿证据：AST提取实际Popen块，在identity和launch-save两个故障下使用真实本地Python exit7。旧块两项均绕过wait，外部父另reap7，RED checker实际退出1；新块两项均内部实际wait7并保留原OSError，GREEN checker实际退出0。该证明只覆盖异常等待路径，没有硬件含义。本复核未重跑测试。

metadata修复80–84行现显式校验Root接纳的`Root_copy_metadata`路径和SHA，并要求它是Root_copy结果同目录的`target-metadata.after.json`。现时接纳SHA `1539cd651b743fc85377bfd8fcce11531b1ce2b0f907bb4dddfaf8920cb0c9b5` 与该引用均吻合，避免从未绑定sibling取期望值。

两处差异没有更改既已审阅的新路径/四SHA、从Root-copy实际ready取Cargo bookkeeping、无竞争守卫、单次Popen、GET服务快照或原900/920/10/30秒预算。host witness仍在driver前记录；冻结controller仍在静态/主96门后按原0..60秒校验，过时应拒绝。

本复核未运行wrapper、ready、build、测试、proc、signal、网络或Git；未重验Task1。后续仍须Root准确单次批准及当前宿主/服务门。

[JSON报告](strict-native-trace-capacity-v2-AB1-wrapper-review-v1.json)，SHA：`9a6f0a1d9582ba93632b70d5307e050030da474597d23354e560da1def54c63c`。
