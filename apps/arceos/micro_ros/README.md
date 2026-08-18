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
- Agent time synchronization and epoch access;
- a delayed, one-snapshot `RMW_UXRCE_GRAPH` cache and `rcl_get_node_names()`
  query.

The Kilted `rclc_lifecycle` helper only registers `get_state`,
`get_available_states`, and `change_state`. This application also registers
`get_available_transitions` and `get_transition_graph`, so the standard
`ros2 lifecycle list/set` commands work.

The final QEMU success marker is:

```text
MICRO_ROS_FEATURES_OK executor=1 guard_condition=1 qos_best_effort=1 subscriber=1 service_server=1 service_client=1 action_server=1 action_client=1 parameter=1 lifecycle=1 time_sync=1 graph=1
```

## Static client library

Generated AArch64 client artifacts are intentionally not tracked. Place them
at:

- `c/libmicroros.a`
- `c/libgcc.a`
- `c/include/`

The cross-compilation and XRCE capacity settings used for the Kilted library
are recorded in `library_generation/`. The current application needs five
publishers, three subscriptions, fifteen services, four clients, an entity
history depth of four, and a 256-message reliable input stream for the graph
snapshot. These totals include the action, parameter, and lifecycle entities
created internally by rcl/rclc.

Before building, apply
`library_generation/patches/rmw_microxrcedds-kilted-graph.patch` to the Kilted
`rmw_microxrcedds` checkout. It contains the Kilted graph compile/query fixes
and the delayed one-snapshot delivery API used by this application.

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
`/host_add_two_ints` and `/host_fibonacci`. Also start the best-effort
publisher before the guest so DDS matching is complete when its subscription
is created. Stop the publisher after the final marker:

```sh
ros2 topic pub --qos-reliability best_effort -r 2 \
  /arceos_input std_msgs/msg/Int32 "{data: 42}"
```

Once those peers are running, launch the guest:

```sh
env PATH="/tmp/arceos-clang-aarch64-micro-ros:$PATH" \
  CCC_OVERRIDE_OPTIONS=+-fno-stack-protector \
  cargo xtask arceos qemu \
  --config apps/arceos/micro_ros/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config apps/arceos/micro_ros/qemu-aarch64.toml
```

Drive the remaining guest-facing features from ROS 2 Kilted:

```sh
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

## Graph-discovery support and limitation

`RMW_UXRCE_GRAPH` is enabled with the recorded downstream Kilted patch. The
stock Kilted Agent creates a reliable, transient-local
`ros_to_microros_graph` writer. The patch fixes invalid context and string
buffer handling in the Kilted client, creates the graph DDS entities during
RMW initialization, and delays `REQUEST_DATA` until all application entities
and executor handles exist.

Delivery is deliberately limited to one complete snapshot. In the reproduced
setup, a graph was about 64 KiB, or roughly 129 508-byte XRCE fragments.
Requesting unlimited updates during startup stalled entity creation; leaving
updates enabled at runtime let short-lived ROS CLI nodes generate several full
snapshots and overrun the reliable stream's retained window. A 256-message
input history plus delayed, single-sample delivery produced a valid cache, and
`rcl_get_node_names()` returned discovered nodes before the rest of the feature
exercise completed successfully.

The remaining limitation is freshness: this integration provides an initial
graph snapshot, not a continuously updated client-side cache. Host ROS 2 graph
discovery through the Agent remains live, so standard `ros2 topic`, `service`,
`action`, `param`, and `lifecycle` commands discover the guest normally. No
upstream issue matching the exact full-snapshot XRCE failure was found as of
2026-08-18.

## Verified result

The complete AArch64 QEMU run was repeated on 2026-08-18 with a Kilted Agent
and ROS 2 Kilted peers. Every component marker, `MICRO_ROS_GRAPH_OK`, and the
final marker above were observed; QEMU exited through its configured success
regex. This demonstrates the listed rcl/rclc APIs and the initial graph query
over the AArch64 UDP setup. It is not a claim that every micro-ROS transport,
middleware profile, graph query, or continuous graph-update mode is supported.
