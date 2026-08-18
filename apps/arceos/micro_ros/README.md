# ArceOS micro-ROS publisher

This experimental C application publishes five `std_msgs/msg/Int32` messages
to `arceos_counter` through a custom UDP transport. The QEMU guest reaches a
micro-ROS Agent on the host at `10.0.2.2:8888`.

The generated Kilted AArch64 client artifacts are intentionally not tracked.
Place them at:

- `c/libmicroros.a`
- `c/libgcc.a`
- `c/include/`

On a host with Clang but without an AArch64 musl cross compiler, provide the
tool names expected by `axbuild`:

```sh
mkdir -p /tmp/arceos-clang-aarch64-micro-ros
ln -sf /usr/bin/clang /tmp/arceos-clang-aarch64-micro-ros/aarch64-linux-musl-gcc
ln -sf /usr/bin/ar /tmp/arceos-clang-aarch64-micro-ros/aarch64-linux-musl-ar
```

Start the Kilted Agent on the host:

```sh
docker run --rm --name arceos-micro-ros-agent --network host \
  microros/micro-ros-agent:kilted udp4 --port 8888 -v4
```

Then run the AArch64 guest from another terminal:

```sh
env PATH="/tmp/arceos-clang-aarch64-micro-ros:$PATH" \
  CCC_OVERRIDE_OPTIONS=+-fno-stack-protector \
  cargo xtask arceos qemu \
  --config apps/arceos/micro_ros/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config apps/arceos/micro_ros/qemu-aarch64.toml
```

Success is reported as `MICRO_ROS_PUBLISH_OK count=5`.
