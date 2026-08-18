#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include <rcl/rcl.h>
#include <rclc/rclc.h>
#include <rmw_microros/custom_transport.h>
#include <rmw_microros/ping.h>
#include <std_msgs/msg/int32.h>
#include <uxr/client/profile/transport/custom/custom_transport.h>

#define AGENT_ADDRESS "10.0.2.2"
#define AGENT_PORT 8888
#define PUBLISH_COUNT 5

struct arceos_udp_transport {
    int socket;
    struct sockaddr_in agent;
};

static bool transport_open(struct uxrCustomTransport *transport)
{
    struct arceos_udp_transport *context = transport->args;

    context->socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (context->socket < 0) {
        return false;
    }
    if (fcntl(context->socket, F_SETFL, O_NONBLOCK) != 0) {
        close(context->socket);
        context->socket = -1;
        return false;
    }

    memset(&context->agent, 0, sizeof(context->agent));
    context->agent.sin_family = AF_INET;
    context->agent.sin_port = htons(AGENT_PORT);
    if (inet_pton(AF_INET, AGENT_ADDRESS, &context->agent.sin_addr) != 1 ||
        connect(context->socket, (struct sockaddr *)&context->agent, sizeof(context->agent)) != 0) {
        close(context->socket);
        context->socket = -1;
        return false;
    }
    return true;
}

static bool transport_close(struct uxrCustomTransport *transport)
{
    struct arceos_udp_transport *context = transport->args;

    if (context->socket >= 0) {
        close(context->socket);
        context->socket = -1;
    }
    return true;
}

static size_t transport_write(struct uxrCustomTransport *transport, const uint8_t *buffer,
                              size_t length, uint8_t *error_code)
{
    struct arceos_udp_transport *context = transport->args;
    ssize_t written = send(context->socket, buffer, length, 0);

    if (written < 0) {
        *error_code = (uint8_t)errno;
        return 0;
    }
    return (size_t)written;
}

static size_t transport_read(struct uxrCustomTransport *transport, uint8_t *buffer, size_t length,
                             int timeout_ms, uint8_t *error_code)
{
    struct arceos_udp_transport *context = transport->args;
    int remaining_ms = timeout_ms;

    do {
        ssize_t received = recv(context->socket, buffer, length, 0);
        if (received >= 0) {
            return (size_t)received;
        }
        if (errno != EAGAIN && errno != EWOULDBLOCK) {
            *error_code = (uint8_t)errno;
            return 0;
        }
        if (remaining_ms > 0) {
            usleep(1000);
        }
    } while (remaining_ms-- > 0);

    return 0;
}

static int report_rcl_error(const char *operation, rcl_ret_t result)
{
    printf("micro-ROS: %s failed: rcl_ret=%d\n", operation, (int)result);
    return 1;
}

int main(void)
{
    struct arceos_udp_transport transport = {.socket = -1};
    rcl_allocator_t allocator = rcl_get_default_allocator();
    rclc_support_t support = {0};
    rcl_node_t node = rcl_get_zero_initialized_node();
    rcl_publisher_t publisher = rcl_get_zero_initialized_publisher();
    std_msgs__msg__Int32 message = {0};
    rcl_ret_t result;

    puts("micro-ROS: configuring ArceOS UDP transport to " AGENT_ADDRESS ":8888");
    if (rmw_uros_set_custom_transport(false, &transport, transport_open, transport_close,
                                      transport_write, transport_read) != RMW_RET_OK) {
        puts("micro-ROS: failed to configure custom transport");
        return 1;
    }
    if (rmw_uros_ping_agent(1000, 5) != RMW_RET_OK) {
        puts("micro-ROS: agent ping failed");
        return 1;
    }
    puts("micro-ROS: agent reachable");

    result = rclc_support_init(&support, 0, NULL, &allocator);
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_support_init", result);
    }
    result = rclc_node_init_default(&node, "arceos_micro_ros", "", &support);
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_node_init_default", result);
    }
    result = rclc_publisher_init_default(
        &publisher, &node, ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, Int32), "arceos_counter");
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_publisher_init_default", result);
    }

    for (int32_t count = 1; count <= PUBLISH_COUNT; ++count) {
        message.data = count;
        result = rcl_publish(&publisher, &message, NULL);
        if (result != RCL_RET_OK) {
            return report_rcl_error("rcl_publish", result);
        }
        printf("micro-ROS: published arceos_counter=%d\n", (int)count);
        sleep(1);
    }

    (void)rcl_publisher_fini(&publisher, &node);
    (void)rcl_node_fini(&node);
    (void)rclc_support_fini(&support);
    transport_close(&(struct uxrCustomTransport){.args = &transport});
    puts("MICRO_ROS_PUBLISH_OK count=5");
    return 0;
}
