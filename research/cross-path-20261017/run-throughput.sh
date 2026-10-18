#!/bin/sh
set -eu
cd /home/yanlien/Program/hypervisor/tgoskits
name=${1:?new cohort name required}
export VIRQ_LINUX_FENCES=${7:-1}
exec sh research/cross-path-20261017/run-periodic.sh "$name" "${2:-20000}" \
  "${3:-4096}" "${4:-off}" "${5:-linux_cpu}" "${6:-32}"
