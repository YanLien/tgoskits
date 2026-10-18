#!/usr/bin/env python3
"""Execute the registered cohort, statistics, figures and seal exactly once."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ARCHIVE = Path(__file__).resolve().parent
REPO = ARCHIVE.parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery", action="store_true", help="use a new cohort after the preserved pre-measurement assembly failure")
    args = parser.parse_args()
    cohort = "factorial-recovery" if args.recovery else "factorial"
    prefix = "phase12-recovery" if args.recovery else "phase12"
    status_path = Path(f"/tmp/{prefix}-pipeline-status.json")
    log_path = Path(f"/tmp/{prefix}-pipeline.log")
    if status_path.exists() or log_path.exists():
        raise FileExistsError("inspect the existing pipeline and its recorded PID; never restart blindly")
    state = dict(controller_pid=os.getpid(), cohort=cohort, started_unix=time.time(), phase="preregister", terminal=False, success=False)

    def save():
        temporary = status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2)+"\n")
        temporary.replace(status_path)

    with status_path.open("x") as stream:
        stream.write(json.dumps(state, indent=2)+"\n")
    try:
        with log_path.open("x") as stream:
            for phase, command in (
                ("factorial", ["python3", str(ARCHIVE/"factorial_runner.py")]),
                ("statistics", ["python3", str(ARCHIVE/"summarize-factorial.py")]),
                ("figures", ["/tmp/crosspath-plot-env/bin/python3", str(ARCHIVE/"plot-phase12.py")]),
                ("seal", ["python3", str(ARCHIVE/"finalize-phase12.py")])):
                state["phase"] = phase
                save()
                print(f"PHASE12_PIPELINE_BEGIN phase={phase} pid={os.getpid()}", flush=True)
                stream.flush()
                if phase == "seal":
                    (ARCHIVE/"raw"/f"{prefix}-pipeline-before-seal.log").write_bytes(log_path.read_bytes())
                subprocess.run(command, cwd=REPO, check=True, stdout=stream, stderr=subprocess.STDOUT,
                               env=dict(os.environ, FACTORIAL_COHORT=cohort))
        state.update(terminal=True, success=True, phase="sealed", finished_unix=time.time())
        save()
        print("PHASE12_PIPELINE_DONE full_phase0_to2=0 M1=0 M2=0", flush=True)
    except BaseException as error:
        state.update(terminal=True, success=False, error=repr(error), finished_unix=time.time())
        save()
        raise


if __name__ == "__main__":
    main()
