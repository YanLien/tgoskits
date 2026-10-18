#!/usr/bin/env python3
"""Read-only, source-bound diagnosis of two saved suite error candidates."""
import ast
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
TOOLS = Path('/tmp/crosspath-native-cache-v3-tools-jrhcn15t')


def bound(path, expected):
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    assert checksum == expected, (str(path), checksum, expected)
    return raw, dict(path=str(path), bytes=len(raw), sha256=checksum)


def write(name, value):
    (HERE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


source, source_ref = bound(R / 'raw/strict-native-phase-v3/function-audit-v1/audit.py',
    '6fa57d1bb99a9fbdb49613ffc90cb4b648aa9511465957aec25b9e58e34e76aa')
raw, raw_ref = bound(R / 'raw/strict-native-phase-v3/AB1/xtask.log',
    'c74a5a24106e3e59a4c03316b428f9591e5e481bce5f65a874f4231b7d10814b')
report_raw, report_ref = bound(R / 'raw/strict-native-phase-v3/function-audit-v1/AB1-actual-audit-v1/report.json',
    '1a9257ef78caf570267dcb89c60d3143cf97dd033f9460b56176347f594d0b25')
report = json.loads(report_raw)

# Extract only immutable regex assignments; do not instantiate Log or run any gate.
names = {'ANSI', 'MARKER', 'EXPLICIT', 'CANDIDATE', 'NONZERO_ERROR'}
assignments = [node for node in ast.parse(source).body
               if isinstance(node, ast.Assign) and len(node.targets) == 1
               and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names]
assert len(assignments) == len(names)
namespace = {'re': re}
exec(compile(ast.Module(body=assignments, type_ignores=[]), str(source_ref['path']), 'exec'), namespace)

candidates, suite, cache, partial = [], [], [], []
offset = 0
saved_candidate_bytes = bytearray()
for number, line in enumerate(raw.splitlines(keepends=True), 1):
    text = namespace['ANSI'].sub('', line.decode('utf-8', errors='replace').rstrip('\r\n'))
    ref = dict(line=number, offset=offset, bytes=len(line), sha256=hashlib.sha256(line).hexdigest())
    marker = namespace['MARKER'].search(text)
    match = namespace['CANDIDATE'].search(text)
    classification = None
    if namespace['EXPLICIT'].search(text):
        classification = 'explicit-host-or-guest-failure'
    elif marker and (marker.group().endswith(('_FAIL', '_FAILED', '_FAILURE')) or marker.group().startswith('VIRQ_FAILURE_')):
        classification = 'known-protocol-failure'
    elif any(int(m[1]) > 0 for m in namespace['NONZERO_ERROR'].finditer(text)):
        classification = 'nonzero-error-counter'
    elif marker and 'DIAGNOSTIC' in marker.group():
        classification = 'diagnostic-failure'
    elif match:
        classification = 'unclassified-reject'
    if match or classification:
        row = dict(ref, marker=marker.group() if marker else None, text=text,
                   error_classification=classification, requires_rejection=True,
                   first_candidate_match=match.group() if match else None,
                   first_candidate_match_text_offset=match.start() if match else None,
                   raw_copy_offset=len(saved_candidate_bytes))
        saved_candidate_bytes.extend(line)
        candidates.append(row)
    if marker and marker.group() in {'AXTEST_BEGIN', 'AXTEST_CASE', 'AXTEST_SUMMARY', 'AXTEST_SUITE_OK'}:
        suite.append(dict(ref, marker=marker.group(), text=text))
    if 'USER_CACHE' in text or 'Cache files will be written to:' in text:
        cache.append(dict(ref, text=text))
    if not line.endswith(b'\n') and text.strip():
        partial.append(dict(ref, text=text))
    offset += len(line)
assert offset == len(raw)

# The report field is checked without changing its existing classification.
def find_candidates(value):
    if isinstance(value, dict):
        if 'error_candidates' in value:
            return value['error_candidates']
        for child in value.values():
            found = find_candidates(child)
            if found is not None:
                return found
    return None

original_candidates = find_candidates(report)
assert original_candidates is not None
for field in ('line', 'offset', 'bytes', 'sha256', 'marker', 'text', 'error_classification', 'requires_rejection'):
    assert [x[field] for x in candidates] == [x[field] for x in original_candidates], field
assert len(candidates) == 2 and {x['line'] for x in candidates} == {24, 52}
assert all(x['first_candidate_match'] == 'error' for x in candidates)
(HERE / 'suite-candidates.raw').write_bytes(saved_candidate_bytes)

freeze, freeze_ref = bound(TOOLS / 'freeze-manifest.json',
    '0bf9ff1cbc154583c60c6dd34688c9b498b6f63b0ef8014d1dbcec04f7ed28e8')
manifest = json.loads(freeze)
offline_key = 'evidence/cache-v3-validation/zephyr-capability-cache-cause.json'
offline_raw, offline_ref = bound(TOOLS / offline_key, manifest[offline_key]['sha256'])
assert len(offline_raw) == manifest[offline_key]['bytes']
offline = json.loads(offline_raw)
offline_selection = offline['actual_stdout_selects_user_cache']
write('suite-diagnosis.json', dict(
    scope='isolated regex classification and exact raw spans; no full audit or target success',
    sources=dict(sealed_auditor=source_ref, original_report=report_ref, raw=raw_ref),
    candidates=candidates, candidate_count=len(candidates),
    exact_original_report_classifications_reproduced=True,
    explicit_or_protocol_failure_candidate_count=sum(x['error_classification'] != 'unclassified-reject' for x in candidates),
    unframed_nonempty_final_rows=partial, raw_ends_with_LF=raw.endswith(b'\n'),
    raw_candidate_copy=dict(path=str(HERE / 'suite-candidates.raw'), bytes=len(saved_candidate_bytes),
                            sha256=hashlib.sha256(saved_candidate_bytes).hexdigest()),
    suite_marker_records=suite,
    user_cache=dict(actual_raw_records=cache,
                    frozen_offline_witness=offline_ref,
                    frozen_offline_witness_field='actual_stdout_selects_user_cache',
                    frozen_offline_selection=offline_selection,
                    observed_paths_equal=False,
                    selection_cause='unknown; no cache or environment changes or new configuration performed',
                    freeze=freeze_ref),
    normal_end_to_end_GREEN=False, full_function_passed=False))

capture, capture_ref = bound(TOOLS / 'capture_native.py',
    '61717a37b528e2e93d8cbcae1c1dafbc6249ac3417fbf0b8011b984a03a4c683')
def snippets(raw_source, ranges):
    lines = raw_source.decode().splitlines()
    return [dict(line_start=lo, line_end=hi,
                 text='\n'.join(str(i) + ':' + lines[i-1] for i in range(lo, hi+1)))
            for lo, hi in ranges]
write('source-rules.json', dict(
    auditor=dict(reference=source_ref, snippets=snippets(source, [(21,25), (124,138), (156,161), (524,535), (540,566), (668,682)])),
    capture=dict(reference=capture_ref, snippets=snippets(capture, [(86,131), (296,345), (480,510)]))))
print(json.dumps(dict(candidate_count=len(candidates), candidate_lines=[x['line'] for x in candidates],
                      first_match_offsets=[x['first_candidate_match_text_offset'] for x in candidates],
                      suite_marker_lines=[x['line'] for x in suite],
                      actual_user_cache=[x['text'] for x in cache],
                      frozen_offline_user_cache=offline_selection,
                      full_function_passed=False), indent=2))
