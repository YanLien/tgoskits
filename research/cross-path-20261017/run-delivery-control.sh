#!/bin/sh
set -eu
cd /home/yanlien/Program/hypervisor/tgoskits
name=${1:?new cohort name required}
case ${2:?control required: ab_fenced, ab_unfenced, memory_fenced} in
    ab_fenced) mode=sgi; fences=1 ;;
    ab_unfenced) mode=sgi; fences=0 ;;
    memory_fenced) mode=off; fences=1 ;;
    *) exit 2 ;;
esac
exec sh research/cross-path-20261017/run-throughput.sh "$name" 250 1048576 "$mode" linux_memory 32 "$fences"
