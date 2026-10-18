#!/usr/bin/env python3
"""Run a local audit preparation command and retain its actual wait receipt."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    if not argv:
        parser.error("missing command")
    root = Path(__file__).resolve().parent
    receipt_dir = root / "commands" / args.name
    receipt_dir.mkdir(exist_ok=False)
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC",
           "PYTHONDONTWRITEBYTECODE": "1"}
    cwd = "/home/yanlien/Program/hypervisor/tgoskits"
    receipt = {"argv": argv, "env": env, "cwd": cwd,
               "started_ns": time.time_ns(), "forced_stop": False}
    with (receipt_dir / "stdout").open("wb") as out, (receipt_dir / "stderr").open("wb") as err:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err)
        receipt["pid"] = child.pid
        receipt["wait_returncode"] = child.wait()
    receipt["returncode"] = child.returncode
    receipt["ended_ns"] = time.time_ns()
    for stream in ("stdout", "stderr"):
        path = receipt_dir / stream
        data = path.read_bytes()
        receipt[stream] = {"path": str(path), "size": len(data),
                           "sha256": hashlib.sha256(data).hexdigest()}
    (receipt_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print((receipt_dir / "stdout").read_text(errors="replace"), end="")
    print((receipt_dir / "stderr").read_text(errors="replace"), end="")
    print("RECEIPT " + str(receipt_dir / "receipt.json"))
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
