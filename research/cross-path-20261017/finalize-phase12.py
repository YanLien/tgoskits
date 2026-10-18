#!/usr/bin/env python3
"""Seal a completed factorial cohort without claiming unpassed research gates."""
import json
from pathlib import Path
import subprocess

from factorial_runner import ARCHIVE, PLAN_FILE, STATUS_FILE, REPO, digest, read, validate_completed, verify_derived, verify_frozen


def main():
    plan, state = read(PLAN_FILE), read(STATUS_FILE)
    expected = validate_completed(plan, state, digest(ARCHIVE/PLAN_FILE))
    verify_frozen(plan)
    summary = read("results/factorial-summary.json")
    baseline = read("results/stage-baseline-summary.json")
    if digest(ARCHIVE/"results/stage-baseline-summary.json") != plan["prerequisites"]["baseline_summary_sha256"]:
        raise ValueError("the registered baseline changed")
    if (summary["plan_sha256"] != state["plan_sha256"] or summary["native_boots"] != 32
            or summary["task_observations"] != 2048 or summary["M1"] or summary["M2"]
            or baseline["independent_boots"] != 8 or baseline["dropped"] or baseline["incomplete"]):
        raise ValueError("summary, baseline or milestone scope does not match accepted evidence")
    for run, accepted in zip(expected, state["completed"]):
        output = ARCHIVE/"results"/run["name"]
        verify_derived(output, accepted)
        if (digest(ARCHIVE/"raw"/(run["name"]+".log")) != accepted["raw_sha256"]
                or digest(output/"analysis-input.log") != accepted["analysis_input_sha256"]):
            raise ValueError("sealed run measurement bytes differ from acceptance")
    for filename, sha in summary["derived_tables_sha256"].items():
        if digest(ARCHIVE/"results"/filename) != sha:
            raise ValueError("final summary table changed")
    for meta_name, source in (("figure-provenance.json", "factorial-summary.json"),
                              ("stage-baseline-figure-provenance.json", "stage-baseline-summary.json")):
        meta = read("results/figures/"+meta_name)
        if meta["summary_sha256"] != digest(ARCHIVE/"results"/source):
            raise ValueError("figure and summary input identities differ")
        for figure in meta["files"]:
            if digest(ARCHIVE/figure["path"]) != figure["sha256"]:
                raise ValueError("rendered figure bytes changed")
    audit = dict(scope="Eight-boot stage baseline and one preregistered eight-block factorial hardware cohort",
        original_recorder_pairs=8, original_recorder_native_tasks=1024, baseline_tasks=baseline["samples"],
        baseline_unique_chains=baseline["full_chain_samples"], factorial_blocks=8, factorial_native_boots=32,
        factorial_task_observations=2048, trace_loss_records=summary["trace_loss_records"],
        source_and_analysis_identity_verified=True, full_phase0_to2_achieved=False, M1=False, M2=False,
        remaining_requirements=["Second controlled CPU-sharing/resource topology and hardware/firmware capability audit closure.",
            "Fixed or adequately characterized active-window frequency and temperature; complete firmware identity boundary.",
            "Residual measurement costs beyond recorder operations; calibration and sample-association limitations.",
            "A/B intensity and phase sensitivity before any stable-interaction/mechanism decision."],
        limitations=plan["limitations"], finalizer_script_sha256=digest(Path(__file__)))
    audit.update(cohort=plan["cohort"], recovery_of=plan.get("recovery_of"))
    (ARCHIVE/"results/phase12-checkpoint-audit.json").write_text(json.dumps(audit, indent=2)+"\n")
    readme = ARCHIVE/"README.md"
    section = '''

## 22. 当前版本阶段基线与随机四组

### 22.1 阶段关联

[阶段报告](results/stage-baseline-report.md)、[阶段图](results/figures/stage-baseline.pdf) 与 `results/stage-baseline-summary.json` 只汇总原八次真板 on 启动。严格唯一子集、歧义分母、实际重叠、原 offset 仿射链与因果窗截断分别保留；Host route 不重复加入串行链。软件 T4 和线程 T6 不冒称硬件 ERET 或设备输出。

### 22.2 四组重复

[四组报告](results/factorial-report.md) 来自新八块32次独立真板启动，共2048条任务观察。种子、Williams顺序、完整运行身份和派生产物均绑定原计划；首次失败停止，不静默替换坏结果。I_AB 按运行级均值和完整块重采样，尾部、DMR及Linux吞吐分列。CPU与内存工作负载的迭代率不能跨工作量解释为优化收益。固件只读构建文本按实际可见性保留，不作固件二进制认证。

### 22.3 复现与未完成项

`factorial_runner.py`、`summarize-factorial.py`、`plot-phase12.py` 和 `finalize-phase12.py` 分别负责一次性编排、完整块统计、标准绘图与归档。绘图环境依赖为 `configs/phase12-plot-requirements.txt`；源码增量与独立应用核验见 `patches/phase12-analysis.patch` 和 `results/phase12-patch-audit.json`。原开销实验与本轮源码冻结不改，所有原始失败/测量字节保留。

本检查点不等于阶段0～2全部验收；完整剩余项见 `results/phase12-checkpoint-audit.json`。第二种CPU拓扑、环境与固件完整身份、残余探针成本、A/B强度及相位敏感性仍须补齐，M1/M2保持false。只有稳定交互后才验证机制，机制成立后才实现联合控制；不将分位数非加性或最大观测值当作耦合或严格WCET/WCRT证明。
'''
    content = readme.read_text()
    if "\n## 22. 当前版本阶段基线与随机四组" not in content:
        readme.write_text(content+section)
    paths = sorted(path for path in ARCHIVE.rglob("*") if path.is_file()
                   and path.name != "SHA256SUMS" and "__pycache__" not in path.parts)
    for path in paths:
        if path.suffix == ".json":
            json.loads(path.read_text())
    manifest = ARCHIVE/"SHA256SUMS"
    manifest.write_text("".join(f"{digest(path)}  {path.relative_to(REPO)}\n" for path in paths))
    result = subprocess.run(["sha256sum", "-c", str(manifest)], cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise ValueError(result.stdout)
    print(f"PHASE12_CHECKPOINT_OK files={len(paths)} blocks=8 native_tasks=2048 M1=0 M2=0 full_phase0_to2=0")


if __name__ == "__main__":
    main()
