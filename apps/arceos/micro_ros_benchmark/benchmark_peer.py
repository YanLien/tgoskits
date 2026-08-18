#!/usr/bin/env python3
"""ROS 2 echo peer used by both Linux and ArceOS benchmark clients."""

import rclpy
from example_interfaces.srv import AddTwoInts
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_services_default,
)
from std_msgs.msg import Int32


class BenchmarkPeer(Node):
    def __init__(self) -> None:
        super().__init__("micro_ros_benchmark_peer")
        reliable_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._publisher = self.create_publisher(Int32, "/benchmark/pong", reliable_qos)
        self._subscription = self.create_subscription(
            Int32,
            "/benchmark/ping",
            self._echo_ping,
            reliable_qos,
        )
        self._service = self.create_service(
            AddTwoInts,
            "/benchmark/add_two_ints",
            self._add_two_ints,
            qos_profile=qos_profile_services_default,
        )

    def _echo_ping(self, message: Int32) -> None:
        self._publisher.publish(message)

    @staticmethod
    def _add_two_ints(
        request: AddTwoInts.Request, response: AddTwoInts.Response
    ) -> AddTwoInts.Response:
        response.sum = request.a + request.b
        return response


def main() -> None:
    rclpy.init()
    peer = BenchmarkPeer()
    peer.get_logger().info("benchmark peer ready")
    try:
        rclpy.spin(peer)
    finally:
        peer.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
