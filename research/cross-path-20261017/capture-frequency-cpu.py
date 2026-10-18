#!/usr/bin/env python3
"""Verify the CPU-owned PMU sources frozen before a frequency cohort build."""
import hashlib
import json
from pathlib import Path
import sys
import tarfile

archive=Path(__file__).resolve().parent
repo=archive.parent.parent
out=archive/'configs'/sys.argv[1]
path=out/'cpu-sources.tar.gz'
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
sources={}
with tarfile.open(path) as snapshot:
    for member in snapshot:
        if not member.isfile() or '__pycache__' in member.name:
            continue
        assert member.name.startswith('components/axcpu/')
        sha=hashlib.sha256(snapshot.extractfile(member).read()).hexdigest()
        assert digest(repo/member.name)==sha,'CPU source changed during cohort'
        sources[member.name]=sha
(out/'cpu-source-provenance.json').write_text(json.dumps(dict(
    archive_sha256=digest(path),source_sha256=sources,
    capture_script_sha256=digest(Path(__file__)),
    scope='ax-cpu sources frozen before build; no implied firmware or whole-workspace immutability'),indent=2)+'\n')
print(f'FREQUENCY_CPU_SOURCES_OK files={len(sources)}')
