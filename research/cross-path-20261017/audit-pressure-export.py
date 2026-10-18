#!/usr/bin/env python3
"""Verify bulk SGI reports follow both VM-group retirement and trace freeze."""
import argparse
import hashlib
import json
from pathlib import Path
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('name')
args = parser.parse_args()
archive = Path(__file__).resolve().parent
raw = (archive/'raw'/(args.name+'.log')).read_bytes()
log = raw.decode('utf-8', errors='replace')
retired = [m.start() for m in re.finditer('VIRQ_VM_GROUP_RETIRED count=2 empty=1', log)]
events = [m.start() for m in re.finditer('VIRQ_IRQ_PRESSURE_EVENT ', log)]
assert len(retired) == 2 and events, 'missing VM retirement or pressure events'
assert min(events) > max(retired), 'bulk pressure export preceded VM retirement'
freeze = list(re.finditer(r'VIRQ_TRACE_FROZEN records=(\d+) dropped=(\d+) incomplete=(\d+) vm_groups_retired=2', log))
assert len(freeze) == 1 and max(retired) < freeze[0].start() < min(events)
reports = re.findall(r'VIRQ_IRQ_PRESSURE_SUMMARY policy=(\S+) sent=(\d+) handled=(\d+) errors=(\d+)[^\r\n]* skipped_periods=(\d+) joined=1 retired=1', log)
assert sorted(p for p, *_ in reports) == ['fair','fifo80']
assert all(s == h and e == '0' for _,s,h,e,_ in reports)
assert len(events) == sum(int(s) for _,s,_,_,_ in reports)
result = dict(run=args.name, raw_log_sha256=hashlib.sha256(raw).hexdigest(),
              pressure_events=len(events), vm_groups_retired_before_export=True,
              policies={p:dict(sent=int(s),handled=int(h),errors=int(e),skipped_periods=int(k))
                        for p,s,h,e,k in reports},
              frozen_before_export=True,
              trace_records=int(freeze[0][1]), dropped=int(freeze[0][2]), incomplete=int(freeze[0][3]),
              measurement_accepted=None, scope='Export ordering only; independent analyses still required')
(archive/'results'/(args.name+'-export-audit.json')).write_text(json.dumps(result,indent=2)+'\n')
print(f'PRESSURE_EXPORT_ORDER_OK events={len(events)} dropped={result["dropped"]} incomplete={result["incomplete"]}')
