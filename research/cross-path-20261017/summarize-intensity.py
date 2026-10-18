#!/usr/bin/env python3
"""Summarize only the fully accepted, frozen 96-boot intensity cohort."""
import csv
import hashlib
import json
import math
from numbers import Real
import os
from pathlib import Path
import statistics
import tempfile

from factorial_statistics import CONDITIONS, summarize_blocks

STRATA = ('reference', 'irq2x', 'memory_sparse')
POLICIES = ('fair', 'fifo80')
METRICS = ('release_to_completion', 'irq_entry_to_completion')
RUN_FIELDS = ('block', 'stratum', 'position', 'macro_position', 'condition', 'name')
TABLES = ('intensity-v3-run-means.csv', 'intensity-v3-task-endpoints.csv',
          'intensity-v3-environment.csv')
FIGURES = ('intensity-v3-interactions', 'intensity-v3-paired-changes',
           'intensity-v3-ecdf', 'intensity-v3-throughput')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def descriptive(values):
    ordered = sorted(values)
    if not ordered or any(not math.isfinite(v) for v in ordered):
        raise ValueError('nonempty finite observations required')
    return dict(mean=statistics.mean(ordered), p50=statistics.median(ordered),
                p99=ordered[math.ceil(.99*len(ordered))-1],
                p999=ordered[math.ceil(.999*len(ordered))-1], maximum_observed=ordered[-1])


def _candidate(effect):
    """Apply the same strict stability rule to positive and negative candidates."""
    halves = [effect['first_half_mean_bounds_ns'], effect['second_half_mean_bounds_ns']]
    checks = halves+effect['leave_one_block_out_mean_bounds_ns']
    if (effect['bootstrap_95_bounds_ns'][0] > 0 and effect['positive_block_bounds'] >= 7
            and all(bounds[0] > 0 for bounds in checks)):
        return 'positive'
    if (effect['bootstrap_95_bounds_ns'][1] < 0 and effect['negative_block_bounds'] >= 7
            and all(bounds[1] < 0 for bounds in checks)):
        return 'negative'
    return None


def summarize_records(run_rows, *, resamples=10000):
    """Return stratified effects and macroblock-paired changes from run means.

    Each of 96 registered boots contributes two policy rows with RUN_FIELDS,
    tasks=32 and both metric lower/upper bounds. Row ordering is immaterial;
    block IDs define pairing and the chronological first/second halves.
    This pure algorithm does not accept or certify hardware evidence.
    """
    from intensity_sensitivity import paired_difference
    rows = list(run_rows)
    if len(rows) != 192:
        raise ValueError('96 complete boots with two policy rows required')
    indexed, boots, names = {}, {}, {}
    for row in rows:
        try:
            block, stratum, condition, policy = (row[k] for k in ('block', 'stratum', 'condition', 'policy'))
            position, macro = row['position'], row['macro_position']
            if (type(block) is not int or block not in range(1, 9)
                    or type(position) is not int or position not in range(1, 5)
                    or type(macro) is not int or macro not in range(1, 13)
                    or stratum not in STRATA or condition not in CONDITIONS or policy not in POLICIES
                    or row['tasks'] != 32 or type(row['tasks']) is not int
                    or not isinstance(row['name'], str) or not row['name']
                    or (macro-1) % 4+1 != position):
                raise ValueError('invalid complete-block run identity')
            key = block, stratum, condition, policy
            if key in indexed:
                raise ValueError('duplicate condition/policy in a complete block')
            indexed[key] = row
            boot = block, stratum, condition
            identity = tuple(row[k] for k in RUN_FIELDS)
            if boot in boots and boots[boot] != identity:
                raise ValueError('the two policies must belong to the same registered boot')
            boots[boot] = identity
            if row['name'] in names and names[row['name']] != boot:
                raise ValueError('boot names must be unique')
            names[row['name']] = boot
            for metric in METRICS:
                lo, hi = (row[metric+suffix] for suffix in ('_lower_ns', '_upper_ns'))
                if (any(isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v)
                        or v < 0 for v in (lo, hi)) or lo > hi):
                    raise ValueError('finite nonnegative ordered run-mean endpoints required')
        except (KeyError, TypeError) as error:
            raise ValueError('missing or malformed complete-block row') from error
    for block in range(1, 9):
        chosen = [r for r in rows if r['block'] == block and r['policy'] == POLICIES[0]]
        if len(chosen) != 12 or {r['macro_position'] for r in chosen} != set(range(1, 13)):
            raise ValueError('each macroblock must have twelve unique boot positions')
        for stratum in STRATA:
            group = [r for r in chosen if r['stratum'] == stratum]
            if (len(group) != 4 or {r['condition'] for r in group} != set(CONDITIONS)
                    or {r['position'] for r in group} != set(range(1, 5))
                    or len({(r['macro_position']-1)//4 for r in group}) != 1):
                raise ValueError('each stratum needs one contiguous complete four-condition subblock')
    effects = {s: {p: {} for p in POLICIES} for s in STRATA}
    paired = {s: {p: {} for p in POLICIES} for s in STRATA[1:]}
    for stratum in STRATA:
        for policy in POLICIES:
            for metric in METRICS:
                blocks = [dict(block=b, conditions={c: [indexed[b, stratum, c, policy][metric+s]
                                  for s in ('_lower_ns', '_upper_ns')] for c in CONDITIONS})
                          for b in range(1, 9)]
                effect = summarize_blocks(blocks, seed=20261029, resamples=resamples)
                effect['candidate_stable_sign'] = _candidate(effect)
                effect['candidate_rule'] = ('Strict empirical interval sign, >=7/8 strict same-sign blocks, '
                    'same-sign first/second half and every leave-one-block-out mean envelope; candidate only.')
                effects[stratum][policy][metric] = effect
                if stratum != 'reference':
                    paired[stratum][policy][metric] = paired_difference(
                        effects['reference'][policy][metric]['block_interactions'],
                        effect['block_interactions'], seed=20261030, resamples=resamples)
    return dict(effects=effects, paired_changes=paired)


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def _sample_keys(rows):
    keys = [(r['policy'], int(r['sample'])) for r in rows]
    expected = {(p, i) for p in POLICIES for i in range(1, 33)}
    if len(keys) != 64 or len(set(keys)) != 64 or set(keys) != expected:
        raise ValueError('every boot must retain all 64 unique policy/sample endpoints')
    return set(keys)


def collect_records(archive, plan, state, expected, verifier):
    """Read verified native bytes; retain endpoint and stage denominators separately."""
    run_rows, events, environment, stages, sources = [], [], [], [], {}
    fit_identities, firmware_identity = {}, None
    for run, accepted in zip(expected, state['completed']):
        verifier(plan, run, accepted)
        fit_key = run['stratum'], run['condition']
        content = accepted['host_fit_content_sha256']
        if fit_identities.setdefault(fit_key, content) != content:
            raise ValueError('actual Host FIT content changed within a stratum/condition')
        firmware = accepted['firmware']
        if not firmware['uboot_build_banners'] or not firmware['bl31_build_banners']:
            raise ValueError('both observed firmware build banners are required')
        if firmware_identity is None:
            firmware_identity = firmware
        if firmware_identity != firmware:
            raise ValueError('actual observed firmware changed within the native cohort')
        name = run['name']
        output = archive/'results'/name
        paths = [output/p for p in ('task/summary.json', 'task/samples.csv', 'load/summary.json',
                 'runtime/summary.json', 'stage_baseline/samples.json',
                 'thermal/samples.csv', 'frequency/samples.csv')]
        sources[name] = {str(path.relative_to(archive)): digest(path) for path in paths}
        task, load, runtime = (read(output/p) for p in
                              ('task/summary.json', 'load/summary.json', 'runtime/summary.json'))
        samples = _read_csv(output/'task/samples.csv')
        keys = _sample_keys(samples)
        if any(r['trace_loss'] != 'False' for r in samples) or runtime['dropped'] or runtime['incomplete']:
            raise ValueError('lossy or incomplete task/runtime observations')
        run_identity = {key: run[key] for key in RUN_FIELDS}
        evidence = dict(raw_sha256=accepted['raw_sha256'],
                        analysis_input_sha256=accepted['analysis_input_sha256'],
                        task_csv_sha256=sources[name][str((output/'task/samples.csv').relative_to(archive))])
        normalized = []
        for sample in samples:
            event = dict(**run_identity, **evidence, policy=sample['policy'], sample=int(sample['sample']),
                         task_deadline_miss=sample['task_deadline_miss'])
            if event['task_deadline_miss'] not in ('true', 'false', 'unknown'):
                raise ValueError('invalid clock-bounded deadline classification')
            for metric in METRICS:
                lo, hi = [float(sample[metric+s]) for s in ('_lower_ns', '_upper_ns')]
                if not 0 <= lo <= hi or not math.isfinite(hi):
                    raise ValueError('invalid task endpoint bounds')
                event.update({metric+'_lower_ns': lo, metric+'_upper_ns': hi})
            events.append(event)
            normalized.append(event)
        for policy in POLICIES:
            selected = [r for r in normalized if r['policy'] == policy]
            stat = task['policies'][policy]
            if stat['samples'] != 32:
                raise ValueError('task summary must describe all 32 tasks per policy')
            means = {metric+s: statistics.mean(r[metric+s] for r in selected)
                     for metric in METRICS for s in ('_lower_ns', '_upper_ns')}
            if any(not math.isclose(v, stat[k]['mean'], rel_tol=1e-12, abs_tol=1e-6)
                   for k, v in means.items()):
                raise ValueError('task summary and complete endpoint means disagree')
            throughput = load['loads'][policy]['fenced_throughput']
            row = dict(**run_identity, **evidence, policy=policy, tasks=32, **means,
                       linux_workload=load['scenario'], trace_records=runtime['records'],
                       trace_dropped=runtime['dropped'], trace_incomplete=runtime['incomplete'],
                       deadline_miss_true=sum(r['task_deadline_miss'] == 'true' for r in selected),
                       deadline_miss_unknown=sum(r['task_deadline_miss'] == 'unknown' for r in selected))
            for field in ('task_execution_ns', 'isr_end_to_task_start_ns', 'release_lateness_ns'):
                row[field+'_mean'] = stat[field]['mean']
            # Preserve the complete whole-fence interval, including causal bounds and logical bytes.
            row.update({'linux_'+key: value for key, value in throughput.items()
                        if isinstance(value, (str, int, float, bool)) or value is None})
            run_rows.append(row)
        for kind in ('thermal', 'frequency'):
            observed = _read_csv(output/kind/'samples.csv')
            if not observed:
                raise ValueError('frequency/thermal snapshot evidence must be present')
            environment.extend(dict(r, **run_identity, observation=kind,
                source_csv_sha256=sources[name][str((output/kind/'samples.csv').relative_to(archive))])
                for r in observed)
        environment.append(dict(**run_identity, observation='firmware_build_text',
            uboot_build_banners=' | '.join(firmware['uboot_build_banners']),
            bl31_build_banners=' | '.join(firmware['bl31_build_banners']),
            exact_firmware_binary_identity_verified=False))
        stage_rows = read(output/'stage_baseline/samples.json')
        if (_sample_keys(stage_rows) != keys or any(r['trace_loss'] is not False for r in stage_rows)):
            raise ValueError('stage denominator must retain every endpoint sample')
        stages.extend(dict(r, **run_identity) for r in stage_rows)
    if len(events) != 6144:
        raise ValueError('the native cohort must contain 6144 task endpoints')
    return run_rows, events, environment, stages, sources


def condition_distributions(run_rows, events, stages):
    from stage_baseline import summarize as summarize_stages
    conditions, stage_conditions = {}, {}
    for stratum in STRATA:
        conditions[stratum], stage_conditions[stratum] = {}, {}
        for policy in POLICIES:
            conditions[stratum][policy] = {}
            for condition in CONDITIONS:
                selected = [r for r in events if (r['stratum'], r['policy'], r['condition']) ==
                            (stratum, policy, condition)]
                runs = [r for r in run_rows if (r['stratum'], r['policy'], r['condition']) ==
                        (stratum, policy, condition)]
                n = len(selected)
                summary = dict(independent_boots=len(runs), tasks=n,
                    deadline_miss_ratio_clock_bounds=[sum(r['task_deadline_miss'] == 'true' for r in selected)/n,
                        sum(r['task_deadline_miss'] != 'false' for r in selected)/n],
                    p999_is_maximum_order_statistic=math.ceil(.999*n) == n,
                    linux_workload=runs[0]['linux_workload'])
                summary.update({metric: {side: descriptive([r[metric+'_'+side] for r in selected])
                    for side in ('lower_ns', 'upper_ns')} for metric in METRICS})
                for field in ('iterations_per_second', 'iterations_per_second_causal_lower',
                              'iterations_per_second_causal_upper', 'logical_read_bytes_per_second',
                              'logical_write_bytes_per_second'):
                    values = [r.get('linux_'+field) for r in runs]
                    summary['linux_'+field+'_run_distribution'] = (descriptive(values)
                        if all(v is not None for v in values) else None)
                conditions[stratum][policy][condition] = summary
        for condition in CONDITIONS:
            stage_conditions[stratum][condition] = summarize_stages([r for r in stages
                if r['stratum'] == stratum and r['condition'] == condition])
    return conditions, stage_conditions


def make_figures(destination, report):
    """Plot from the actual CSV bytes whose SHA is included in every figure."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    runs = _read_csv(destination/TABLES[0])
    events = _read_csv(destination/TABLES[1])
    source_hashes = report['derived_tables_sha256']
    if any(digest(destination/name) != sha for name, sha in source_hashes.items()):
        raise ValueError('plot source CSV bytes changed')
    # Recompute effects from serialized run means, binding plots to published CSVs.
    numeric = []
    for raw in runs:
        row = dict(raw)
        for key in ('block', 'position', 'macro_position', 'tasks'):
            row[key] = int(row[key])
        for metric in METRICS:
            for suffix in ('_lower_ns', '_upper_ns'):
                row[metric+suffix] = float(row[metric+suffix])
        numeric.append(row)
    plotted = summarize_records(numeric)
    if plotted != {key: report[key] for key in ('effects', 'paired_changes')}:
        raise ValueError('serialized run means and report inference disagree')
    figures = {}
    (destination/'figures').mkdir()

    def save(fig, stem, tables):
        binding = {name: source_hashes[name] for name in tables}
        description = json.dumps(binding, sort_keys=True)
        fig.suptitle(report['scope'], fontsize=10)
        fig.text(.01, .005, 'Source CSV SHA256: '+', '.join(sha[:12] for sha in binding.values()), fontsize=6)
        for extension in ('png', 'pdf'):
            path = destination/'figures'/(stem+'.'+extension)
            metadata = {'Description': description} if extension == 'png' else {'Subject': description}
            with path.open('xb') as stream:
                fig.savefig(stream, format=extension, dpi=180, bbox_inches='tight', metadata=metadata)
            figures[str(path.relative_to(destination))] = dict(sha256=digest(path), source_tables_sha256=binding)
        plt.close(fig)

    def intervals(ax, labels, groups, key, title):
        for index, group in enumerate(groups):
            lo, hi = group[key]
            ax.plot([lo/1000, hi/1000], [index, index], linewidth=3)
            ax.plot([(lo+hi)/2000], [index], 'o', markersize=3)
        ax.set_yticks(range(len(labels)), labels)
        ax.axvline(0, color='black', linewidth=.6)
        ax.set_xlabel('Empirical 95% envelope (us)')
        ax.set_title(title)
        ax.grid(axis='x', alpha=.2)

    fig, axes = plt.subplots(2, 2, figsize=(12, 7), constrained_layout=True)
    for i, policy in enumerate(POLICIES):
        for j, metric in enumerate(METRICS):
            intervals(axes[i, j], STRATA, [plotted['effects'][s][policy][metric] for s in STRATA],
                      'bootstrap_95_bounds_ns', policy+' / '+metric)
    save(fig, FIGURES[0], [TABLES[0]])
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), constrained_layout=True)
    for i, policy in enumerate(POLICIES):
        for j, metric in enumerate(METRICS):
            intervals(axes[i, j], [s+' - reference' for s in STRATA[1:]],
                [plotted['paired_changes'][s][policy][metric] for s in STRATA[1:]],
                'bootstrap_95_bounds_ns', policy+' / '+metric)
    save(fig, FIGURES[1], [TABLES[0]])
    fig, axes = plt.subplots(3, 4, figsize=(17, 10), constrained_layout=True)
    colors = dict(zip(CONDITIONS, ('#0072B2', '#E69F00', '#009E73', '#CC79A7')))
    for i, stratum in enumerate(STRATA):
        for j, (policy, metric) in enumerate((p, m) for p in POLICIES for m in METRICS):
            ax = axes[i, j]
            for condition in CONDITIONS:
                selected = [r for r in events if (r['stratum'], r['policy'], r['condition']) ==
                            (stratum, policy, condition)]
                for side, style in (('lower_ns', '--'), ('upper_ns', '-')):
                    values = sorted(float(r[metric+'_'+side])/1000 for r in selected)
                    ax.step(values, [(k+1)/len(values) for k in range(len(values))], where='post',
                            color=colors[condition], linestyle=style,
                            label=condition if side == 'upper_ns' else None, linewidth=.8)
            ax.set_title(stratum+' / '+policy+'\n'+metric, fontsize=9)
            ax.set_xlabel('Latency bounds (us)')
            ax.set_ylabel('Pooled task ECDF')
            ax.legend(fontsize=7)
    save(fig, FIGURES[2], [TABLES[1]])
    fig, axes = plt.subplots(3, 2, figsize=(12, 10), constrained_layout=True)
    for i, stratum in enumerate(STRATA):
        for j, policy in enumerate(POLICIES):
            ax = axes[i, j]
            for k, condition in enumerate(CONDITIONS):
                selected = [r for r in runs if (r['stratum'], r['policy'], r['condition']) ==
                            (stratum, policy, condition)]
                rate = statistics.mean(float(r['linux_iterations_per_second']) for r in selected)
                lower, upper = [statistics.mean(float(r['linux_iterations_per_second_causal_'+s])
                                for r in selected) for s in ('lower', 'upper')]
                ax.errorbar(k, rate/1e6, yerr=[[max(0, rate-lower)/1e6], [max(0, upper-rate)/1e6]],
                            fmt='o', color=colors[condition], capsize=3)
                logical = [r.get('linux_logical_read_bytes_per_second') for r in selected]
                if all(v not in (None, '') for v in logical):
                    text = f'{statistics.mean(float(v) for v in logical)/1e6:.1f} MB/s logical read'
                    ax.annotate(text, (k, rate/1e6), xytext=(0, 9), textcoords='offset points',
                                ha='center', fontsize=6)
            ax.set_xticks(range(4), ['0\nCPU', 'A\nCPU', 'B\nMemory', 'AB\nMemory'])
            ax.set_ylabel('Whole-fence million iterations/s')
            ax.set_title(stratum+' / '+policy)
            ax.grid(axis='y', alpha=.2)
    save(fig, FIGURES[3], [TABLES[0]])
    return figures


def _bounds(bounds):
    return f'{bounds[0]/1000:.3f}～{bounds[1]/1000:.3f}'


def render_report(report):
    lines = ['# 强度敏感性真板报告', '', '## 1. 范围与证据', '',
        '本报告由同一 v3 RK3588 测量版本的 96 次已验收真实启动生成：八个宏块，每宏块随机交错三个强度层，每层各有完整 0/A/B/AB 子块。每启动 Fair/FIFO 各 32 条任务，共 6144 条；策略使用固定顺序，分别分析，不构成策略随机实验。', '',
        '### 1.1 强度与边界', '',
        'reference：A 为 2000 µs 周期、burst=2，B 为 16 MiB 每批访问；irq2x 仅将 A 周期改为 1000 µs；memory_sparse 仅将 B 改为每八批访问。当前是强度敏感性实验，没有宣称控制 B 的相位。0/A 是 Linux CPU 工作量，B/AB 是 Linux 内存工作量；CPU 工作负载也访问内存。', '',
        '### 1.2 完整性与身份', '',
        '全部注册启动必须成功终态、顺序唯一、每启动 64 条任务，且逐次复核 raw/derived、源包、冻结参考输入、实际压力与驻留和实际 Host FIT。runtime dropped/incomplete 必须为零。完整端点保留；多次 Entry 或阶段关联失败只影响阶段子集，不能筛掉任务端点。计划、状态、输入来源和输出 CSV 的 SHA256 见 JSON；图的元数据绑定实际 CSV SHA256。', '',
        f'既有 M1 验收依据仅引用冻结计划：`{json.dumps(report["existing_acceptance"], ensure_ascii=False, sort_keys=True)}`。本轮不据此宣布阶段 0～2 或整体目标完成，M2 保持 false。', '',
        '## 2. 运行均值交互', '',
        '每层/策略/端点以八个完整子块计算 IAB=AB−A−B+0，时钟端点按符号向外传播。固定 seed=20261029，10000 次共同抽取完整块索引。相对 reference 的变化按同一宏块交互配对相减，seed=20261030；不把三个强度层混为独立重复。', '',
        '### 2.1 分层结果', '',
        '| 强度层 | 策略 | 端点 | 均值界 µs | 经验95%包围 µs | 正/负块 | 稳定候选 |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    for stratum in STRATA:
        for policy in POLICIES:
            for metric in METRICS:
                effect = report['effects'][stratum][policy][metric]
                sign = {'positive': '正', 'negative': '负', None: '无'}[effect['candidate_stable_sign']]
                lines.append(f'| {stratum} | {policy} | {metric} | {_bounds(effect["interaction_mean_bounds_ns"])} | '
                    f'{_bounds(effect["bootstrap_95_bounds_ns"])} | {effect["positive_block_bounds"]}/{effect["negative_block_bounds"]} | {sign} |')
    lines += ['', '### 2.2 配对变化', '',
        '| 相对 reference | 策略 | 端点 | 配对均值界 µs | 经验95%包围 µs |',
        '| --- | --- | --- | --- | --- |']
    for stratum in STRATA[1:]:
        for policy in POLICIES:
            for metric in METRICS:
                effect = report['paired_changes'][stratum][policy][metric]
                lines.append(f'| {stratum} | {policy} | {metric} | {_bounds(effect["mean_bounds_ns"])} | '
                             f'{_bounds(effect["bootstrap_95_bounds_ns"])} |')
    lines += ['', '### 2.3 候选规则与推断限制', '',
        '正负使用同一规则：经验区间严格不跨零，至少 7/8 块严格同号，前半、后半及全部 leave-one-out 均值界同号。满足时也只是候选，仍须阶段 3 机制干预，不自动成为 M2。八块的小样本经验包围没有覆盖保证；多个逐点区间没有全族覆盖保证。未达规则不能证明所有条件下没有交互。', '',
        '![Stratified interactions](figures/intensity-v3-interactions.png)', '',
        '上图分别展示三个强度层的交互经验包围；下图以同一宏块配对，展示改变强度后相对 reference 的交互变化。', '',
        '![Paired changes](figures/intensity-v3-paired-changes.png)', '',
        '## 3. 条件分布与吞吐', '',
        '任务端点分布描述关键任务的观察时延，Linux 围栏吞吐描述同窗口的普通虚拟机进展；两类结果分别保留各自分母和时钟边界。', '',
        '### 3.1 全部任务端点', '',
        '每层/策略/条件为八次启动、256 条任务。下表分别列各端点时钟界；P99.9 在 n=256 时等于观察最大值。分位数不进入加性交互，分位数非加性本身不构成耦合证据；最大观测值不是 WCET/WCRT，DMR 观察界不是未来保证。', '',
        '| 强度层/策略/条件 | 端点 | 均值 µs | P50 µs | P99 µs | P99.9/最大 µs | DMR 时钟界 |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    for stratum in STRATA:
        for policy in POLICIES:
            for condition in CONDITIONS:
                group = report['conditions'][stratum][policy][condition]
                for metric in METRICS:
                    lo, hi = (group[metric][side] for side in ('lower_ns', 'upper_ns'))
                    values = [_bounds([lo[k], hi[k]]) for k in ('mean', 'p50', 'p99', 'p999')]
                    lines.append(f'| {stratum}/{policy}/{condition} | {metric} | '+
                                 ' | '.join(values)+f' | {group["deadline_miss_ratio_clock_bounds"]} |')
    lines += ['', '![Task endpoint ECDFs](figures/intensity-v3-ecdf.png)', '',
        '### 3.2 Linux 围栏吞吐', '',
        'whole-fence 的 Linux 时钟迭代率、Host 因果界、围栏起止批次/时间、逻辑读写字节及速率完整保存在逐启动 CSV。下表对八次启动的速率取均值；CPU 与内存工作量不同，不能把其吞吐比称为优化代价。logical bytes 包含可缓存访问，不是 DRAM 总线带宽或 PMU 测量。', '',
        '| 强度层/策略/条件 | 迭代率均值 iterations/s | Host 因果均值界 iterations/s | 逻辑读/写 MB/s |',
        '| --- | --- | --- | --- |']
    for stratum in STRATA:
        for policy in POLICIES:
            for condition in CONDITIONS:
                group = report['conditions'][stratum][policy][condition]
                rate = group['linux_iterations_per_second_run_distribution']['mean']
                lower, upper = [group['linux_iterations_per_second_causal_'+s+'_run_distribution']['mean']
                                for s in ('lower', 'upper')]
                logical = [group['linux_logical_'+s+'_bytes_per_second_run_distribution'] for s in ('read', 'write')]
                text = '/'.join(f'{v["mean"]/1e6:.3f}' if v is not None else '不适用' for v in logical)
                lines.append(f'| {stratum}/{policy}/{condition} | {rate:.3f} | {lower:.3f}～{upper:.3f} | {text} |')
    lines += ['', '![Whole-fence throughput](figures/intensity-v3-throughput.png)', '',
        '## 4. 阶段关联与剩余边界', '',
        '阶段关联用于说明哪些样本能够组成唯一的串行链，并保留未能关联的分母；测量与环境边界限定这些结果能够支持的结论。', '',
        '### 4.1 阶段分母', '',
        '阶段通过既有 stage_baseline.summarize 汇总，各层/条件并保留按策略分母、完整链数、排除数与状态；端点 ECDF 始终使用全部样本。Host route 可能与远端执行重叠，不能再加到串行链；只能在相同关联样本上解释阶段均值之和。', '',
        '| 强度层/条件 | 全部端点分母 | 唯一完整链 | 阶段关联率 |', '| --- | --- | --- | --- |']
    for stratum in STRATA:
        for condition in CONDITIONS:
            stage = report['stages_by_condition'][stratum][condition]
            lines.append(f'| {stratum}/{condition} | {stage["samples"]} | {stage["full_chain_samples"]} | {stage["association_rate"]:.3f} |')
    lines += ['', '### 4.2 测量边界', '',
        'T0 是 Hypervisor 软件观察点，不是硬件引脚时刻；T4 为后端调用前的软件边界，不是硬件 ERET；T6 是 Guest 任务结束，不是设备输出。名义计数频率和有限校时不能认证物理时钟误差。既有记录器校准不覆盖全部交互残余扰动，不能把残余成本当作已知可减常量。', '',
        '频率/温度 CSV 是实际窗口前后快照，不能认证固定 OPP 或整个窗口连续环境。U-Boot/BL31 构建文本按可见性归档，缺失仍缺失，文本不认证固件二进制身份。所有表图仅描述冻结测量版本、指定平台与强度；后续阶段 3 才检验机制，之后才能讨论联合控制及收益。', '']
    return '\n'.join(lines)


def main():
    import intensity_sensitivity as intensity
    archive = intensity.ARCHIVE
    plan = intensity.read_plan()
    plan_sha = digest(archive/intensity.PLAN_FILE)
    state_sha = digest(archive/intensity.STATUS_FILE)
    state = read(archive/intensity.STATUS_FILE)
    expected = intensity.validate_completed(plan, state, plan_sha)
    intensity.check_inputs(plan, full_seals=True)
    if len(expected) != 96:
        raise ValueError('exactly the registered 96 native boots are required')
    runs, events, environment, stages, sources = collect_records(
        archive, plan, state, expected, intensity.verify_run)
    intensity.check_inputs(plan)
    if digest(archive/intensity.PLAN_FILE) != plan_sha or digest(archive/intensity.STATUS_FILE) != state_sha:
        raise ValueError('registered plan or successful terminal state changed during verification')
    inference = summarize_records(runs)
    conditions, stage_conditions = condition_distributions(runs, events, stages)
    report = dict(schema_version=1, scope='same-v3-RK3588 intensity sensitivity; not phase completion',
        native_boots=96, macroblocks=8, complete_blocks_per_stratum=8,
        task_observations=len(events), plan_sha256=plan_sha,
        status_sha256=state_sha, summary_script_sha256=digest(Path(__file__)),
        acceptance_script_sha256=digest(Path(intensity.__file__)),
        source_files_sha256=sources, accepted_runs=state['completed'],
        existing_acceptance={key: value for key, value in plan.items()
                             if 'acceptance' in key.lower() or 'm1' in key.lower()},
        conditions=conditions, stages_by_condition=stage_conditions,
        firmware_observation_coverage={key: sum(bool(r['firmware'][key]) for r in state['completed'])
            for key in ('uboot_build_banners', 'bl31_build_banners')},
        trace_loss_records=0, M2=False, phase0_to_2_complete=False,
        inference_scope='Candidate interactions only; phase 3 mechanism evidence remains required.',
        bootstrap_resamples=10000, bootstrap_seed=20261029, paired_bootstrap_seed=20261030,
        **inference)
    results = archive/'results'
    outputs = [*TABLES, 'intensity-v3-summary.json', 'intensity-v3-report.md']
    outputs += ['figures/'+stem+'.'+ext for stem in FIGURES for ext in ('png', 'pdf')]
    if any((results/name).exists() for name in outputs):
        raise ValueError('intensity output already exists; sealed or prior artifacts are never overwritten')
    # Publish only complete artifacts, using exclusive hard links on the same filesystem.
    with tempfile.TemporaryDirectory(prefix='.intensity-v3-', dir=results) as temporary:
        staged = Path(temporary)
        for filename, rows in zip(TABLES, (runs, events, environment)):
            write_csv(staged/filename, rows)
        report['derived_tables_sha256'] = {name: digest(staged/name) for name in TABLES}
        report['figures'] = make_figures(staged, report)
        (staged/'intensity-v3-summary.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        (staged/'intensity-v3-report.md').write_text(render_report(report))
        if (digest(archive/intensity.PLAN_FILE) != plan_sha
                or digest(archive/intensity.STATUS_FILE) != state_sha
                or any(digest(archive/path) != sha for run in sources.values() for path, sha in run.items())):
            raise ValueError('accepted plan, terminal state or derived plot sources changed before publication')
        (results/'figures').mkdir(exist_ok=True)
        for name in outputs:
            os.link(staged/name, results/name)
    print('INTENSITY_SUMMARY_OK macroblocks=8 strata=3 native_boots=96 tasks=6144 M2=0')


if __name__ == '__main__':
    main()
