"""Check memory traffic accounting and full-buffer verification provenance."""

import unittest

from analyze_virq_load import analyze, validate_load
from test_virq_ready_analysis import fixture as ready_fixture


def memory_fixture():
    size, words = 1024*1024, 1024*1024//8
    final = 162
    checksum = (words*(words-1)//2 + final*1024) % (1 << 64)
    lines = ["VIRQ_CONTROLLER cpu=0", "VIRQ_SCENARIO name=memory_cross_core",
             f"VIRQ_MEMORY_CONFIG cpu=2 working_set_bytes={size} chunk_words=1024 access=volatile_read_modify_write"]
    for policy in ("fair", "fifo80"):
        lines.append(f"VIRQ_LOAD_BOOT_WORK policy={policy} batches=10")
        for sample in range(1, 301):
            before, after = 11+(sample-1)//2, 11+sample//2
            lines.append(f"VIRQ_LOAD_SAMPLE policy={policy} sample={sample} before_batches={before} after_batches={after}")
        lines.append(f"VIRQ_MEMORY_SUMMARY policy={policy} cpu=2 thread=99 working_set_bytes={size} chunk_words=1024 start_batches=11 end_batches=161 final_batches={final} read_bytes={final*8192} write_bytes={final*8192} checksum={checksum} verified_words={words} mismatch_words=0 wrong_cpu=0 joined=1")
    return "\n".join(lines)+"\n"


class MemoryAnalysis(unittest.TestCase):
    def test_completed_chunks_have_independent_traffic_and_checksum_accounting(self):
        rows, report = analyze(ready_fixture()+memory_fixture())
        self.assertEqual(len(rows), 600)
        self.assertEqual(rows[0]["logical_read_bytes"], 0)
        self.assertEqual(rows[1]["logical_write_bytes"], 8192)
        self.assertEqual(report["loads"]["fair"]["interval_logical_read_bytes"], 150*8192)
        self.assertEqual(report["loads"]["fifo80"]["verified_words"], 131072)

    def test_traffic_data_integrity_and_cohort_mismatches_cannot_claim_success(self):
        valid = memory_fixture()
        for invalid in (valid.replace("read_bytes=1327104", "read_bytes=1", 1),
                        valid.replace("checksum=8590034944", "checksum=1", 1),
                        valid.replace("verified_words=131072", "verified_words=1024", 1),
                        valid.replace("mismatch_words=0", "mismatch_words=1", 1),
                        valid.replace("cpu=2", "cpu=1", 1),
                        valid.replace("start_batches=11", "start_batches=161", 1),
                        valid.replace("name=memory_cross_core", "name=baseline"),
                        valid.replace("VIRQ_MEMORY_SUMMARY policy=fifo80", "VIRQ_MEMORY_SUMMARY policy=fair", 1)):
            self.assertNotEqual(invalid, valid)
            with self.assertRaises(ValueError):
                validate_load(invalid)


if __name__ == "__main__":
    unittest.main()
