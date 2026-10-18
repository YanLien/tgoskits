#!/usr/bin/env python3
"""Verify the extra driver/feature inputs frozen before a thermal cohort build."""
import hashlib
import json
from pathlib import Path
import sys
import tarfile

archive=Path(__file__).resolve().parent
repo=archive.parent.parent
out=archive/'configs'/sys.argv[1]
path=out/'driver-sources.tar.gz'
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
sources={}
with tarfile.open(path) as snapshot:
    for member in snapshot:
        if not member.isfile() or '__pycache__' in member.name:
            continue
        assert member.name.startswith('drivers/ax-driver/') or member.name in ('virtualization/axvm/Cargo.toml','Cargo.lock')
        sha=hashlib.sha256(snapshot.extractfile(member).read()).hexdigest()
        assert digest(repo/member.name)==sha,'driver source changed during cohort'
        sources[member.name]=sha
(out/'driver-source-provenance.json').write_text(json.dumps(dict(
    archive_sha256=digest(path),source_sha256=sources,
    capture_script_sha256=digest(Path(__file__)),
    scope='Driver sources, axvm feature manifest and lockfile frozen before build; no implied firmware immutability'),indent=2)+'\n')
print(f'THERMAL_DRIVER_SOURCES_OK files={len(sources)}')
