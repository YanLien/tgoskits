#!/usr/bin/env python3
"""Collect separate bounded QEMU boots; preserve failures and never pool tails."""

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from analyze_virq_physical import analyze


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def collect(args):
    if not 1 <= args.samples <= 1000 or not 1 <= args.batches <= 100:
        raise ValueError("samples must be 1..1000 and batches 1..100")
    # Creation is exclusive: failed/partial evidence is never silently reused.
    args.evidence.mkdir(parents=True, exist_ok=False)
    command = ["cargo", "xtask", "ktest", "qemu", "-p", "axvm", "--test", "vcpu_runtime",
               "--arch", "aarch64", "--config",
               "virtualization/axvm/tests/vcpu-runtime/build-aarch64-unknown-none-softfloat.toml",
               "--qemu-config", "virtualization/axvm/tests/vcpu-runtime/qemu-aarch64.toml"]
    env = dict(os.environ, VIRQ_SAMPLES=str(args.samples), VIRQ_SOURCE=args.source,
               VIRQ_HOST_LOAD="baseline", VIRQ_IRQ_CONTEXT="current_el",
               VIRQ_SERVICE_PLACEMENT="cpu0")
    artifacts = json.loads(args.artifact_map.read_text())
    selected_env = {key: value for key, value in env.items()
                    if key.startswith("VIRQ_") or key in ("CARGO_TARGET_DIR", "CROSS_COMPILE")}
    (args.evidence / "command.json").write_text(json.dumps(
        dict(command=command, environment=selected_env, requested_batches=args.batches,
             artifact_map=artifacts, statistical_independence_assumed=False), indent=2) + "\n")
    manifest = dict(completed=[], requested_batches=args.batches, all_passed=False,
                    samples_per_policy_per_boot=args.samples, pooled=False)
    manifest_path = args.evidence / "runs.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    for index in range(1, args.batches + 1):
        folder = args.evidence / f"boot-{index:03d}"
        folder.mkdir()
        record = dict(boot=index, analysis_passed=False)
        started = time.monotonic()
        with (folder / "qemu.log").open("w") as stream:
            result = subprocess.run(command, cwd=args.repo, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, check=False)
        record.update(exit_code=result.returncode, elapsed_seconds=time.monotonic() - started)
        (folder / "exit.json").write_text(json.dumps(record, indent=2) + "\n")
        if result.returncode:
            raise RuntimeError(f"boot {index} failed; raw evidence preserved at {folder}")
        try:
            rows, summary = analyze((folder / "qemu.log").read_text())
            if len(rows) != args.samples * 2:
                raise ValueError("analysis returned unexpected cohort size")
            with (folder / "samples.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            binary = {}
            for name, entry in artifacts.items():
                source = Path(entry["source"])
                sha = digest(source)
                archive = args.evidence / f"{sha}-{name}.gz"
                if not archive.exists():
                    with source.open("rb") as incoming, archive.open("wb") as outgoing:
                        with gzip.GzipFile(fileobj=outgoing, mode="wb", mtime=0) as packed:
                            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                                packed.write(block)
                # Read back every archive; a previous boot's archive is not trusted.
                with gzip.open(archive, "rb") as packed:
                    restored = hashlib.sha256()
                    for block in iter(lambda: packed.read(1024 * 1024), b""):
                        restored.update(block)
                if restored.hexdigest() != sha:
                    raise ValueError(f"archive verification failed: {name}")
                binary[name] = dict(source=str(source), bytes=source.stat().st_size,
                                    sha256=sha, archive=str(archive), gzip_sha256=digest(archive))
            (folder / "binary.json").write_text(json.dumps(binary, indent=2) + "\n")
            record.update(analysis_passed=True, samples=len(rows), log_sha256=digest(folder / "qemu.log"))
        except Exception as error:
            (folder / "analysis-error.txt").write_text(f"{type(error).__name__}: {error}\n")
            raise
        finally:
            (folder / "exit.json").write_text(json.dumps(record, indent=2) + "\n")
        manifest["completed"].append(record)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"boot {index}/{args.batches}: {len(rows)} samples verified", flush=True)
    manifest["all_passed"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--artifact-map", type=Path, required=True,
                        help="explicit built artifact paths; each entry has a source field")
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--batches", type=int, required=True)
    parser.add_argument("--source", choices=("pl031_spi", "physical_timer_ppi"), default="pl031_spi")
    collect(parser.parse_args())


if __name__ == "__main__":
    main()
