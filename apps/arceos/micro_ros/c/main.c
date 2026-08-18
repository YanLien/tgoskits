#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include <example_interfaces/action/fibonacci.h>
#include <example_interfaces/srv/add_two_ints.h>
#include <rcl/rcl.h>
#include <rclc/executor.h>
#include <rclc/rclc.h>
#include <rclc/timer.h>
#include <rmw_microros/custom_transport.h>
#include <rmw_microros/ping.h>
#include <std_msgs/msg/int32.h>
#include <uxr/client/profile/transport/custom/custom_transport.h>

#define AGENT_ADDRESS "10.0.2.2"
#define AGENT_PORT 8888
#define EXPECTED_VALUE 42
#define FIBONACCI_ORDER 7
#define PUBLISH_COUNT 5

struct arceos_udp_transport {
    int socket;
    struct sockaddr_in agent;
};

static rcl_publisher_t counter_publisher;
static std_msgs__msg__Int32 counter_message;
static volatile bool timer_ok;
static volatile bool subscriber_ok;
static volatile bool service_ok;
static bool action_ok;
static pthread_mutex_t action_state_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_t action_worker;
static bool action_worker_started;

static bool action_succeeded(void)
{
    bool succeeded;

    (void)pthread_mutex_lock(&action_state_mutex);
    succeeded = action_ok;
    (void)pthread_mutex_unlock(&action_state_mutex);
    return succeeded;
}

static void mark_action_succeeded(void)
{
    (void)pthread_mutex_lock(&action_state_mutex);
    action_ok = true;
    (void)pthread_mutex_unlock(&action_state_mutex);
}

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

static void timer_callback(rcl_timer_t *timer, int64_t last_call_time)
{
    (void)last_call_time;
    if (timer == NULL || timer_ok) {
        return;
    }

    ++counter_message.data;
    if (rcl_publish(&counter_publisher, &counter_message, NULL) != RCL_RET_OK) {
        puts("micro-ROS: timer publish failed");
        return;
    }
    printf("micro-ROS: timer published arceos_counter=%d\n", (int)counter_message.data);
    if (counter_message.data == PUBLISH_COUNT) {
        timer_ok = true;
        puts("MICRO_ROS_EXECUTOR_TIMER_OK count=5");
    }
}

static void subscription_callback(const void *message)
{
    const std_msgs__msg__Int32 *input = message;

    printf("micro-ROS: subscriber received arceos_input=%d\n", (int)input->data);
    if (input->data == EXPECTED_VALUE) {
        subscriber_ok = true;
        puts("MICRO_ROS_SUBSCRIBER_OK data=42");
    }
}

static void service_callback(const void *request_message, void *response_message)
{
    const example_interfaces__srv__AddTwoInts_Request *request = request_message;
    example_interfaces__srv__AddTwoInts_Response *response = response_message;

    response->sum = request->a + request->b;
    printf("micro-ROS: AddTwoInts %lld + %lld = %lld\n", (long long)request->a,
           (long long)request->b, (long long)response->sum);
    if (response->sum == EXPECTED_VALUE) {
        service_ok = true;
        puts("MICRO_ROS_SERVICE_OK sum=42");
    }
}

static void *fibonacci_worker(void *argument)
{
    rclc_action_goal_handle_t *goal_handle = argument;
    example_interfaces__action__Fibonacci_SendGoal_Request *request =
        (example_interfaces__action__Fibonacci_SendGoal_Request *)goal_handle->ros_goal_request;
    example_interfaces__action__Fibonacci_FeedbackMessage feedback = {0};
    example_interfaces__action__Fibonacci_GetResult_Response response = {0};
    size_t order = (size_t)request->goal.order;
    int32_t *sequence = calloc(order, sizeof(*sequence));

    if (sequence == NULL) {
        (void)rclc_action_send_result(goal_handle, GOAL_STATE_ABORTED, &response);
        return NULL;
    }

    sequence[0] = 0;
    sequence[1] = 1;
    feedback.feedback.sequence.data = sequence;
    feedback.feedback.sequence.capacity = order;
    feedback.feedback.sequence.size = 2;

    for (size_t index = 2; index < order && !goal_handle->goal_cancelled; ++index) {
        sequence[index] = sequence[index - 1] + sequence[index - 2];
        feedback.feedback.sequence.size = index + 1;
        (void)rclc_action_publish_feedback(goal_handle, &feedback);
        usleep(10000);
    }

    response.result.sequence.data = sequence;
    response.result.sequence.capacity = order;
    response.result.sequence.size = feedback.feedback.sequence.size;

    rcl_ret_t result;
    do {
        result = rclc_action_send_result(
            goal_handle, goal_handle->goal_cancelled ? GOAL_STATE_CANCELED : GOAL_STATE_SUCCEEDED,
            &response);
        if (result != RCL_RET_OK) {
            usleep(10000);
        }
    } while (result == RCLC_RET_ACTION_WAIT_RESULT_REQUEST);

    if (result == RCL_RET_OK && !goal_handle->goal_cancelled && order == FIBONACCI_ORDER &&
        sequence[order - 1] == 8) {
        mark_action_succeeded();
        puts("MICRO_ROS_ACTION_OK order=7 last=8");
    }
    free(sequence);
    return NULL;
}

static rcl_ret_t action_goal_callback(rclc_action_goal_handle_t *goal_handle, void *context)
{
    (void)context;
    example_interfaces__action__Fibonacci_SendGoal_Request *request =
        (example_interfaces__action__Fibonacci_SendGoal_Request *)goal_handle->ros_goal_request;

    if (request->goal.order != FIBONACCI_ORDER) {
        printf("micro-ROS: rejected Fibonacci order=%d\n", (int)request->goal.order);
        return RCL_RET_ACTION_GOAL_REJECTED;
    }

    if (pthread_create(&action_worker, NULL, fibonacci_worker, goal_handle) != 0) {
        return RCL_RET_ACTION_GOAL_REJECTED;
    }
    action_worker_started = true;
    puts("micro-ROS: accepted Fibonacci order=7");
    return RCL_RET_ACTION_GOAL_ACCEPTED;
}

static bool action_cancel_callback(rclc_action_goal_handle_t *goal_handle, void *context)
{
    (void)goal_handle;
    (void)context;
    return true;
}

int main(void)
{
    struct arceos_udp_transport transport = {.socket = -1};
    rcl_allocator_t allocator = rcl_get_default_allocator();
    rclc_support_t support = {0};
    rcl_node_t node = rcl_get_zero_initialized_node();
    rcl_publisher_t publisher = rcl_get_zero_initialized_publisher();
    rcl_subscription_t subscription = rcl_get_zero_initialized_subscription();
    rcl_service_t service = rcl_get_zero_initialized_service();
    rcl_timer_t timer = rcl_get_zero_initialized_timer();
    rclc_executor_t executor = rclc_executor_get_zero_initialized_executor();
    rclc_action_server_t action_server = {0};
    std_msgs__msg__Int32 subscription_message = {0};
    example_interfaces__srv__AddTwoInts_Request service_request = {0};
    example_interfaces__srv__AddTwoInts_Response service_response = {0};
    example_interfaces__action__Fibonacci_SendGoal_Request action_requests[1] = {0};
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
    counter_publisher = publisher;
    result = rclc_subscription_init_default(
        &subscription, &node, ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, Int32), "arceos_input");
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_subscription_init_default", result);
    }
    result = rclc_service_init_default(
        &service, &node, ROSIDL_GET_SRV_TYPE_SUPPORT(example_interfaces, srv, AddTwoInts),
        "arceos_add_two_ints");
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_service_init_default", result);
    }
    result = rclc_action_server_init_default(
        &action_server, &node, &support,
        ROSIDL_GET_ACTION_TYPE_SUPPORT(example_interfaces, Fibonacci), "arceos_fibonacci");
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_action_server_init_default", result);
    }
    result = rclc_timer_init_default2(&timer, &support, RCL_MS_TO_NS(500), timer_callback, true);
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_timer_init_default2", result);
    }

    result = rclc_executor_init(&executor, &support.context, 4, &allocator);
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_executor_init", result);
    }
    if ((result = rclc_executor_add_timer(&executor, &timer)) != RCL_RET_OK) {
        return report_rcl_error("rclc_executor_add_timer", result);
    }
    if ((result = rclc_executor_add_subscription(&executor, &subscription, &subscription_message,
                                                 subscription_callback,
                                                 ON_NEW_DATA)) != RCL_RET_OK) {
        return report_rcl_error("rclc_executor_add_subscription", result);
    }
    if ((result = rclc_executor_add_service(&executor, &service, &service_request,
                                            &service_response, service_callback)) != RCL_RET_OK) {
        return report_rcl_error("rclc_executor_add_service", result);
    }
    if ((result = rclc_executor_add_action_server(
             &executor, &action_server, 1, action_requests, sizeof(action_requests[0]),
             action_goal_callback, action_cancel_callback, &action_server)) != RCL_RET_OK) {
        return report_rcl_error("rclc_executor_add_action_server", result);
    }

    puts("MICRO_ROS_FEATURES_READY");
    while (!(timer_ok && subscriber_ok && service_ok && action_succeeded())) {
        result = rclc_executor_spin_some(&executor, RCL_MS_TO_NS(10));
        if (result != RCL_RET_OK && result != RCL_RET_TIMEOUT) {
            return report_rcl_error("rclc_executor_spin_some", result);
        }
        usleep(10000);
    }

    puts("MICRO_ROS_FEATURES_OK executor=1 subscriber=1 service=1 action=1");
    if (action_worker_started) {
        (void)pthread_join(action_worker, NULL);
    }
    (void)rclc_executor_fini(&executor);
    (void)rcl_timer_fini(&timer);
    (void)rclc_action_server_fini(&action_server, &node);
    (void)rcl_service_fini(&service, &node);
    (void)rcl_subscription_fini(&subscription, &node);
    (void)rcl_publisher_fini(&publisher, &node);
    (void)rcl_node_fini(&node);
    (void)rclc_support_fini(&support);
    transport_close(&(struct uxrCustomTransport){.args = &transport});
    return 0;
}
