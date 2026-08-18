# micro-ROS Linux/ArceOS benchmark

This application compares the same micro-ROS C workload on Linux and ArceOS.
The baseline uses a custom UDP transport; ArceOS and AArch64 Linux/QEMU also
share an experimental shared-RAM transport. All modes use reliable QoS, the same XRCE Agent and the
same ROS 2 echo peer. It reports:

- sequential `/benchmark/ping` to `/benchmark/pong` topic round-trip latency;
- sequential `/benchmark/add_two_ints` service round-trip latency;
- rclc executor timer absolute jitter at a 10 ms period.

Each test discards 100 warm-up samples and reports 1,000 measured samples as
minimum, mean, p50, p95, p99 and maximum nanoseconds. Results use one
machine-readable `BENCH_RESULT` line per test.

## Design scope

The benchmark answers whether the micro-ROS client and executor paths differ
between Linux and ArceOS under a controlled workload. It deliberately does not
measure XRCE Agent throughput, DDS discovery time, action latency, power, or
hard real-time guarantees. The ROS 2 Python peer adds constant host-side work;
use the same peer process and host load for both clients. QEMU results measure
the virtual platform and must not be presented as physical-board results.

An independent application was chosen instead of a mode in the feature
exercise because that application creates action, parameter, lifecycle, and
graph entities whose traffic and logging would contaminate latency samples.
The C source is shared with the Linux build so the measured state machine and
statistics remain identical. The feature exercise's already validated custom
UDP adapter and generated message types are reused.

The shared-RAM mode isolates the cost of the guest network path. It removes
`virtio-net`, ax-net, smoltcp and QEMU user networking from the ArceOS build,
but the host bridge still forwards XRCE datagrams over loopback UDP to the
unmodified Agent. It is not a zero-copy DDS implementation.

## Prerequisites

Start the Kilted Agent:

```sh
docker run --rm --name arceos-micro-ros-agent --network host --ipc host \
  microros/micro-ros-agent:kilted udp4 --port 8888 -v4
```

In a ROS 2 Kilted environment, start the common peer before either client:

```sh
python3 apps/arceos/micro_ros_benchmark/benchmark_peer.py
```

## ArceOS AArch64 QEMU

Use the generated AArch64 artifacts from `../micro_ros/c` by linking or copying
its `include`, `libmicroros.a`, and `libgcc.a` into this application's `c`
directory. With the compiler wrappers described by the feature exercise:

```sh
env PATH="/tmp/arceos-clang-aarch64-micro-ros:$PATH" \
  CCC_OVERRIDE_OPTIONS=+-fno-stack-protector \
  cargo xtask arceos qemu \
  --config apps/arceos/micro_ros_benchmark/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config apps/arceos/micro_ros_benchmark/qemu-aarch64.toml
```

## ArceOS shared-RAM transport

The experimental mode stores two single-producer/single-consumer rings in one
page-aligned 3,840-byte area (three 600-byte slots in each direction) in the
guest image and backs QEMU's 256 MiB RAM with a shared host file. A small host
bridge scans that RAM for the versioned ring header, preserves XRCE datagram
boundaries, and forwards packets to the stock UDP Agent. The guest sets a
completion flag so the bridge exits without leaving a polling process behind.

Reuse the generated client artifacts without copying the common source:

```sh
cd apps/arceos/micro_ros_benchmark
ln -sfn ../c/include c_shm/include
ln -sfn ../c/libmicroros.a c_shm/libmicroros.a
ln -sfn ../c/libgcc.a c_shm/libgcc.a
cc -std=c11 -O2 -Wall -Wextra -Werror \
  host/shm_udp_bridge.c -o /tmp/micro_ros_shm_bridge
rm -f /dev/shm/arceos-micro-ros-benchmark.mem
/tmp/micro_ros_shm_bridge
```

Keep the bridge running and launch QEMU from another terminal:

```sh
env PATH="/tmp/arceos-clang-aarch64-micro-ros:$PATH" \
  CCC_OVERRIDE_OPTIONS=+-fno-stack-protector \
  cargo xtask arceos qemu \
  --config apps/arceos/micro_ros_benchmark/build-shm-aarch64-unknown-none-softfloat.toml \
  --qemu-config apps/arceos/micro_ros_benchmark/qemu-shm-aarch64.toml
```

This first implementation deliberately busy-polls both rings while a transport
session is open. ArceOS itself has GIC and architectural timer interrupts
enabled; only this transport lacks a doorbell interrupt. The Linux shared-RAM
client uses the same polling algorithm, so the comparison is transport-fair,
but each client still consumes its guest vCPU and the bridge consumes a host
CPU while active. Report CPU consumption beside latency. The RAM backend also
exposes the entire benchmark VM memory to the host file; it is suitable for
controlled QEMU experiments, not a security boundary. A production board
should reserve a dedicated coherent RAM window and add a doorbell interrupt.

## Linux native

Generate an x86_64 micro-ROS static library with the custom UDP transport and
the settings in `library_generation/linux-colcon.meta` and
`library_generation/linux_toolchain.cmake`. Point `MICROROS_PREFIX` directly
at the generated `firmware/build` directory, then build and run:

```sh
cmake -S apps/arceos/micro_ros_benchmark/linux \
  -B apps/arceos/micro_ros_benchmark/linux/build \
  -DMICROROS_PREFIX=/path/to/microros-prefix
cmake --build apps/arceos/micro_ros_benchmark/linux/build --parallel
apps/arceos/micro_ros_benchmark/linux/build/micro_ros_benchmark
```

The Kilted builder snapshot used on 2026-08-18 needed two workarounds. Its
`create_firmware_ws.sh generate_lib` bootstrap also selected
`rmw_test_fixture`; placing `COLCON_IGNORE` in
`firmware/dev_ws/ros2/ament_cmake_ros/rmw_test_fixture/` allowed the documented
dev workspace build to finish. Its final archive aggregation included host
Fast RTPS typesupport even though the client profile requests one typesupport.
The verified Linux library was copied and filtered before linking:

```sh
mkdir -p /tmp/microros-linux
cp firmware/build/libmicroros.a /tmp/microros-linux/libmicroros.a
cp -a firmware/build/include /tmp/microros-linux/include
cd /tmp/microros-linux
ar t libmicroros.a | grep fastrtps | xargs ar d libmicroros.a
ranlib libmicroros.a
```

The benchmark calls the generated `rosidl_typesupport_microxrcedds_c` symbols
directly, so those Fast RTPS objects are neither required nor part of the
measured client path. Keep the unmodified generated archive and perform this
operation only on a copy.

The Linux build changes only the platform label and Agent address
(`127.0.0.1` instead of QEMU's `10.0.2.2`). Compile-time definitions can
override sample counts, timer period, Agent address, and port for controlled
experiments; every compared run must use the same values.

## Linux AArch64 QEMU

For an architecture-matched comparison, boot an AArch64 Linux kernel and
rootfs with the same virtual CPU, memory, network device, and QEMU user network
as `qemu-aarch64.toml`:

```sh
qemu-system-aarch64 \
  -machine virt,gic-version=3 -cpu cortex-a72 -smp 1 -m 256M \
  -kernel /path/to/arm64/Image \
  -append 'console=ttyAMA0 root=/dev/vda rw init=/bin/sh' \
  -drive if=none,file=/path/to/aarch64-rootfs.img,format=raw,id=rootfs \
  -device virtio-blk-pci,drive=rootfs \
  -device virtio-net-pci,netdev=net0 \
  -netdev user,id=net0 -display none -serial mon:stdio
```

Configure the guest network with DHCP and build the shared source against the
same AArch64 `libmicroros.a` used by ArceOS. `compat.c` supplies the GNU libc
compatibility symbols referenced by that archive when the guest uses musl:

```sh
ip link set eth0 up
udhcpc -i eth0 -q
gcc -std=gnu11 -O2 -Wall -Wextra -Werror \
  -DBENCHMARK_PLATFORM='"linux-aarch64-qemu"' \
  -DBENCHMARK_AGENT_ADDRESS='"10.0.2.2"' \
  -Iinclude c/main.c c/compat.c libmicroros.a \
  -lpthread -lrt -lm -o micro_ros_benchmark
./micro_ros_benchmark
```

The CMake build exposes `BENCHMARK_PLATFORM` and `BENCHMARK_AGENT_ADDRESS` as
cache variables for equivalent cross-build environments.

### Linux AArch64 shared-RAM mode

Build `linux_shm/main.c` and `linux_shm/compat.c` against the same AArch64
headers and archive, then place the binary in the guest rootfs. Back the full
guest RAM with a shared file and disable emulated networking:

```sh
rm -f /dev/shm/linux-micro-ros-benchmark.mem
/tmp/micro_ros_shm_bridge /dev/shm/linux-micro-ros-benchmark.mem

qemu-system-aarch64 \
  -machine virt,gic-version=3,memory-backend=shmram \
  -object memory-backend-file,id=shmram,size=256M,\
mem-path=/dev/shm/linux-micro-ros-benchmark.mem,share=on \
  -m 256M -cpu cortex-a72 -smp 1 -nic none \
  -kernel /path/to/arm64/Image \
  -append 'console=ttyAMA0 root=/dev/vda rw init=/bin/sh' \
  -drive if=none,file=/path/to/aarch64-rootfs.img,format=raw,id=rootfs \
  -device virtio-blk-device,drive=rootfs \
  -display none -monitor none -serial stdio -no-reboot
```

Use `-monitor none -serial stdio` for scripted guest input. With
`-serial mon:stdio`, QEMU's monitor/serial multiplexer can consume the command
intended for the guest shell.

Example output:

```text
BENCH_RESULT platform=arceos test=topic_rtt qos=reliable samples=1000 min_ns=... mean_ns=... p50_ns=... p95_ns=... p99_ns=... max_ns=... failures=0
BENCH_RESULT platform=arceos test=service_rtt qos=reliable samples=1000 min_ns=... mean_ns=... p50_ns=... p95_ns=... p99_ns=... max_ns=... failures=0
BENCH_RESULT platform=arceos test=executor_timer_jitter qos=reliable samples=1000 min_ns=... mean_ns=... p50_ns=... p95_ns=... p99_ns=... max_ns=... failures=0
MICRO_ROS_BENCHMARK_OK platform=arceos tests=3 samples=1000
```

For publishable comparisons, repeat each complete run, record host CPU load,
Agent version, client library commit, QEMU/board model, compiler flags, and
report the run-to-run spread rather than only the best run.

The architecture-matched UDP and shared-RAM smoke results are recorded in
`results/2026-08-18-qemu-aarch64-vs-linux.md`.
