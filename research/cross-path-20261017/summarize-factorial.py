#!/usr/bin/env python3
"""Summarize only the complete, accepted hardware factorial cohort."""
import csv
import json
import math
from pathlib import Path
import statistics

from factorial_runner import ARCHIVE, PLAN_FILE, STATUS_FILE, digest, identity_for, normalized_fit_sha256, read, validate_completed, verify_derived, verify_frozen
from factorial_statistics import CONDITIONS, summarize_blocks

METRICS = ("release_to_completion", "irq_entry_to_completion")
POLICIES = ("fair", "fifo80")


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def descriptive(values):
    ordered = sorted(values)
    return dict(mean=statistics.mean(ordered), p50=statistics.median(ordered),
                p99=ordered[math.ceil(.99*len(ordered))-1], p999=ordered[math.ceil(.999*len(ordered))-1],
                maximum_observed=ordered[-1])


def main():
    plan, state = read(PLAN_FILE), read(STATUS_FILE)
    expected = validate_completed(plan, state, digest(ARCHIVE/PLAN_FILE))
    verify_frozen(plan)
    from stage_baseline import summarize as summarize_stages
    run_rows, event_rows, environmental, all_stages = [], [], [], []
    for run, accepted in zip(expected, state["completed"]):
        name = run["name"]
        output = ARCHIVE/"results"/name
        verify_derived(output, accepted)
        if (accepted["raw_sha256"] != digest(ARCHIVE/"raw"/(name+".log"))
                or accepted["analysis_input_sha256"] != digest(output/"analysis-input.log")):
            raise ValueError("accepted measurement bytes changed")
        fixed, linux = identity_for(run)
        if fixed != read(f'configs/{plan["cohort"]}-fixed-inputs.json') or linux != read(f'configs/{plan["cohort"]}-{plan["conditions"][run["condition"]]["scenario"]}-inputs.json'):
            raise ValueError("assigned cohort input identity changed")
        if accepted["host_fit_sha256"] != digest(ARCHIVE/"configs"/name/"host-boot.fit"):
            raise ValueError("accepted Host FIT identity changed")
        if accepted["host_fit_content_sha256"] != normalized_fit_sha256((ARCHIVE/"configs"/name/"host-boot.fit").read_bytes()):
            raise ValueError("accepted normalized Host FIT content changed")
        task, load = read(f"results/{name}/task/summary.json"), read(f"results/{name}/load/summary.json")
        with (output/"task/samples.csv").open() as stream:
            samples = list(csv.DictReader(stream))
        if len(samples) != 64 or any(row["trace_loss"] != "False" for row in samples):
            raise ValueError("missing or lossy task rows")
        for sample in samples:
            event_rows.append(dict(**run, policy=sample["policy"], sample=int(sample["sample"]),
                **{metric+suffix: float(sample[metric+suffix]) for metric in METRICS for suffix in ("_lower_ns", "_upper_ns")},
                task_deadline_miss=sample["task_deadline_miss"]))
        runtime = read(f"results/{name}/runtime/summary.json")
        if runtime["dropped"] or runtime["incomplete"]:
            raise ValueError("runtime completeness failed")
        for policy in POLICIES:
            stat = task["policies"][policy]
            throughput = load["loads"][policy]["fenced_throughput"]
            run_rows.append(dict(**run, policy=policy, tasks=stat["samples"],
                **{metric+suffix: stat[metric+suffix]["mean"] for metric in METRICS for suffix in ("_lower_ns", "_upper_ns")},
                deadline_miss_true=stat["deadline_miss_counts"]["true"], deadline_miss_unknown=stat["deadline_miss_counts"]["unknown"],
                task_execution_mean_ns=stat["task_execution_ns"]["mean"],
                isr_to_task_start_mean_ns=stat["isr_end_to_task_start_ns"]["mean"],
                release_lateness_mean_ns=stat["release_lateness_ns"]["mean"],
                linux_iterations_per_second=throughput["iterations_per_second"],
                linux_iterations_per_second_causal_lower=throughput["iterations_per_second_causal_lower"],
                linux_iterations_per_second_causal_upper=throughput["iterations_per_second_causal_upper"],
                linux_logical_read_bytes_per_second=throughput.get("logical_read_bytes_per_second"),
                linux_logical_write_bytes_per_second=throughput.get("logical_write_bytes_per_second"),
                trace_records=runtime["records"], trace_dropped=runtime["dropped"], trace_incomplete=runtime["incomplete"]))
        for kind in ("thermal", "frequency"):
            with (output/kind/"samples.csv").open() as stream:
                environmental.extend(dict(**run, observation=kind, **row) for row in csv.DictReader(stream))
        environmental.append(dict(**run, observation="firmware_build_text",
            uboot_build_banners=" | ".join(accepted["firmware"]["uboot_build_banners"]),
            bl31_build_banners=" | ".join(accepted["firmware"]["bl31_build_banners"]),
            exact_firmware_binary_identity_verified=False))
        all_stages.extend(dict(**run, **row) for row in read(f"results/{name}/stage_baseline/samples.json"))
    effects, conditions, stage_conditions = {}, {}, {}
    for policy in POLICIES:
        effects[policy] = {}
        conditions[policy] = {}
        for metric in METRICS:
            blocks = []
            for block in plan["blocks"]:
                selected = [r for r in run_rows if r["block"] == block["block"] and r["policy"] == policy]
                if len(selected) != 4 or {r["condition"] for r in selected} != set(CONDITIONS):
                    raise ValueError("complete block must contain exactly one run per condition")
                blocks.append(dict(block=block["block"], conditions={r["condition"]:
                    [r[metric+"_lower_ns"], r[metric+"_upper_ns"]] for r in selected}))
            effects[policy][metric] = summarize_blocks(blocks, seed=plan["bootstrap_seed"], resamples=plan["bootstrap_resamples"])
            by_order = {}
            for block, interaction in zip(plan["blocks"], effects[policy][metric]["block_interactions"]):
                by_order.setdefault("/".join(block["order"]), []).append(interaction)
            effects[policy][metric]["by_registered_order"] = {
                order: dict(blocks=[r["block"] for r in rows], independent_blocks=len(rows),
                            mean_bounds_ns=[statistics.mean(r["bounds_ns"][side] for r in rows) for side in (0, 1)],
                            limitation="Two blocks per order are descriptive sensitivity, not adequate independent inference.")
                for order, rows in by_order.items()}
        for condition in CONDITIONS:
            selected = [r for r in event_rows if r["policy"] == policy and r["condition"] == condition]
            runs = [r for r in run_rows if r["policy"] == policy and r["condition"] == condition]
            n = len(selected)
            conditions[policy][condition] = dict(independent_boots=len(runs), tasks=n,
                **{metric: {"lower_ns": descriptive([r[metric+"_lower_ns"] for r in selected]),
                            "upper_ns": descriptive([r[metric+"_upper_ns"] for r in selected])} for metric in METRICS},
                deadline_miss_ratio_clock_bounds=[sum(r["task_deadline_miss"] == "true" for r in selected)/n,
                    sum(r["task_deadline_miss"] != "false" for r in selected)/n],
                p999_is_maximum_order_statistic=math.ceil(.999*n) == n,
                linux_iterations_per_second_run_mean=statistics.mean(r["linux_iterations_per_second"] for r in runs),
                linux_workload=plan["conditions"][condition]["scenario"],
                linux_logical_read_bytes_per_second_run_mean=(statistics.mean(r["linux_logical_read_bytes_per_second"] for r in runs)
                                                            if condition in ("B", "AB") else None))
    for condition in CONDITIONS:
        stage_conditions[condition] = summarize_stages([r for r in all_stages if r["condition"] == condition])
    report = dict(scope=plan["scope"], independent_complete_blocks=8, native_boots=32, task_observations=len(event_rows),
        cohort=plan["cohort"], recovery_of=plan.get("recovery_of"),
        plan_sha256=digest(ARCHIVE/PLAN_FILE), summary_script_sha256=digest(Path(__file__)),
        primary_metric=plan["primary_metric"], secondary_metric=plan["secondary_metric"],
        effects=effects, conditions=conditions, stages_by_condition=stage_conditions,
        firmware_observation_coverage={key: sum(bool(r["firmware"][key]) for r in state["completed"])
                                       for key in ("uboot_build_banners", "bl31_build_banners")},
        trace_loss_records=sum(r["trace_dropped"]+r["trace_incomplete"] for r in run_rows)//2,
        M1=False, M2=False, limitations=plan["limitations"])
    write_csv(ARCHIVE/"results/factorial-run-means.csv", run_rows)
    write_csv(ARCHIVE/"results/factorial-task-endpoints.csv", event_rows)
    write_csv(ARCHIVE/"results/factorial-environment.csv", environmental)
    report["derived_tables_sha256"] = {filename: digest(ARCHIVE/"results"/filename) for filename in (
        "factorial-run-means.csv", "factorial-task-endpoints.csv", "factorial-environment.csv")}
    (ARCHIVE/"results/factorial-summary.json").write_text(json.dumps(report, indent=2)+"\n")
    lines = ["# 四组真板均值交互报告", "", "## 1. 实验范围", "",
        "本报告仅在预定八个完整块的 32 次独立真板启动全部验收后生成。每启动 Fair/FIFO 各 32 条任务，共 2048 条；策略在启动内固定顺序，分别分析，不作策略随机试验。原始计划、每启动完整 Trace、源码/输入身份和环境快照分别保留。", "",
        "### 1.1 对照含义", "",
        "0/A 使用 Linux CPU 工作负载，B/AB 使用 16 MiB 已知答案内存工作负载。A 为 CPU2→CPU0 的 SGI15，2 ms 周期、每批两次；关键 CNTP PPI30 在 CPU0，关键 Guest 在 CPU1，Linux 在 CPU3。0 的 Linux 仍访问内存，逻辑读写速率不代表 DRAM 总线带宽。", "",
        "### 1.2 测量限制", "",
        "主指标从计划释放到 Guest 线程任务完成；另列 Hypervisor 软件 T0 到同一完成点。T4 为后端调用前的软件边界，T6 不是设备输出。频温为窗口前后快照，当前没有固定 OPP 或连续覆盖。U-Boot/BL31 构建文本按实际可见性归档，其覆盖见 JSON 和环境 CSV；文本不能认证固件二进制身份。阶段0/1完整验收及条件敏感性仍未完成，M1/M2 保持 false。", "",
        "## 2. 交互与重复", "",
        "交互按同一指标的运行均值计算 AB−A−B+0，校时端点按符号向外传播。10000 次重采样整块，上下界共同抽取块索引；经验百分位包围不保证八块覆盖率或物理校准误差。逐块和删除一块、前后半段的敏感性见 JSON；启动内任务不作独立重复。", "",
        "### 2.1 均值交互", "",
        "| 策略 | 端点 | 交互均值区间 µs | 经验95%包围 µs | 正/负完整块 |", "| --- | --- | --- | --- | --- |"]
    for policy in POLICIES:
        for metric in METRICS:
            effect = effects[policy][metric]
            low, high = effect["interaction_mean_bounds_ns"]
            lower, upper = effect["bootstrap_95_bounds_ns"]
            lines.append(f'| {policy} | {metric} | {low/1000:.3f}～{high/1000:.3f} | {lower/1000:.3f}～{upper/1000:.3f} | {effect["positive_block_bounds"]}/{effect["negative_block_bounds"]} |')
    lines += ["", "### 2.2 证据判定", ""]
    for policy in POLICIES:
        lower, upper = effects[policy][METRICS[0]]["bootstrap_95_bounds_ns"]
        message = "经验区间跨越零，当前条件下没有稳健的交互证据" if lower <= 0 <= upper else "经验区间未跨零，构成交互线索，仍需条件敏感性和机制对照"
        lines.append(f"{policy}：{message}。有限条件和功效不能证明所有负载下不存在耦合，也不证明直接因果传播。\n")
    lines += ["## 3. 尾部与吞吐", "", "尾部分布单列，不进入加性交互。每策略/条件 256 个任务的 P99.9 退化为最大次序统计量，观察 DMR 不是未来保证；最大观测时延不构成 WCET/WCRT。", "",
        "### 3.1 任务分布", "", "| 策略/条件 | release→end 均值 µs | P99 µs | P99.9/最大 µs | DMR 时钟分类界 |", "| --- | --- | --- | --- | --- |"]
    for policy in POLICIES:
        for condition in CONDITIONS:
            group = conditions[policy][condition]
            lo, hi = (group[METRICS[0]][side] for side in ("lower_ns", "upper_ns"))
            lines.append(f'| {policy}/{condition} | {lo["mean"]/1000:.3f}～{hi["mean"]/1000:.3f} | {lo["p99"]/1000:.3f}～{hi["p99"]/1000:.3f} | {lo["p999"]/1000:.3f}～{hi["p999"]/1000:.3f} | {group["deadline_miss_ratio_clock_bounds"]} |')
    lines += ["", "### 3.2 普通虚拟机吞吐", "", "CPU 与内存工作负载分别解释，不能将 B/0 迭代率比称为同工作量性能损失。精确围栏、Host 因果区间与逻辑字节分项保存在逐启动 CSV；内存逻辑读写包含可缓存访问，不认证 PMU/DRAM 计数。", "",
        "| 策略/条件 | Linux 迭代率运行均值 iterations/s | 逻辑读取 MB/s |", "| --- | --- | --- |"]
    for policy in POLICIES:
        for condition in CONDITIONS:
            group = conditions[policy][condition]
            logical = group["linux_logical_read_bytes_per_second_run_mean"]
            logical_text = f"{logical/1e6:.3f}" if logical is not None else "不适用"
            lines.append(f'| {policy}/{condition} | {group["linux_iterations_per_second_run_mean"]:.3f} | {logical_text} |')
    lines += ["", "## 4. 复现与后续门", "", "`factorial_runner.py` 保留一次性计划和终态，任意失败停止且不静默替换。`summarize-factorial.py` 复核冻结身份、完整块和原始字节后生成本文及 JSON/CSV；每组 `stage_baseline` 另报唯一关联比例及重叠，不能把 Host route 全长再加到关键链。", "",
        "### 4.1 完整性", "", f'已验收 {len(event_rows)} 条任务观察，runtime dropped/incomplete 总数为 {report["trace_loss_records"]}。阶段关联率与条件分布见 factorial-summary.json；零记录丢失不自动证明所有阶段都能唯一关联。', "",
        "### 4.2 继续条件", "", "阶段0的第二类共享/亲和性对照、逐次固件身份、完整残余成本与窗口环境覆盖、A/B强度和相位敏感性仍需按实际能力补齐。只有稳定交互后才进行阶段3机制干预；机制成立后才实现联合控制，不据本轮直接宣称优化收益。", ""]
    (ARCHIVE/"results/factorial-report.md").write_text("\n".join(lines))
    print("FACTORIAL_SUMMARY_OK blocks=8 native_boots=32 tasks=2048 M1=0 M2=0")


if __name__ == "__main__":
    main()
