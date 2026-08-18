# ArceOS micro-ROS feature test

This AArch64 QEMU application exercises micro-ROS Kilted through a custom
non-blocking UDP transport. The guest connects to a micro-ROS Agent on the host
at `10.0.2.2:8888` and covers these `rclc` paths:

- executor-driven timer publishing five `std_msgs/msg/Int32` samples on
  `/arceos_counter`;
- subscription to `/arceos_input`, expecting the value `42`;
- `example_interfaces/srv/AddTwoInts` service at `/arceos_add_two_ints`;
- `example_interfaces/action/Fibonacci` action server at
  `/arceos_fibonacci`, including feedback and result delivery.

The final QEMU success marker is:

```text
MICRO_ROS_FEATURES_OK executor=1 subscriber=1 service=1 action=1
```

## Static client library

The generated AArch64 client artifacts are intentionally not tracked. Place
them at:

- `c/libmicroros.a`
- `c/libgcc.a`
- `c/include/`

The exact cross-compilation and XRCE entity-capacity settings used for the
Kilted library are recorded in `library_generation/`. In particular, the
library reserves three publishers, one subscription, four services and a
history depth of four. The action server consumes two publishers and three
service/replier slots in addition to the application publisher and service.

When rebuilding with `microros/micro_ros_static_library_builder:kilted`, pass
`library_generation/aarch64_arceos_toolchain.cmake` and
`library_generation/colcon.meta` to `build_firmware.sh`. Copy
`firmware/build/libmicroros.a` and the generated flattened include tree into
the locations above. `libgcc.a` must come from the same AArch64 GCC toolchain.

## Run the guest

On a host with Clang but without an AArch64 musl cross compiler, provide the
tool names expected by `axbuild`:

```sh
mkdir -p /tmp/arceos-clang-aarch64-micro-ros
ln -sf /usr/bin/clang /tmp/arceos-clang-aarch64-micro-ros/aarch64-linux-musl-gcc
ln -sf /usr/bin/ar /tmp/arceos-clang-aarch64-micro-ros/aarch64-linux-musl-ar
```

Start the Kilted Agent on the host:

```sh
docker run --rm --name arceos-micro-ros-agent --network host --ipc host \
  microros/micro-ros-agent:kilted udp4 --port 8888 -v4
```

`--ipc host` is needed when the ROS 2 CLI below runs in another container so
that Fast DDS shared-memory traffic works across the two containers.

Then run the AArch64 guest from another terminal:

```sh
env PATH="/tmp/arceos-clang-aarch64-micro-ros:$PATH" \
  CCC_OVERRIDE_OPTIONS=+-fno-stack-protector \
  cargo xtask arceos qemu \
  --config apps/arceos/micro_ros/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config apps/arceos/micro_ros/qemu-aarch64.toml
```

## Drive the feature test

Use a ROS 2 Kilted environment with `example_interfaces` installed:

```sh
ros2 topic pub --times 3 -r 2 --keep-alive 2 \
  /arceos_input std_msgs/msg/Int32 "{data: 42}"

ros2 service call /arceos_add_two_ints \
  example_interfaces/srv/AddTwoInts "{a: 20, b: 22}"

ros2 action send_goal --feedback /arceos_fibonacci \
  example_interfaces/action/Fibonacci "{order: 7}"
```

The service response must contain `sum=42`; the accepted action must finish
with `SUCCEEDED` and the sequence `0, 1, 1, 2, 3, 5, 8`.

## Verified result

The complete AArch64 QEMU test was run on 2026-08-18 with a Kilted Agent and
ROS 2 Kilted CLI. It produced all four component markers and the final success
marker above. This demonstrates the tested executor, subscriber, service and
action-server paths; it is not a claim that every micro-ROS API or transport is
supported.
