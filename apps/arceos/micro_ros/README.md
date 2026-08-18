# ArceOS micro-ROS feature exercise

This AArch64 QEMU application runs micro-ROS Kilted over a custom non-blocking
UDP transport to an Agent at `10.0.2.2:8888`. It exercises the following paths
in one process:

- executor timer and guard condition;
- best-effort publisher `/arceos_counter` and subscriber `/arceos_input`;
- `example_interfaces/srv/AddTwoInts` server `/arceos_add_two_ints` and client
  `/host_add_two_ints`;
- `example_interfaces/action/Fibonacci` server `/arceos_fibonacci` and client
  `/host_fibonacci`, including feedback, result, and cancellation;
- parameter list/get/describe/set services and parameter events;
- all five lifecycle services, transition callbacks, and transition events;
- Agent time synchronization and epoch access.

The Kilted `rclc_lifecycle` helper only registers `get_state`,
`get_available_states`, and `change_state`. This application also registers
`get_available_transitions` and `get_transition_graph`, so the standard
`ros2 lifecycle list/set` commands work.

The final QEMU success marker is:

```text
MICRO_ROS_FEATURES_OK executor=1 guard_condition=1 qos_best_effort=1 subscriber=1 service_server=1 service_client=1 action_server=1 action_client=1 parameter=1 lifecycle=1 time_sync=1
```

## Static client library

Generated AArch64 client artifacts are intentionally not tracked. Place them
at:

- `c/libmicroros.a`
- `c/libgcc.a`
- `c/include/`

The cross-compilation and XRCE capacity settings used for the Kilted library
are recorded in `library_generation/`. The current application needs five
publishers, three subscriptions, fifteen services, four clients, and a history
depth of four. These totals include the action, parameter, and lifecycle
entities created internally by rcl/rclc.

When rebuilding with `microros/micro_ros_static_library_builder:kilted`, pass
`library_generation/aarch64_arceos_toolchain.cmake` and
`library_generation/colcon.meta` to `build_firmware.sh`. Copy
`firmware/build/libmicroros.a` and the generated flattened include tree into
the locations above. `libgcc.a` must come from the same AArch64 GCC toolchain.

## Run

On a host with Clang but without an AArch64 musl cross compiler, provide the
tool names expected by `axbuild`:

```sh
mkdir -p /tmp/arceos-clang-aarch64-micro-ros
ln -sf /usr/bin/clang /tmp/arceos-clang-aarch64-micro-ros/aarch64-linux-musl-gcc
ln -sf /usr/bin/ar /tmp/arceos-clang-aarch64-micro-ros/aarch64-linux-musl-ar
```

Start the Kilted Agent:

```sh
docker run --rm --name arceos-micro-ros-agent --network host --ipc host \
  microros/micro-ros-agent:kilted udp4 --port 8888 -v4
```

`--ipc host` is needed when ROS 2 runs in another container, so Fast DDS
shared-memory traffic works across both containers.

The guest's service and action clients expect host-side servers named
`/host_add_two_ints` and `/host_fibonacci`. Once those are running, launch the
guest:

```sh
env PATH="/tmp/arceos-clang-aarch64-micro-ros:$PATH" \
  CCC_OVERRIDE_OPTIONS=+-fno-stack-protector \
  cargo xtask arceos qemu \
  --config apps/arceos/micro_ros/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config apps/arceos/micro_ros/qemu-aarch64.toml
```

Drive the guest-facing features from ROS 2 Kilted:

```sh
ros2 topic pub --qos-reliability best_effort --times 3 -r 2 \
  /arceos_input std_msgs/msg/Int32 "{data: 42}"

ros2 service call /arceos_add_two_ints \
  example_interfaces/srv/AddTwoInts "{a: 20, b: 22}"

ros2 action send_goal --feedback /arceos_fibonacci \
  example_interfaces/action/Fibonacci "{order: 7}"

ros2 param set /arceos_micro_ros arceos_answer 42

ros2 lifecycle list /arceos_micro_ros
ros2 lifecycle set /arceos_micro_ros configure
ros2 lifecycle set /arceos_micro_ros activate
ros2 lifecycle set /arceos_micro_ros deactivate
ros2 lifecycle set /arceos_micro_ros cleanup
```

The service response must contain `sum=42`; the action must finish with
`SUCCEEDED` and sequence `0, 1, 1, 2, 3, 5, 8`. The application also checks a
successful host service call, one successful host action goal, feedback, and a
second host action goal that it cancels.

## Graph-discovery limitation

`RMW_UXRCE_GRAPH` remains disabled. The Kilted graph profile has upstream
compile defects, and after those are locally corrected the stock Kilted Agent
still does not provide the `ros_to_microros_graph` producer required by the
client. Enabling it makes normal entity initialization stall.

DDS data paths do work without that profile. A best-effort rclpy reader that is
created before the guest writer receives `/arceos_counter` (verified value:
`1`). A later `ros2 topic echo` may wait forever because that CLI first relies
on graph discovery before creating its reader. This is a discovery limitation,
not a publisher transport failure.

## Verified result

The complete AArch64 QEMU run was repeated on 2026-08-18 with a Kilted Agent
and ROS 2 Kilted peers. Every component marker and the final marker above were
observed; QEMU exited through its configured success regex. This demonstrates
the listed rcl/rclc APIs over the AArch64 UDP setup. It is not a claim that
every micro-ROS transport, middleware profile, or graph API is supported.
