"""Validate correlated software IRQ intervals without inventing legacy observations."""

import re

STAGE_KINDS = frozenset(("IrqDispatchBegin", "IrqDispatchEnd", "TimerSyncBegin", "TimerSyncEnd"))
CONFIG = re.compile(r"VIRQ_STAGE_CONFIG version=1 key=cpu_intid_entry_ticks dispatch=host_route timer_sync=lower_el_only")


def validate_stages(log, events):
    declarations = [line for line in log.splitlines() if "VIRQ_STAGE_CONFIG" in line]
    stages = [e for e in events if e["kind"] in STAGE_KINDS]
    if not declarations:
        if stages:
            raise ValueError("IRQ stages have no schema declaration")
        return dict(version=None, entries=[], observations_available=False)
    if len(declarations) != 1:
        raise ValueError("duplicated IRQ stage schema")
    match = CONFIG.search(declarations[0])
    if match is None or declarations[0][match.end():].strip():
        raise ValueError("unsupported IRQ stage schema")
    entries = {}
    for entry in (e for e in events if e["kind"] == "HostIrqEntry"):
        key = entry["cpu"], entry["value0"], entry["ticks"]
        if (key in entries or entry["thread"] != 0 or entry["value1"] not in (1, 2)
                or not 16 <= entry["value0"] < 1020 or entry["ticks"] == 0):
            raise ValueError("invalid or duplicate IRQ stage origin")
        entries[key] = (entry, {})
    for stage in stages:
        key = stage["cpu"], stage["value0"], stage["value1"]
        if key not in entries or stage["thread"] != 0:
            raise ValueError("IRQ stage has no matching CPU/INTID/entry timestamp")
        entry, group = entries[key]
        if stage["kind"] in group:
            raise ValueError("duplicate IRQ stage")
        if (stage["ticks"], stage["sequence"]) < (entry["ticks"], entry["sequence"]):
            raise ValueError("IRQ stage precedes its origin")
        group[stage["kind"]] = stage
    rows = []
    for (cpu, intid, ticks), (entry, group) in entries.items():
        order = (["TimerSyncBegin", "TimerSyncEnd"] if entry["value1"] == 2 else [])
        order += ["IrqDispatchBegin", "IrqDispatchEnd"]
        if set(group) != set(order):
            raise ValueError("IRQ stage interval missing or incompatible with entry context")
        positions = [(group[k]["ticks"], group[k]["sequence"]) for k in order]
        if positions != sorted(positions) or len(set(positions)) != len(positions):
            raise ValueError("IRQ stages are reversed or reuse one record")
        rows.append(dict(cpu=cpu, intid=intid, entry_ticks=ticks,
                         entry_context=entry["value1"],
                         dispatch_begin_ticks=group["IrqDispatchBegin"]["ticks"],
                         dispatch_end_ticks=group["IrqDispatchEnd"]["ticks"],
                         timer_sync_begin_ticks=group["TimerSyncBegin"]["ticks"] if entry["value1"] == 2 else None,
                         timer_sync_end_ticks=group["TimerSyncEnd"]["ticks"] if entry["value1"] == 2 else None))
    return dict(version=1, entries=rows, observations_available=bool(rows))
