#!/usr/bin/env python3
"""Verify this diagnosis archive and the exact unchanged original documents."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]


def reference(path):
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


receipts = []
for path in sorted((HERE / 'commands').glob('*/receipt.json')):
    receipt = json.loads(path.read_bytes())
    actual = receipt.get('wait_returncode', receipt.get('actual_Popen_wait', receipt.get('returncode')))
    expected = 1 if path.parent.name == '0009-final-evidence-seal' else 0
    assert actual == expected, (str(path), actual, expected)
    for stream in ('stdout', 'stderr'):
        recorded = receipt[stream]
        observed = reference(Path(recorded['path']))
        # The bootstrap receipt uses bytes; the inherited runner uses size.
        assert observed['bytes'] == recorded.get('bytes', recorded.get('size'))
        assert observed['sha256'] == recorded['sha256']
    receipts.append(dict(reference=reference(path), actual_Popen_wait=actual))
assert len(receipts) == 10
report_path = R / 'results/strict-native-cache-v3-AB1-auditor-cause-v1.json'
report = json.loads(report_path.read_bytes())
assert report['full_function_passed'] is False and report['normal_end_to_end_GREEN'] is False
assert report['actual_original_audit']['actual_Popen_wait'] == 1
assert report['suite_refusal']['candidate_count'] == 2
expected = {
    R / 'raw/strict-native-phase-v3/function-audit-v1/audit.py':
        '6fa57d1bb99a9fbdb49613ffc90cb4b648aa9511465957aec25b9e58e34e76aa',
    R / 'raw/strict-native-phase-v3/function-audit-v1/AB1-actual-audit-v1/report.json':
        '1a9257ef78caf570267dcb89c60d3143cf97dd033f9460b56176347f594d0b25',
    R / 'raw/strict-native-phase-v3/AB1-root-final-handoff-v1.json':
        'cf25d62d4ff106f0e6d3315ce4e0b58ce5f4d78ac2e90b7b79fe814116e9b72f',
    Path('/tmp/crosspath-native-cache-v3-tools-jrhcn15t/capture_native.py'):
        '61717a37b528e2e93d8cbcae1c1dafbc6249ac3417fbf0b8011b984a03a4c683',
}
originals = []
for path, checksum in expected.items():
    observed = reference(path)
    assert observed['sha256'] == checksum
    originals.append(observed)
seal = dict(
    scope='final read-only diagnosis evidence seal; not a full normal audit',
    reports=[reference(report_path), reference(report_path.with_suffix('.md'))],
    completed_command_receipts=receipts,
    archival_verification_note='0009 exited 1 because its receipt checker expected bytes while the inherited runner records size. 0010 inspected the exact schema; this checker verifies both explicit historical schemas. No parser rule, candidate classification, sealed original, or result changed.',
    unchanged_originals=originals,
    supporting_outputs=[reference(HERE / name) for name in [
        'format-diagnosis.json', 'suite-diagnosis.json', 'source-rules.json',
        'suite-candidates.raw', 'host-newc-gzip-boundary.raw', 'seal_evidence.py']],
    normal_end_to_end_GREEN=False,
    full_function_passed=False)
path = HERE / 'evidence-seal.json'
path.write_text(json.dumps(seal, indent=2) + '\n')
print(json.dumps(dict(reports=seal['reports'], completed_prior_receipts=len(receipts),
                      expected_archival_attempt_failure='0009=1; retained',
                      all_other_prior_actual_waits=0, evidence_seal=reference(path),
                      normal_end_to_end_GREEN=False), indent=2))
