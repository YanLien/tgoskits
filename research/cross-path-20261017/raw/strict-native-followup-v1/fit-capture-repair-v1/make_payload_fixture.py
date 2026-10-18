#!/usr/bin/env python3
"""Create only private, software-only relocated inputs; no original file is written."""
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
fixture = HERE / 'payload-fixture'
fixture.mkdir()
refs = json.loads((HERE / 'input-refs.json').read_text())
original = json.loads(Path(refs['original_capture']['path']).read_text())
inputs = json.loads((HERE / 'repaired/inputs.json').read_text())
original_target = Path(inputs['target'])
relocated = {}
for label, row in original['artifacts'].items():
    source = Path(row['saved'])
    destination = fixture / 'target' / Path(row['path']).relative_to(original_target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    assert not destination.exists()
    shutil.copy2(source, destination)
    assert source.stat().st_ino != destination.stat().st_ino
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == row['sha256']
    relocated[label] = destination
fit = relocated['host_fit']
before = fit.read_bytes()
payload = (HERE / 'green/artifacts/fit-kernel').read_bytes()
assert hashlib.sha256(payload).hexdigest() == original['artifacts']['host_bin']['sha256']
assert before.count(payload) == 1
payload_start = before.index(payload)
offset = payload_start + len(payload) // 2
after = bytearray(before)
after[offset] ^= 1
assert sum(a != b for a, b in zip(before, after)) == 1
assert fit.stat().st_nlink == 1
fit.write_bytes(after)
changed = []
for label, destination in relocated.items():
    if hashlib.sha256(destination.read_bytes()).hexdigest() != original['artifacts'][label]['sha256']:
        changed.append(label)
assert changed == ['host_fit']
scope = 'synthetic software-only relocation; no boot or Guest runtime data'
log = '\n'.join([
    '# ' + scope,
    'kernel from: ' + str(relocated['host_bin']),
    'FIT image ok: ' + str(relocated['host_fit']),
    'Using DTB from: ' + str(relocated['host_preset_dtb']),
    'cargo build elf=' + str(relocated['host_elf']),
    'Axvisor host initramfs ' + str(relocated['host_initramfs']) + ' sha256=' + original['artifacts']['host_initramfs']['sha256'],
]) + '\n'
with (fixture / 'synthetic-relocation.log').open('x') as stream:
    stream.write(log)
record = {'scope': scope, 'changed_payload_bytes': 1, 'changed_artifact_labels': changed,
          'selected_component': 'kernel', 'FIT_byte_offset': offset, 'payload_byte_offset': offset - payload_start,
          'before_byte': before[offset], 'after_byte': after[offset],
          'original_FIT_sha256': hashlib.sha256(before).hexdigest(), 'mutated_FIT_sha256': hashlib.sha256(after).hexdigest(),
          'external_BIN_sha256_unchanged': original['artifacts']['host_bin']['sha256'],
          'external_initramfs_sha256_unchanged': original['artifacts']['host_initramfs']['sha256'],
          'relocated_paths': {key: str(value) for key, value in relocated.items()},
          'metadata_note': 'original build metadata paths are retained; rejection must occur earlier at FIT binding'}
with (fixture / 'fixture.json').open('x') as stream:
    json.dump(record, stream, indent=2, sort_keys=True)
    stream.write('\n')
print(json.dumps(record, sort_keys=True))
