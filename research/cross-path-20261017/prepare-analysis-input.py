#!/usr/bin/env python3
"""Keep raw serial bytes; permit decoding replacements only before measurement."""
import codecs
import hashlib
import json
from pathlib import Path
import sys

raw_path, output = Path(sys.argv[1]), Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=True)
raw = raw_path.read_bytes()
spans = []

def replace_boot_noise(error):
    spans.append((error.start, error.end))
    return '\ufffd', error.end

codecs.register_error('virq_boot_serial_noise', replace_boot_noise)
decoded = raw.decode('utf-8', errors='virq_boot_serial_noise')
start = raw.find(b'VIRQ_MEASUREMENT ')
valid = start >= 0 and all(end <= start for _, end in spans)
report = dict(raw_path=str(raw_path), raw_sha256=hashlib.sha256(raw).hexdigest(),
              invalid_utf8_spans=spans, invalid_utf8_bytes=sum(b-a for a,b in spans),
              measurement_offset=start, decoding_valid_for_analysis=valid,
              policy='Only pre-measurement UTF-8 replacement; no line removal or measurement repair')
if valid:
    measurement = decoded[decoded.index('VIRQ_MEASUREMENT '):].encode('utf-8')
    assert measurement == raw[start:], 'measurement bytes changed during decoding'
    report['measurement_bytes_unchanged'] = True
    report['measurement_sha256'] = hashlib.sha256(measurement).hexdigest()
    analysis_input = decoded.encode('utf-8')
    (output/'analysis-input.log').write_bytes(analysis_input)
    report['analysis_input_sha256'] = hashlib.sha256(analysis_input).hexdigest()
(output/'analysis-input-provenance.json').write_text(json.dumps(report, indent=2)+'\n')
assert valid, 'Missing measurement marker or invalid UTF-8 inside/after measurement; raw bytes retained'
print(f'ANALYSIS_INPUT_OK invalid_boot_bytes={report["invalid_utf8_bytes"]} measurement_bytes_unchanged=1')
