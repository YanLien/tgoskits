"""Join existing validators into an explicitly conditional, correlated stage chain.

Host points have coordinate ``ticks`` and Guest points ``ticks + offset``.
The same policy calibration offset is retained in every affine expression.
Causally clipped endpoint bounds are separate observations, never summands.
"""

from collections import Counter
from pathlib import Path
import sys

ANALYSIS = Path(__file__).resolve().parents[2] / "virtualization/axvm/tests/analysis"
if str(ANALYSIS) not in sys.path:
    sys.path.insert(0, str(ANALYSIS))

from analyze_virq_isr import analyze as analyze_isr
from analyze_virq_ready import analyze as analyze_ready
from analyze_virq_runtime import analyze as analyze_runtime
from analyze_virq_stages import analyze as analyze_stages
from analyze_virq_task import analyze as analyze_task, stats

ADDITIVE_STAGES = (
    "t0_to_irq_kick", "irq_kick_to_wake_begin", "wake_begin_to_ready",
    "ready_to_running", "running_to_guest_entry_boundary",
    "guest_entry_boundary_to_guest_isr_begin", "guest_isr_execution",
    "guest_isr_end_to_task_start", "task_execution",
)

# A group is an addition contract, not an attribution to an exclusive subsystem.
METRICS = {
    **{name: (start, end, "serial_chain") for name, start, end in zip(ADDITIVE_STAGES,
        ("t0", "irq_kick", "wake_begin", "ready", "running", "guest_entry_boundary",
         "guest_isr_begin", "guest_isr_end", "task_start"),
        ("irq_kick", "wake_begin", "ready", "running", "guest_entry_boundary",
         "guest_isr_begin", "guest_isr_end", "task_start", "task_end"))},
    "host_route": ("dispatch_begin", "dispatch_end", "overlapping_auxiliary"),
    "t0_to_host_route_end": ("t0", "dispatch_end", "overlapping_auxiliary"),
    "t0_to_dispatch_begin": ("t0", "dispatch_begin", "overlapping_auxiliary"),
    "lower_el_timer_sync": ("timer_sync_begin", "timer_sync_end", "overlapping_auxiliary"),
    "lower_el_timer_end_to_dispatch_begin": ("timer_sync_end", "dispatch_begin", "overlapping_auxiliary"),
    "t0_to_guest_isr_begin_correlated": ("t0", "guest_isr_begin", "correlated_endpoint"),
    "t0_to_task_end_correlated": ("t0", "task_end", "correlated_endpoint"),
    "guest_isr_begin_to_host_observation": ("guest_isr_begin", "host_isr_observed", "observation_lag"),
    "task_end_to_host_observation": ("task_end", "host_task_observed", "observation_lag"),
}
CAUSAL_METRICS = ("t0_to_guest_isr_begin_causal", "t0_to_task_end_causal",
                  "guest_isr_begin_to_host_observation_causal", "task_end_to_host_observation_causal")
AUXILIARY_METRICS = tuple(name for name, (_, _, group) in METRICS.items() if group == "overlapping_auxiliary")
BOUND_FIELDS = ("constant_ticks", "offset_coefficient", "lower_ticks", "upper_ticks", "lower_ns", "upper_ns")


def _bounds(constant, coefficient, low, high, frequency):
    endpoints = (constant+coefficient*low, constant+coefficient*high)
    lower, upper = min(endpoints), max(endpoints)
    return dict(constant_ticks=constant, offset_coefficient=coefficient,
                lower_ticks=lower, upper_ticks=upper,
                lower_ns=lower*1_000_000_000//frequency,
                upper_ns=-(-upper*1_000_000_000//frequency))


def _set_bounds(row, name, bounds):
    row.update({f"{name}_{field}": bounds[field] for field in BOUND_FIELDS})


def correlated_sum(row, metric_names):
    """Add contiguous, non-overlapping affine intervals before bounding offset.

    An auxiliary Host route cannot be added to the cross-CPU serial chain.
    This API also permits a diagnostic Guest/Host round trip, whose offset
    coefficients cancel exactly rather than widening two independent bounds.
    """
    previous, constant, coefficient = None, 0, 0
    names = list(metric_names)
    if not names:
        raise ValueError("an additive chain needs at least one interval")
    for name in names:
        if name not in METRICS or METRICS[name][2] == "overlapping_auxiliary":
            raise ValueError(f"{name} is not an additive interval; Host routes may overlap")
        start, end, _ = METRICS[name]
        if previous is not None and start != previous:
            raise ValueError("additive intervals must be contiguous and non-overlapping")
        if row.get(name+"_constant_ticks") is None:
            raise ValueError("an unassociated interval cannot enter an additive chain")
        if name in ADDITIVE_STAGES and not row["full_chain"]:
            raise ValueError("an incomplete sample cannot enter the additive stage subset")
        previous = end
        constant += row[name+"_constant_ticks"]
        coefficient += row[name+"_offset_coefficient"]
    return _bounds(constant, coefficient, row["offset_low_ticks"], row["offset_high_ticks"], row["frequency_hz"])


def _index(rows, source):
    output = {}
    for row in rows:
        key = row["policy"], row["sample"]
        if key in output:
            raise ValueError(f"duplicate {source} sample association")
        output[key] = row
    return output


def analyze(log):
    """Return every accepted sample and its conditional stage summary.

    Existing validators reject malformed, lost or incomplete captures. Missing
    or ambiguous scheduler association remains a row, with no fabricated edge.
    This function performs no writes and does not run the experiment controller.
    """
    stage_rows, stage_report = analyze_stages(log)
    runtime_rows, _, _, runtime_report = analyze_runtime(log)
    ready_rows, _, _ = analyze_ready(log)
    task_rows, _ = analyze_task(log)
    isr_rows, _, clocks = analyze_isr(log)
    indexes = [_index(rows, source) for rows, source in (
        (runtime_rows, "runtime"), (ready_rows, "Ready"), (task_rows, "task"), (isr_rows, "ISR"))]
    keys = set(_index(stage_rows, "physical stage"))
    if any(set(index) != keys for index in indexes):
        raise ValueError("stage/runtime/Ready/task/ISR sample cohorts differ")
    output = []
    for stage in stage_rows:
        key = stage["policy"], stage["sample"]
        runtime, ready, task, isr = (index[key] for index in indexes)
        clock = clocks[key[0]]
        row = dict(policy=key[0], sample=key[1], source=stage["source"],
                   status="associated", full_chain=False, runtime_status=runtime["status"],
                   ready_status=ready["status"], target_thread=runtime["target_thread"],
                   state_at_submit=runtime["state_at_submit"],
                   irq_requests=runtime["irq_requests"], worker_wakes=runtime["worker_wakes"],
                   running_edges=runtime["running_edges"], entry_boundaries=runtime["entry_boundaries"],
                   ready_candidates=ready["ready_candidates"],
                   wake_end_after_running=runtime["wake_end_after_running"],
                   irq_cpu=stage["irq_cpu"], intid=stage["intid"], irq_entry_context=stage["irq_entry_context"],
                   dispatch_end_vs_isr=stage["dispatch_end_vs_isr"],
                   ready_observer_cpu=ready["ready_observer_cpu"], running_cpu=ready["running_cpu"],
                   frequency_hz=clock["frequency_hz"], offset_low_ticks=clock["offset_low_ticks"],
                   offset_high_ticks=clock["offset_high_ticks"],
                   clock_calibration_width_ns=clock["offset_width_ns"],
                   trace_dropped=runtime_report["dropped"], trace_incomplete=runtime_report["incomplete"],
                   trace_loss=isr["trace_loss"], additive_stage_names="",
                   chain_algebra_residual_constant_ticks=None,
                   chain_algebra_residual_offset_coefficient=None,
                   chain_rounding_residual_lower_ns=None, chain_rounding_residual_upper_ns=None)
        points = {"t0": (stage["irq_entry_ticks"], 0), "irq_kick": (stage["irq_kick_ticks"], 0),
                  "dispatch_begin": (stage["dispatch_begin_ticks"], 0),
                  "dispatch_end": (stage["dispatch_end_ticks"], 0),
                  "timer_sync_begin": (stage["timer_sync_begin_ticks"], 0),
                  "timer_sync_end": (stage["timer_sync_end_ticks"], 0),
                  "wake_begin": (None, 0), "ready": (None, 0), "running": (None, 0),
                  "guest_entry_boundary": (None, 0),
                  "guest_isr_begin": (isr["guest_ticks"], 1), "guest_isr_end": (isr["guest_end_ticks"], 1),
                  "task_start": (task["task_start_ticks"], 1), "task_end": (task["task_end_ticks"], 1),
                  "host_isr_observed": (isr["observed_ticks"], 0),
                  "host_task_observed": (task["host_task_observed_ticks"], 0)}
        same_kick = (runtime["submit_to_irq_ticks"] != ""
                     and stage["submit_ticks"]+runtime["submit_to_irq_ticks"] == stage["irq_kick_ticks"])
        # A unique Host boundary remains observable even if another stage is
        # ambiguous. It does not make the sample a complete additive chain.
        if runtime["full_chain"] and same_kick:
            wake = stage["irq_kick_ticks"]+runtime["irq_to_worker_ticks"]
            running = wake+runtime["worker_to_running_ticks"]
            entry = running+runtime["running_to_entry_ticks"]
            if runtime["worker_wakes"] == 1:
                points["wake_begin"] = wake, 0
            if runtime["running_edges"] == 1:
                points["running"] = running, 0
            if runtime["entry_boundaries"] == 1:
                points["guest_entry_boundary"] = entry, 0
            if ready["complete"] and runtime["worker_wakes"] == runtime["running_edges"] == 1:
                points["ready"] = wake+ready["wake_to_ready_ticks"], 0
        if not runtime["full_chain"]:
            row["status"] = "runtime:"+runtime["status"]
        elif any(runtime[field] != 1 for field in ("irq_requests", "worker_wakes", "running_edges", "entry_boundaries")):
            row["status"] = "ambiguous_runtime_boundaries"
        elif not ready["complete"]:
            row["status"] = "ready:"+ready["status"]
        elif not same_kick:
            row["status"] = "runtime_physical_kick_mismatch"
        else:
            row.update(full_chain=True, additive_stage_names=",".join(ADDITIVE_STAGES))
        row.update({name+"_ticks": coordinate[0] for name, coordinate in points.items()})
        for name in ("ready", "running"):
            boundary = points[name][0]
            row["dispatch_end_vs_"+name] = (
                "missing" if boundary is None else
                "before" if stage["dispatch_end_ticks"] < boundary else
                "after" if stage["dispatch_end_ticks"] > boundary else "same_tick")
        low, high, hz = row["offset_low_ticks"], row["offset_high_ticks"], row["frequency_hz"]
        for name, (start, end, _) in METRICS.items():
            a, b = points[start], points[end]
            bounds = (dict.fromkeys(BOUND_FIELDS) if a[0] is None or b[0] is None
                      else _bounds(b[0]-a[0], b[1]-a[1], low, high, hz))
            _set_bounds(row, name, bounds)
        # These are the existing causal-window intersections, not affine terms.
        t0 = row["t0_ticks"]
        causal = {
            "t0_to_guest_isr_begin_causal": (max(t0, isr["guest_ticks"]+low)-t0,
                                                min(isr["observed_ticks"], isr["guest_ticks"]+high)-t0),
            "t0_to_task_end_causal": (max(task["submit_ticks"], task["task_end_ticks"]+low)-t0,
                                     min(task["host_task_observed_ticks"], task["task_end_ticks"]+high)-t0),
            "guest_isr_begin_to_host_observation_causal": (isr["observed_ticks"]-min(isr["observed_ticks"], isr["guest_ticks"]+high),
                                                          isr["observed_ticks"]-max(isr["submit_ticks"], isr["guest_ticks"]+low)),
            "task_end_to_host_observation_causal": (task["host_task_observed_ticks"]-min(task["host_task_observed_ticks"], task["task_end_ticks"]+high),
                                                    task["host_task_observed_ticks"]-max(task["submit_ticks"], task["task_end_ticks"]+low)),
        }
        for name, (lower, upper) in causal.items():
            row.update({name+"_lower_ticks": lower, name+"_upper_ticks": upper,
                        name+"_lower_ns": lower*1_000_000_000//hz,
                        name+"_upper_ns": -(-upper*1_000_000_000//hz)})
        if row["full_chain"]:
            total = correlated_sum(row, ADDITIVE_STAGES)
            endpoint = "t0_to_task_end_correlated"
            constant_residual = total["constant_ticks"]-row[endpoint+"_constant_ticks"]
            coefficient_residual = total["offset_coefficient"]-row[endpoint+"_offset_coefficient"]
            if constant_residual or coefficient_residual or any(row[m+"_lower_ticks"] < 0 for m in ADDITIVE_STAGES):
                raise ValueError("the unique chain does not telescope in the original tick domains")
            row.update(chain_algebra_residual_constant_ticks=constant_residual,
                       chain_algebra_residual_offset_coefficient=coefficient_residual,
                       chain_rounding_residual_lower_ns=sum(row[m+"_lower_ns"] for m in ADDITIVE_STAGES)-total["lower_ns"],
                       chain_rounding_residual_upper_ns=sum(row[m+"_upper_ns"] for m in ADDITIVE_STAGES)-total["upper_ns"])
        output.append(row)
    report = summarize(output)
    report.update(irq_stage_schema_version=stage_report["schema_version"],
                  runtime_records=runtime_report["records"], dropped=runtime_report["dropped"],
                  incomplete=runtime_report["incomplete"], clocks=clocks)
    return output, report


def _distribution(rows, metric):
    available = [row for row in rows if row[metric+"_lower_ns"] is not None]
    return dict(samples=len(available),
                lower=stats([row[metric+"_lower_ns"] for row in available]) if available else None,
                upper=stats([row[metric+"_upper_ns"] for row in available]) if available else None)


def summarize(rows):
    """Pool descriptive samples by policy; boot/condition annotations are allowed.

    This is not a boot-level inference or bootstrap. Every discrete stage uses
    the same strictly unique full-chain subset within its policy denominator.
    """
    rows = list(rows)
    if not rows:
        raise ValueError("cannot summarize an empty stage cohort")
    policies = {}
    for policy in dict.fromkeys(row["policy"] for row in rows):
        selected = [row for row in rows if row["policy"] == policy]
        complete = [row for row in selected if row["full_chain"]]
        policies[policy] = dict(
            samples=len(selected), full_chain_samples=len(complete),
            association_rate=len(complete)/len(selected), excluded_samples=len(selected)-len(complete),
            statuses=dict(Counter(row["status"] for row in selected)),
            ambiguous_samples=sum("ambiguous" in row["status"] for row in selected),
            missing_or_nonserial_samples=sum(not row["full_chain"] and "ambiguous" not in row["status"] for row in selected),
            irq_entry_contexts=dict(Counter(row["irq_entry_context"] for row in selected)),
            overlap_classifications={field: dict(Counter(row[field] for row in selected))
                                     for field in ("dispatch_end_vs_ready", "dispatch_end_vs_running", "dispatch_end_vs_isr")},
            conditional_distributions_ns={metric: _distribution(complete, metric) for metric in (*METRICS, *CAUSAL_METRICS)},
            all_sample_auxiliary_distributions_ns={metric: _distribution(selected, metric) for metric in AUXILIARY_METRICS},
            all_sample_observation_distributions_ns={metric: _distribution(selected, metric) for metric in CAUSAL_METRICS},
            calibration_width_ns=stats([row["clock_calibration_width_ns"] for row in selected]),
            rounding_residual_ns=(dict(lower=min(row["chain_rounding_residual_lower_ns"] for row in complete),
                                       upper=max(row["chain_rounding_residual_upper_ns"] for row in complete)) if complete else None))
    complete_count = sum(row["full_chain"] for row in rows)
    return dict(schema_version=1, units="nominal ns unless named ticks or Hz", samples=len(rows),
                full_chain_samples=complete_count, association_rate=complete_count/len(rows),
                excluded_samples=len(rows)-complete_count, invalid_logs=0,
                invalid_input_policy="Reject the entire malformed/lost/incomplete log before returning rows.",
                trace_loss_known=all(row["trace_loss"] is False for row in rows),
                additive_stages=list(ADDITIVE_STAGES),
                metric_contract={name: dict(start=a, end=b, group=group,
                                            additive_stage=name in ADDITIVE_STAGES)
                                 for name, (a, b, group) in METRICS.items()},
                causal_endpoints=list(CAUSAL_METRICS), policies=policies,
                relationship_definitions=dict(
                    dispatch_end_vs_isr="Host route end relative to Guest ISR begin, using the original causal-window bounds; certainly_before/certainly_after/within_clock_uncertainty.",
                    dispatch_end_vs_ready="Host route end relative to the unique Ready Host tick: before/after/same_tick; missing retains unassociated boundaries.",
                    dispatch_end_vs_running="Host route end relative to the unique Running Host tick: before/after/same_tick; missing retains unassociated boundaries."),
                statistics="Descriptive pooled samples; mean/P50 median/P99/P99.9 nearest-rank/max. No boot independence claim.",
                M1=False, M2=False,
                limitations=[
                    "The Host route and lower-EL timer spans can overlap remote execution and are never extra serial summands.",
                    "Current-EL timer spans remain null. GuestEntryBoundary is software, not hardware ERET; task end is not device output.",
                    "Raw correlated endpoints retain one shared policy offset; causal-window intersections are separate and cannot be summed.",
                    "Only unique Wake/Ready/Running/Entry associations enter the common stage subset; excluded samples remain in denominators.",
                    "Stage means can add only on identical rows; separately ranked percentiles are not additive.",
                    "Nanosecond endpoints round outward; exact tick algebra and its rounding residual are retained per sample.",
                    "Nominal counter scale, finite calibration and observed tails do not establish physical clock error bounds or WCET.",
                ])


def require_completed_plan(plan, state, finalizer):
    """Return the eight registered board-on runs only after both completion gates."""
    expected = plan["pilots"]+[run for block in plan["blocks"] for run in block["runs"]]
    completed = state.get("completed", [])
    identity_fields = ("name", "runtime", "mode", "block")
    identity = lambda run: tuple(run.get(field) for field in identity_fields)
    if (len(expected) != 18 or len(plan["pilots"]) != 2 or len(plan["blocks"]) != 8
            or not state.get("terminal") or not state.get("success")
            or [identity(run) for run in completed] != [identity(run) for run in expected]
            or len({run["name"] for run in expected}) != 18):
        raise ValueError("all 18 original registered runs must finish successfully before a formal baseline")
    if not finalizer.get("terminal") or not finalizer.get("success") or finalizer.get("phase") != "sealed":
        raise ValueError("the existing recorder-ops finalizer must have succeeded before a formal baseline")
    selected = [run for run in expected if run["runtime"] == "board" and run["mode"] == "on"]
    if len(selected) != 8 or {run["block"] for run in selected} != set(range(1, 9)):
        raise ValueError("the registered baseline needs one board-on run in each of eight blocks")
    return selected
