#!/usr/bin/env python3
"""Verify configured host service placement using completed task observations."""

import re


def records(log, prefix, expression):
    lines = [line.strip() for line in log.splitlines() if line.startswith(prefix)]
    parsed = [re.fullmatch(expression, line) for line in lines]
    if any(match is None for match in parsed):
        raise ValueError(f"malformed {prefix} record")
    return [match.groups() for match in parsed]


def analyze(log):
    modes = records(log, "VIRQ_SERVICE_PLACEMENT", r"VIRQ_SERVICE_PLACEMENT mode=(unrestricted|cpu0|cpu1|cpu2)")
    threads = records(log, "VIRQ_SERVICE_THREAD", r"VIRQ_SERVICE_THREAD role=(control|signal) thread=(\d+) requested_cpu=(\d+) observations=(\d+) wrong_cpu=(\d+)")
    summaries = records(log, "VIRQ_SERVICE_SUMMARY", r"VIRQ_SERVICE_SUMMARY role=(control|signal) requested_cpu=(\d+) started=(\d+) finished=(\d+) observations=(\d+) wrong_cpu=(\d+)")
    # Logs predating this optional fixture retain their original interpretation.
    if not modes:
        if threads or summaries:
            raise ValueError("service observations have no placement configuration")
        return dict(mode="unrecorded", verified=False)
    if len(modes) != 1:
        raise ValueError("duplicated service placement configuration")
    mode = modes[0][0]
    if mode == "unrestricted":
        if threads or summaries:
            raise ValueError("unrestricted service fixture has controlled observations")
        return dict(mode=mode, verified=False)
    if len(summaries) != 2 or {row[0] for row in summaries} != {"control", "signal"}:
        raise ValueError("missing or duplicated service role summary")
    if len({row[1] for row in threads}) != len(threads):
        raise ValueError("service thread identity reused")
    expected_cpu = int(mode[-1])
    report = {}
    for role, *raw in summaries:
        cpu, started, finished, observations, wrong = map(int, raw)
        selected = [tuple(map(int, row[1:])) for row in threads if row[0] == role]
        if not selected or any(t == 0 or c != expected_cpu or n < 2 or w != 0 for t, c, n, w in selected):
            raise ValueError("service thread placement observations failed")
        if (cpu, started, finished, observations, wrong) != (expected_cpu, len(selected), len(selected), sum(row[2] for row in selected), 0):
            raise ValueError("service role lifetime or observation aggregate mismatch")
        report[role] = dict(cpu=cpu, threads=len(selected), observations=observations, wrong_cpu=0)
    return dict(mode=mode, verified=True, roles=report,
                limitation="Discrete task observations supplement builder affinity; other host activity remains uncontrolled.")
