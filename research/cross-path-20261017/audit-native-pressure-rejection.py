#!/usr/bin/env python3
"""Keep the real A+B loss failure distinct from successful delivery checks."""
import hashlib
import json
from pathlib import Path
import re

archive = Path(__file__).resolve().parent
name = 'native-private-ram-board-memory-sgi-32'
config = archive/'configs'/name
raw = (archive/'raw'/(name+'.log')).read_bytes()
log = raw.decode('utf-8',errors='replace')
identity = json.loads((config/'provenance.json').read_text())
assert identity['exit_code'] == 1 and 'AXTEST_SUITE_OK' not in log
assert 'AXVM_TEST_FAILED runtime trace lost records' in log
assert log.count('VIRQ_VM_GROUP_RETIRED count=2 empty=1') == 2
assert 'VIRQ_RUNTIME_SUMMARY' not in log
critical = re.findall(r'VIRQ_PHYSICAL_SUMMARY policy=(\S+) intid=30 cpu=0 handled=(\d+) errors=(\d+) retired=1',log)
assert sorted(critical) == [('fair','32','0'),('fifo80','32','0')]
pressure = re.findall(r'VIRQ_IRQ_PRESSURE_SUMMARY policy=(\S+) sent=(\d+) handled=(\d+) errors=(\d+) [^\r\n]*skipped_periods=(\d+) joined=1 retired=1',log)
assert len(pressure) == 2
assert all(sent == handled and error == skipped == '0' for _,sent,handled,error,skipped in pressure)
base = json.loads((archive/'configs/native-private-ram-board-cpu-32/provenance.json').read_text())
assert identity['source_sha256'] == base['source_sha256']
assert identity['host_source_sha256'] == base['host_source_sha256']
assert identity['cargo_lock_sha256'] == base['cargo_lock_sha256']
report = dict(run=name,suite_passed=False,measurement_accepted=False,declared_tasks=64,accepted_tasks=0,
              failure='Runtime snapshot dropped!=0 or incomplete!=0; original guard rejected the complete run',
              exact_dropped_count=None,exact_incomplete_count=None,per_cpu_occupancy=None,
              critical_deliveries={p:dict(handled=int(n),errors=int(e)) for p,n,e in critical},
              pressure_deliveries={p:dict(sent=int(s),handled=int(h),errors=int(e),skipped_periods=int(k)) for p,s,h,e,k in pressure},
              same_test_and_host_sources_as_native_baseline=True,all_vm_groups_retired=True,
              raw_log_sha256=hashlib.sha256(raw).hexdigest(),
              observation='Pressure finish emits events while Linux and the completed critical Guest remain active; capture is frozen only after both policies',
              next_action='Keep stop/join/count/checksum validation at the same boundary; retain an owned pressure report and emit it after all VMs retire and trace is frozen; print actual loss and per-CPU occupancy before rejecting',
              guards_to_preserve=['Trace capacity','Nonzero loss rejection','SGI capacity/identity/checksum','Exact critical IRQ count','Task drain','Linux causal fence coverage'],
              M1_complete=False,M2_complete=False)
(archive/'results/native-pressure-rejection.json').write_text(json.dumps(report,indent=2)+'\n')
print('NATIVE_PRESSURE_REJECTION_OK accepted_tasks=0 same_sources=1')
