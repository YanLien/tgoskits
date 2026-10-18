#!/usr/bin/env python3
"""Publish the eight registered board-on stage baselines after the original seal."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from stage_baseline import ADDITIVE_STAGES, AUXILIARY_METRICS, analyze, require_completed_plan, summarize

ARCHIVE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(archive, finalizer_status):
    """Validate the completed original plan before analyzing its board-on cohort."""
    read = lambda relative: json.loads((archive/relative).read_text())
    plan = read("configs/recorder-ops-plan.json")
    state = read("results/recorder-ops-status.json")
    finalizer = json.loads(finalizer_status.read_text())
    selected = require_completed_plan(plan, state, finalizer)
    if (finalizer.get("waiting_for_controller_pid") != state.get("controller_pid")
            or finalizer.get("finished_unix", 0) < state.get("finished_unix", float("inf"))):
        raise ValueError("the successful finalizer must belong to and follow this original controller")
    repo = archive.parent.parent
    for key in ("source_sha256", "control_sha256"):
        if any(digest(repo/path) != expected for path, expected in plan[key].items()):
            raise ValueError("the original recorder-ops source/control freeze changed")
    audit = read("results/recorder-ops-audit.json")
    if (audit.get("native_pairs") != 8 or audit.get("native_boots") != 16
            or not audit.get("source_identity_verified")):
        raise ValueError("the original finalizer audit is absent or incomplete")
    inputs = {}
    identities = {}
    # Validate all eighteen runs, including off and QEMU evidence, without
    # rerunning their controller, analysis, audit, or finalizer.
    for run in plan["pilots"]+[run for block in plan["blocks"] for run in block["runs"]]:
        name = run["name"]
        identity = read(f"configs/{name}/provenance.json")
        decoded = read(f"results/{name}/analysis-input-provenance.json")
        result = read(f"results/{name}/probe_cost/summary.json")
        raw = archive/"raw"/(name+".log")
        log = archive/"results"/name/"analysis-input.log"
        if (identity["runtime"] != run["runtime"] or identity["exit_code"] != 0
                or identity["suite_passed"] is not True
                or digest(raw) != identity["raw_log_sha256"]
                or not decoded["measurement_bytes_unchanged"] or not decoded["decoding_valid_for_analysis"]
                or decoded["raw_sha256"] != identity["raw_log_sha256"]
                or decoded["analysis_input_sha256"] != digest(log)
                or result["recording_mode"] != run["mode"]
                or result["comparison_scope"] != "recorder_operations"
                or result["recording_declaration_version"] != 2
                or not result["task_observations_valid"]
                or result["complete_chain_accepted"] != (run["mode"] == "on")
                or set(result["policies"]) != {"fair", "fifo80"}
                or any(policy["samples"] != 32 for policy in result["policies"].values())):
            raise ValueError(f"original run acceptance or preserved input identity failed: {name}")
        raw_bytes, analysis_bytes = raw.read_bytes(), log.read_bytes()
        marker = b"VIRQ_MEASUREMENT "
        if raw_bytes[raw_bytes.index(marker):] != analysis_bytes[analysis_bytes.index(marker):]:
            raise ValueError(f"original measurement bytes changed: {name}")
        inputs[name] = log
        identities[name] = dict(raw_sha256=identity["raw_log_sha256"],
                                analysis_input_sha256=decoded["analysis_input_sha256"])
    rows, logs = [], []
    for run in selected:
        current, summary = analyze(inputs[run["name"]].read_text())
        for row in current:
            row.update(boot=run["name"], block=run["block"], condition="recorder_on_baseline")
        rows.extend(current)
        logs.append(dict(boot=run["name"], block=run["block"], summary=summary))
    report = summarize(rows)
    report.update(scope="Eight preregistered board-on boots; descriptive stage baseline only",
                  independent_boots=len(selected), original_runs_verified=18,
                  original_finalizer_succeeded=True, original_status_sha256=digest(archive/"results/recorder-ops-status.json"),
                  original_finalizer_status_sha256=digest(finalizer_status),
                  original_audit_sha256=digest(archive/"results/recorder-ops-audit.json"),
                  plan_sha256=digest(archive/"configs/recorder-ops-plan.json"),
                  stage_analysis_sha256=digest(ARCHIVE/"stage_baseline.py"),
                  summary_script_sha256=digest(Path(__file__)), identities=identities,
                  logs=logs, dropped=sum(log["summary"]["dropped"] for log in logs),
                  incomplete=sum(log["summary"]["incomplete"] for log in logs))
    return rows, report


LABELS = dict(zip(ADDITIVE_STAGES, (
    "T0→IrqKick", "IrqKick→WakeBegin", "WakeBegin→Ready", "Ready→Running",
    "Running→软件 GuestEntryBoundary", "软件 GuestEntryBoundary→Guest ISR begin",
    "Guest ISR begin→end", "Guest ISR end→任务 start", "任务 start→end")))
LABELS.update(host_route="Host route 全长（DispatchBegin→End，重叠辅助）",
              t0_to_host_route_end="T0→Host route end（重叠辅助）",
              t0_to_dispatch_begin="T0→Host route begin（重叠辅助）",
              lower_el_timer_sync="低 EL timer synchronize_timer（重叠辅助）",
              lower_el_timer_end_to_dispatch_begin="低 EL timer end→route begin（重叠辅助）",
              t0_to_guest_isr_begin_correlated="T0→Guest ISR begin（原 offset 包围）",
              t0_to_task_end_correlated="T0→任务 end（原 offset 包围）",
              guest_isr_begin_to_host_observation="ISR begin→Host 观察（原 offset 包围）",
              task_end_to_host_observation="任务 end→Host 观察（原 offset 包围）",
              t0_to_guest_isr_begin_causal="T0→ISR begin（因果窗截断）",
              t0_to_task_end_causal="T0→任务 end（因果窗截断）",
              guest_isr_begin_to_host_observation_causal="ISR begin→Host 观察（因果窗截断）",
              task_end_to_host_observation_causal="任务 end→Host 观察（因果窗截断）")


def render(report):
    """Render the Chinese report from already validated summary data."""
    lines = ["# 同一任务链的阶段基线", "",
             f"原计划 18 次运行均成功，既有 finalizer 已成功。这里只汇总其中 {report['independent_boots']} 次独立真板 on 启动；"
             "QEMU 和 off 不进入阶段分布。结果是当前探针版本、名义计数尺度下的描述性观察，M1/M2 保持 false。", "",
             "## 1. 基线范围", "",
             "聚合入口的 `collect()` 先核对 `require_completed_plan()` 的原计划与 finalizer 成功门，"
             "再验证原始日志和分析输入身份；阶段分析的 `analyze()` 复用原有五类验证入口，保留每个策略和样本的关联状态。", "",
             "### 1.1 测量边界", "",
             "T0 是已分类的软件 Host 中断入口。GuestEntryBoundary 是软件进入边界，不能称为硬件 ERET；"
             "任务 end 是 Guest 线程完成计时，不能称为设备输出。当前 EL 不执行所测低 EL timer 同步，其字段和分布保留 null。", "",
             "### 1.2 关联口径", "",
             "每个离散阶段均使用同策略内全部边界唯一的共同关联子集。Host route 与低 EL timer 作为重叠辅助区间单列，"
             "可能与另一核上的 Ready、Running 或 Guest 执行重叠，不得追加到串行链。CSV 的 additive_stage_names 明示每行可加阶段。", "",
             "原始链用 ticks 和同一个策略 offset 的仿射式 constant + coefficient × offset 求界，"
             "先作链代数，再向外取整为 ns。ISR 与任务端点另保留既有 Host 因果窗截断结果，不能拿截断端点界拼接原链。"
             "分位数各自排序，不能相加；仅共同子集的均值和逐样本原始链具有对应的可加关系。"
             "`ADDITIVE_STAGES` 声明串行链，`correlated_sum()` 在求界前保留 offset 系数相关性。", "",
             "## 2. 阶段分布", "",
             "`summarize()` 分策略汇总 `full_chain` 共同子集；辅助 span 与全部样本的观察滞后另保留可用分母，"
             "不以关联失败删除有效的 Host 区间观察。", ""]
    for number, (name, policy) in enumerate(report["policies"].items(), 1):
        residual = policy["rounding_residual_ns"]
        lines += [f"### 2.{number} {'Fair' if name == 'fair' else 'FIFO'}", "",
                  f"完整唯一关联 {policy['full_chain_samples']}/{policy['samples']}（{policy['association_rate']:.2%}）；"
                  f"排除 {policy['excluded_samples']}，歧义 {policy['ambiguous_samples']}，"
                  f"缺失或非串行 {policy['missing_or_nonserial_samples']}。状态：`{json.dumps(policy['statuses'], ensure_ascii=False)}`。", "",
                  "实际边界关系按全部样本分类。Host route end 相对 Ready 的 before/after/same_tick/missing 计数为 "
                  f"`{json.dumps(policy['overlap_classifications']['dispatch_end_vs_ready'])}`，相对 Running 为 "
                  f"`{json.dumps(policy['overlap_classifications']['dispatch_end_vs_running'])}`。"
                  "before/after 比较同一 Host tick 域，same_tick 不推断跨核指令次序；missing 表示未建立唯一可用边界，仍保留分母。"
                  "相对 Guest ISR begin 的原三态计数为 "
                  f"`{json.dumps(policy['overlap_classifications']['dispatch_end_vs_isr'])}`："
                  "certainly_before/certainly_after 比较 route end 与 ISR begin 的校时因果区间，within_clock_uncertainty 表示关系未定。", "",
                  f"校时宽度均值 {policy['calibration_width_ns']['mean']:.3f} ns，最大 {policy['calibration_width_ns']['max']:.3f} ns。"
                  +(f"链 ticks 常数项和 offset 系数残差均为 0；逐段 ns 外取整之和相对整链取整的残差包围为 "
                    f"[{residual['lower']}, {residual['upper']}] ns。" if residual else "没有完整链，无法给出链代数残差。"), "",
                  "下表单位为 ns；数对为保留下界～上界。所有离散阶段使用同一关联子集，辅助区间的 null 不进入其可用数量。", "",
                  "| 区间 | 可用 n | mean | P50 | P99 | P99.9 | max |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for metric, distribution in policy["conditional_distributions_ns"].items():
            if metric in AUXILIARY_METRICS:
                continue
            cells = ([f"{distribution['lower'][stat]:.3f}～{distribution['upper'][stat]:.3f}"
                      for stat in ("mean", "p50", "p99", "p999", "max")]
                     if distribution["samples"] else ["null"]*5)
            lines.append(f"| {LABELS[metric]} | {distribution['samples']} | "+" | ".join(cells)+" |")
        lines += ["", "以下重叠辅助区间按全部有效 IRQ span 单列，分母独立于串行链；它们不能与上表逐段相加：", "",
                  "| 重叠辅助区间 | 可用 n | mean | P50 | P99 | P99.9 | max |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for metric, distribution in policy["all_sample_auxiliary_distributions_ns"].items():
            cells = ([f"{distribution['lower'][stat]:.3f}～{distribution['upper'][stat]:.3f}"
                      for stat in ("mean", "p50", "p99", "p999", "max")]
                     if distribution["samples"] else ["null"]*5)
            lines.append(f"| {LABELS[metric]} | {distribution['samples']} | "+" | ".join(cells)+" |")
        lines += ["", "观察滞后另按全部已接纳样本保留：", "",
                  "| 观察区间（因果窗截断） | n | mean | P50 | P99 | P99.9 | max |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for metric in ("guest_isr_begin_to_host_observation_causal", "task_end_to_host_observation_causal"):
            distribution = policy["all_sample_observation_distributions_ns"][metric]
            cells = [f"{distribution['lower'][stat]:.3f}～{distribution['upper'][stat]:.3f}"
                     for stat in ("mean", "p50", "p99", "p999", "max")]
            lines.append(f"| {LABELS[metric]} | {distribution['samples']} | "+" | ".join(cells)+" |")
        lines.append("")
    lines += ["## 3. 完整性与限制", "",
              "每次运行的 `logs` 保留独立摘要，`identities` 锚定原日志和分析输入；"
              "丢样与无效输入门控制报告能否生成，观测解释则受软件边界与有限样本约束。", "",
              "### 3.1 丢样与无效输入", "",
              f"运行记录丢失 {report['dropped']}，不完整 {report['incomplete']}，本次接纳的无效日志 {report['invalid_logs']}；"
              "任何非法、丢失或不完整输入均在输出前拒绝整份报告，不把拒绝计入有效样本。", "",
              "### 3.2 可解释范围", "",
              "每策略最多 256 个任务，P99.9 对应最大观察次序统计量；它不是极端尾部精确估计或 WCET。"
              "8 次独立启动没有变成 256 个独立实验重复；本报告不进行启动级推断或策略优劣比较。"
              "有限校时、环境快照和名义频率不认证运行窗口内的物理时钟误差。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--finalizer-status", type=Path, default=Path("/tmp/recorder-ops-finalizer-status.json"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    try:
        rows, report = collect(args.archive.resolve(), args.finalizer_status)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"invalid stage baseline: {error}\n")
    output = args.output_dir or args.archive/"results"
    output.mkdir(parents=True, exist_ok=True)
    with (output/"stage-baseline-samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output/"stage-baseline-summary.json").write_text(json.dumps(report, indent=2)+"\n")
    (output/"stage-baseline-report.md").write_text(render(report))
    print(json.dumps(dict(independent_boots=report["independent_boots"], samples=report["samples"],
                          full_chain_samples=report["full_chain_samples"], M1=False, M2=False)))


if __name__ == "__main__":
    main()
