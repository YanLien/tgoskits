"""Protect one-shot execution and fail-stop preservation between board boots."""
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest

from factorial_runner import DERIVED_INPUTS, execute_runs, normalized_fit_sha256, normalized_linux_vm, validate_completed, validate_runtime_sidecars, verify_derived
from factorial_statistics import balanced_blocks


class FactorialRunner(unittest.TestCase):
    def test_runtime_directory_requires_both_preparation_and_packaging_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            reference=root/"reference"; reference.mkdir()
            actual=root/"actual"; actual.mkdir()
            board=actual/"board.toml"; board.write_text('timeout=1\n')
            for name, content in (("guest-builds.toml", 'host_prepare=["prepare"]\n'),
                                  ("host-initramfs.toml", 'source="resources"\n')):
                (reference/name).write_text(content)
            with self.assertRaises(ValueError):
                validate_runtime_sidecars(board, reference)
            (actual/"host-initramfs.toml").write_bytes((reference/"host-initramfs.toml").read_bytes())
            with self.assertRaises(ValueError):
                validate_runtime_sidecars(board, reference)
            (actual/"guest-builds.toml").write_bytes((reference/"guest-builds.toml").read_bytes())
            validate_runtime_sidecars(board, reference)
            (actual/"guest-builds.toml").write_text('host_prepare=[]\n')
            with self.assertRaises(ValueError):
                validate_runtime_sidecars(board, reference)

    def test_fit_identity_excludes_only_the_root_packaging_timestamp(self):
        def fit(timestamp, payload):
            prop = lambda length, name: struct.pack(">III", 3, length, name)
            body = (struct.pack(">I", 1)+b"\0"*4+prop(4, 0)+struct.pack(">I", timestamp)
                    +struct.pack(">I", 1)+b"image\0\0\0"+prop(len(payload), 10)+payload+b"\0"*((-len(payload))%4)
                    +struct.pack(">III", 2, 2, 9))
            strings = b"timestamp\0data\0"
            header = struct.pack(">10I", 0xd00dfeed, 56+len(body)+len(strings), 56, 56+len(body), 40, 17, 16, 0, len(strings), len(body))
            return header+b"\0"*16+body+strings
        self.assertEqual(normalized_fit_sha256(fit(10, b"kernel")), normalized_fit_sha256(fit(20, b"kernel")))
        self.assertNotEqual(normalized_fit_sha256(fit(10, b"kernel")), normalized_fit_sha256(fit(10, b"changed")))
        with self.assertRaises(ValueError):
            normalized_fit_sha256(b"not-a-fit")

    def test_summary_requires_the_pinned_complete_plan(self):
        blocks = [dict(block=i+1, order=order, runs=[dict(block=i+1, position=j+1, condition=c,
                  name=f"sample-{i}-{j}") for j, c in enumerate(order)]) for i, order in enumerate(balanced_blocks(7))]
        plan = dict(cohort="example-cohort", seed=7, independent_blocks=8, native_boots=32, blocks=blocks)
        state = dict(terminal=True, success=True, plan_sha256="pinned",
                     completed=[dict(r, tasks=64) for b in blocks for r in b["runs"]])
        self.assertEqual(len(validate_completed(plan, state, "pinned")), 32)
        for broken_state, actual_hash in (({**state, "completed": state["completed"][:-1]}, "pinned"),
                                         ({**state, "completed": [{**r, "condition": "AB"} for r in state["completed"]]}, "pinned"),
                                         (state, "changed")):
            with self.subTest(broken_state=broken_state), self.assertRaises(ValueError):
                validate_completed(plan, broken_state, actual_hash)
        with self.assertRaises(ValueError):
            validate_completed({**plan, "blocks": blocks[:-1]}, state, "pinned")
        # Finishing collection does not release the board to a subsequent
        # workflow until statistics, figures and the original seal finish.
        from topology_native import require_primary_complete
        pipeline = dict(cohort="example-cohort", terminal=True, success=True, phase="sealed")
        self.assertEqual(len(require_primary_complete(plan, state, pipeline, "pinned")), 32)
        for unready in (dict(pipeline, terminal=False), dict(pipeline, success=False),
                        dict(pipeline, phase="figures"), dict(pipeline, cohort="other-cohort")):
            with self.assertRaises(ValueError):
                require_primary_complete(plan, state, unready, "pinned")
        with self.assertRaises(ValueError):
            require_primary_complete(plan, {**state, "completed": [dict(r, tasks=63) for r in state["completed"]]},
                                     pipeline, "pinned")

    def test_modified_or_unbound_derived_inputs_cannot_enter_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            hashes = {}
            for relative in DERIVED_INPUTS:
                path = output/relative
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b"accepted-input")
                hashes[relative] = hashlib.sha256(b"accepted-input").hexdigest()
            accepted = dict(derived_sha256=hashes)
            verify_derived(output, accepted)
            with self.assertRaises(ValueError):
                verify_derived(output, dict(derived_sha256={}))
            (output/"task/samples.csv").write_bytes(b"modified")
            with self.assertRaises(ValueError):
                verify_derived(output, accepted)

    def test_identity_only_normalizes_the_assigned_linux_workload_name(self):
        cpu = '[base]\nname="linux-ordinary-cpu"\ncpus=[3]\nram=64\n'
        memory = cpu.replace('linux-ordinary-cpu', 'linux-ordinary-memory')
        self.assertEqual(normalized_linux_vm(cpu, "linux_cpu"), normalized_linux_vm(memory, "linux_memory"))
        self.assertNotEqual(normalized_linux_vm(cpu, "linux_cpu"), normalized_linux_vm(memory.replace('cpus=[3]', 'cpus=[2]'), "linux_memory"))
        with self.assertRaises(ValueError):
            normalized_linux_vm(cpu, "linux_memory")

    def test_failure_preserves_active_run_and_prevents_following_boots(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory)/"state.json"
            visited = []

            def run_one(run):
                visited.append(run["name"])
                subprocess.run([sys.executable, "-c", "raise SystemExit(7)" if run["name"] == "bad" else "pass"], check=True)
                return dict(name=run["name"], accepted=True)

            with self.assertRaises(subprocess.CalledProcessError):
                execute_runs([dict(name=name) for name in ("accepted", "bad", "never")], state_path, run_one)
            state = json.loads(state_path.read_text())
            self.assertEqual(visited, ["accepted", "bad"])
            self.assertTrue(state["terminal"])
            self.assertFalse(state["success"])
            self.assertEqual(state["active_run"], "bad")
            self.assertEqual([r["name"] for r in state["completed"]], ["accepted"])
            with self.assertRaises(FileExistsError):
                execute_runs([dict(name="restart")], state_path, run_one)
            self.assertEqual(visited, ["accepted", "bad"])


if __name__ == "__main__":
    unittest.main()
