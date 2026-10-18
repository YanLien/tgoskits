#!/usr/bin/env python3
"""Audit rejected diagnostic runs and reconstruct the fixed Guest exception frame."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tarfile

archive = Path(__file__).resolve().parent
names = ['native-reset-diagnostic-board-cpu-32', 'native-reset-exit-pc-board-cpu-32',
         'native-reset-exception-board-cpu-32', 'native-reset-stack-board-cpu-32',
         'native-reset-cache-board-cpu-32']
reports = {}
for name in names:
    config = archive/'configs'/name
    identity = json.loads((config/'provenance.json').read_text())
    raw = (archive/'raw'/(name+'.log')).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == identity['raw_log_sha256']
    log = raw.decode('utf-8', errors='replace')
    assert 'VIRQ_PLATFORM kind=orangepi5plus_rk3588' in log
    for key, hashes in [('source_archive','source_sha256'), ('host_source_archive','host_source_sha256')]:
        if key not in identity:
            continue
        source = archive/identity[key]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == identity[key+'_sha256']
        with tarfile.open(source) as snapshot:
            assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == checksum
                       for p,checksum in identity[hashes].items())
    phases = re.findall(r'VIRQ_LIFECYCLE stage=(\S+) ticks=(\d+)[^\r\n]*?entry_count=(\d+) park_count=(\d+) participants=(\d+)',log)
    exits = re.findall(r'VIRQ_GUEST_EXIT_DIAGNOSTIC cpu=0 thread=(\d+) mpidr=(0x[0-9a-f]+) count=(\d+) ticks=(\d+) pc=(0x[0-9a-f]+) syndrome=(0x[0-9a-f]+)([^\r\n]*)',log)
    failure = name != names[-1]
    assert identity['exit_code'] == (1 if failure else 0)
    assert ('AXTEST_SUITE_OK' in log) == (not failure)
    if failure:
        failed = [p for p in phases if p[0] == 'ready_failed']
        assert len(failed) == 1 and int(failed[0][2]) > 0 and int(failed[0][4]) == 1
        assert 'VIRQ_VM_GROUP_RETIRED count=2 empty=1' in log
    else:
        assert sum(p[0] == 'ready_after_reset' for p in phases) == 2
        assert 'VIRQ_RUNTIME_SUMMARY records=17191 dropped=0 incomplete=0' in log
        assert 'missing or duplicate envelope markers' in (archive/'raw/native-cache-analysis.log').read_text()
    observed = sorted({int(e[4],16) for e in exits})
    if name in names[1:4]:
        bindings = re.findall(r'VIRQ_FAILURE_EVENT scope=boundary cpu=0 sequence=\d+ ticks=(\d+) kind=Binding thread=(\d+) value0=2 value1=0',log)
        assert len(bindings) == 2
        reset_thread = max(bindings,key=lambda p:int(p[0]))[1]
        halted = [e for e in exits if e[4] == '0x40003234']
        assert halted and all(e[0] == reset_thread for e in halted)
        if name in names[2:4]:
            assert all('esr_el1: 2248146959' in e[6] and 'elr_el1: 1074092160' in e[6]
                       and 'far_el1: 1074092160' in e[6] for e in halted)
    reports[name] = dict(exit_code=identity['exit_code'], suite_passed=not failure,
                         measurement_accepted=False,
                         rejection=('Post-reset Guest fatal/Ready timeout' if failure else 'Extra diagnostic Markers violate envelope contract'),
                         lifecycle=[dict(stage=p[0],ticks=int(p[1]),entry_count=int(p[2]),park_count=int(p[3]),participants=int(p[4])) for p in phases],
                         observed_irq_exit_pcs=[hex(p) for p in observed],
                         raw_log_sha256=identity['raw_log_sha256'],
                         guest_elf_sha256=identity['artifact_sha256'][str(Path('target/axbuild/axvm/vcpu-runtime/guest/zephyr/zephyr.elf'))])

assert len({p['guest_elf_sha256'] for p in reports.values()}) == 1, 'Guest ELF changed across cache control'
stack_name = names[-2]
output = archive/'results'/stack_name
output.mkdir(parents=True,exist_ok=True)
log = (archive/'raw'/(stack_name+'.log')).read_bytes().decode('utf-8',errors='replace')
regions = {}
for region, address, size in re.findall(r'VIRQ_FAILURE_MEMORY_BEGIN region=(\S+) address=(0x[0-9a-f]+) size=(\d+) concurrent=1',log):
    start, size = int(address,16), int(size)
    words = re.findall(r'VIRQ_FAILURE_MEMORY region='+re.escape(region)+r' address=(0x[0-9a-f]+) low=(0x[0-9a-f]+) high=(0x[0-9a-f]+)',log)
    assert len(words) == size//16
    payload = bytearray()
    for index,(address,low,high) in enumerate(words):
        assert int(address,16) == start+index*16
        payload += struct.pack('<QQ',int(low,16),int(high,16))
    assert f'VIRQ_FAILURE_MEMORY_END region={region} size={size}' in log
    (output/(region+'.bin')).write_bytes(payload)
    regions[region] = dict(start=start,size=size,sha256=hashlib.sha256(payload).hexdigest())
    if region == 'irq_stack_cpu0':
        candidates = []
        for offset in range(0,len(payload)-0xb0+1,16):
            words = struct.unpack_from('<22Q',payload,offset)
            if words[20] == 0x600002c5 and words[21] == 0x40055880:
                candidates.append(dict(address=hex(start+offset),x0=hex(words[0]),lr=hex(words[19]),spsr=hex(words[20]),elr=hex(words[21])))
        assert len(candidates) == 1
        frame = candidates[0]
        assert frame['lr'] == frame['elr'] == '0x40055880'
elf = archive/'configs'/stack_name/'realtime.elf'
assert hashlib.sha256(elf.read_bytes()).hexdigest() == reports[stack_name]['guest_elf_sha256']
symbols = subprocess.check_output(['aarch64-linux-gnu-nm','-n',str(elf)],text=True)
assert re.search(r'^0000000040055880 B z_mm_lock$',symbols,re.M)
halt = subprocess.check_output(['aarch64-linux-gnu-addr2line','-e',str(elf),'-f','-C','0x40003234'],text=True)
assert halt.splitlines()[0] == 'arch_system_halt'
report = dict(scope='Hardware reset diagnosis and cache-state counterfactual; no accepted performance samples',
              runs=reports, exception=dict(esr='0x8600000f',ec='0x21',fsc='0xf',fault_symbol='z_mm_lock',
                                          halt_pc='0x40003234',frame=frame,regions=regions,
                                          esr_reference='https://raw.githubusercontent.com/torvalds/linux/master/arch/arm64/include/asm/esr.h'),
              conclusion='Full private-RAM cache maintenance changes reset outcome with identical Guest ELF; temporary probes removed before final validation',
              M1_complete=False,M2_complete=False)
(archive/'results/reset-observations-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print('RESET_OBSERVATIONS_AUDIT_OK same_guest_elf=1 decoded_frame=1 cache_control_suite_pass=1 diagnostic_measurements_accepted=0')
