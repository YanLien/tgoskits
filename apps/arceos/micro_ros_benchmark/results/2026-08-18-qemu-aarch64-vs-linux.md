# AArch64 Linux QEMU and ArceOS QEMU baseline, 2026-08-18

This is a single-run smoke baseline, not a performance claim for physical
hardware. Both clients used the Kilted Agent and the same Kilted rclpy peer on
the same host, reliable QoS, 100 discarded warm-up samples, 1,000 measured
samples, and a 10 ms executor timer period.

> The UDP and ArceOS-only shared-RAM numbers below are retained as historical
> integration baselines. The repeated, like-for-like shared-RAM comparison at
> the end supersedes them for Linux-versus-ArceOS transport comparisons.

| Test | Linux/QEMU mean | ArceOS/QEMU mean | ArceOS/QEMU delta |
| --- | ---: | ---: | ---: |
| Topic RTT | 739.434 us | 1,199.416 us | +62.2% (1.62x) |
| Service RTT | 758.092 us | 1,198.071 us | +58.0% (1.58x) |
| Executor timer absolute jitter | 30.579 us | 73.715 us | +141.1% (2.41x) |

Exact final output:

```text
BENCH_RESULT platform=linux-aarch64-qemu test=topic_rtt qos=reliable samples=1000 min_ns=549728 mean_ns=739434 p50_ns=728448 p95_ns=820784 p99_ns=881536 max_ns=6735104 failures=0
BENCH_RESULT platform=linux-aarch64-qemu test=service_rtt qos=reliable samples=1000 min_ns=576032 mean_ns=758092 p50_ns=749760 p95_ns=850352 p99_ns=934064 max_ns=1965104 failures=0
BENCH_RESULT platform=linux-aarch64-qemu test=executor_timer_jitter qos=reliable samples=1000 min_ns=0 mean_ns=30579 p50_ns=11968 p95_ns=165040 p99_ns=287632 max_ns=528656 failures=0
MICRO_ROS_BENCHMARK_OK platform=linux-aarch64-qemu tests=3 samples=1000

BENCH_RESULT platform=arceos test=topic_rtt qos=reliable samples=1000 min_ns=1160768 mean_ns=1199416 p50_ns=1197536 p95_ns=1227840 p99_ns=1252256 max_ns=2303152 failures=0
BENCH_RESULT platform=arceos test=service_rtt qos=reliable samples=1000 min_ns=1162816 mean_ns=1198071 p50_ns=1198608 p95_ns=1227344 p99_ns=1251456 max_ns=1281104 failures=0
BENCH_RESULT platform=arceos test=executor_timer_jitter qos=reliable samples=1000 min_ns=16 mean_ns=73715 p50_ns=90272 p95_ns=141280 p99_ns=215024 max_ns=441760 failures=0
MICRO_ROS_BENCHMARK_OK platform=arceos tests=3 samples=1000
```

Environment:

- both guests: AArch64 `virt,gic-version=3`, Cortex-A72, one vCPU, 256 MiB,
  `virtio-net-pci`, and QEMU user networking;
- Linux: Linux 5.4.0 `PREEMPT`, Alpine/musl rootfs;
- ArceOS: the benchmark's release AArch64 QEMU image;
- Agent: `microros/micro-ros-agent:kilted`, UDP port 8888;
- peer: ROS 2 Kilted `rclpy`, `benchmark_peer.py`;
- client library: the same generated AArch64 `libmicroros.a` archive;
- benchmark source: shared `c/main.c`; Linux application uses `-O2`, while
  axbuild's release C application uses `-O3` for ArceOS.

The custom transport retries a non-blocking receive with `usleep(1000)` when no
packet is ready. On ArceOS, the measured RTT distribution stays close to that
one-millisecond polling quantum. Linux often observes the response before a
retry and therefore has a lower median. This result compares the current
integrated transport, scheduler, timer, and network stacks; it is not the
minimum possible UDP latency. The Linux topic maximum is also a single-run
outlier, so repeated trials and a physical-board run are required before
drawing deployment-level conclusions.

## Transport follow-up

After implementing blocking socket timeouts in ArceOS, the same UDP workload
gave the following RTT means. The Linux timer value from that follow-up is not
reported because Linux 5.4 rounded the one-millisecond receive timeout to its
timer tick and contaminated the executor timer phase.

| Test | Linux/QEMU UDP mean | ArceOS/QEMU UDP mean | ArceOS delta |
| --- | ---: | ---: | ---: |
| Topic RTT | 766.969 us | 816.236 us | +6.4% |
| Service RTT | 772.049 us | 845.567 us | +9.5% |

The experimental shared-RAM mode then removed `virtio-net`, ax-net, smoltcp,
and QEMU user networking from the ArceOS guest. The bridge and guest both used
busy polling, while the bridge forwarded complete XRCE datagrams to the same
stock Agent over host loopback UDP.

| Test | ArceOS shared-RAM mean | Versus Linux UDP | Versus ArceOS UDP |
| --- | ---: | ---: | ---: |
| Topic RTT | 141.498 us | 5.42x faster | 5.77x faster |
| Service RTT | 122.002 us | 6.33x faster | 6.93x faster |
| Executor timer absolute jitter | 1.323 us | not compared | 6.09x lower |

Exact shared-RAM output:

```text
BENCH_RESULT platform=arceos test=topic_rtt qos=reliable samples=1000 min_ns=101856 mean_ns=141498 p50_ns=155840 p95_ns=182016 p99_ns=190128 max_ns=293200 failures=0
BENCH_RESULT platform=arceos test=service_rtt qos=reliable samples=1000 min_ns=109040 mean_ns=122002 p50_ns=120064 p95_ns=138000 p99_ns=169760 max_ns=228480 failures=0
BENCH_RESULT platform=arceos test=executor_timer_jitter qos=reliable samples=1000 min_ns=0 mean_ns=1323 p50_ns=1104 p95_ns=3200 p99_ns=3952 max_ns=4640 failures=0
MICRO_ROS_BENCHMARK_OK platform=arceos tests=3 samples=1000
```

This result demonstrates that the guest network path dominated the earlier
end-to-end measurement. It does not establish an equal-resource win over
Linux: the shared-RAM mode consumes polling CPUs, while the UDP mode blocks and
wakes. A fair production comparison needs equivalent shared-memory transports,
CPU utilization, repeated runs, and preferably a physical coherent-memory
window with doorbell interrupts on both systems.

## Repeated like-for-like shared-RAM comparison, 2026-08-19

Linux and ArceOS used the same page-sized shared-memory protocol, bridge,
generated AArch64 client archive, Agent, peer, Cortex-A72 QEMU CPU model, one
vCPU, reliable QoS, 100 warm-up samples, and 1,000 measured samples. Each ring
direction had three 600-byte slots. Neither guest used an emulated network
device. Both transports busy-polled and had no doorbell interrupt.

The host pinned QEMU, bridge, Agent, and peer to separate logical CPUs 2, 3, 4,
and 5 respectively. The Agent was restarted and allowed four seconds to warm
up before every run. Stale bridge processes were removed before collecting
these three alternating ArceOS/Linux pairs.

The table reports the median of the three per-run means. The range is the
minimum and maximum per-run mean; it makes the Linux third-run tail event
visible instead of selecting only the best run.

| Test | ArceOS median mean (range) | Linux median mean (range) | ArceOS delta |
| --- | ---: | ---: | ---: |
| Topic RTT | 128.982 us (124.705–139.342) | 144.541 us (128.326–263.525) | -10.8% |
| Service RTT | 134.272 us (131.010–159.318) | 149.190 us (136.247–253.691) | -10.0% |
| Executor timer absolute jitter | 1.165 us (1.147–1.198) | 0.943 us (0.925–0.961) | +23.5% |

Per-run means and tail percentiles:

```text
ArceOS run 1: topic mean=139342 p95=191024 p99=220960; service mean=131010 p95=184208 p99=189584; jitter mean=1147 p95=2640 p99=3152 ns
Linux  run 1: topic mean=128326 p95=178928 p99=195008; service mean=136247 p95=181504 p99=198512; jitter mean=961 p95=2224 p99=2608 ns
ArceOS run 2: topic mean=128982 p95=179824 p99=185120; service mean=134272 p95=180288 p99=184880; jitter mean=1165 p95=2704 p99=3104 ns
Linux  run 2: topic mean=144541 p95=214208 p99=242480; service mean=149190 p95=212160 p99=241968; jitter mean=943 p95=2096 p99=2464 ns
ArceOS run 3: topic mean=124705 p95=177184 p99=183312; service mean=159318 p95=182560 p99=191680; jitter mean=1198 p95=2720 p99=3088 ns
Linux  run 3: topic mean=263525 p95=276736 p99=2974864; service mean=253691 p95=265200 p99=2954800; jitter mean=925 p95=2192 p99=2672 ns
```

The result is close rather than a categorical unikernel win: ArceOS has about
10% lower median-of-run-mean RTT, while Linux has lower timer jitter. Linux's
third run also shows roughly 3 ms p99 topic/service outliers. This benchmark
does not measure CPU efficiency because polling intentionally keeps one guest
vCPU and one bridge CPU runnable. A deployment-quality transport should replace
polling with a board-specific doorbell interrupt and then compare latency,
tail latency, throughput, and CPU utilization on physical hardware.
