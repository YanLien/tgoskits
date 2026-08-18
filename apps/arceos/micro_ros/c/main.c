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
#include <lifecycle_msgs/msg/transition.h>
#include <lifecycle_msgs/msg/transition_description.h>
#include <lifecycle_msgs/srv/get_available_transitions.h>
#include <rcl/rcl.h>
#include <rcl/graph.h>
#include <rclc/executor.h>
#include <rclc/rclc.h>
#include <rclc/timer.h>
#include <rclc_lifecycle/rclc_lifecycle.h>
#include <rclc_parameter/rclc_parameter.h>
#include <rmw_microros/custom_transport.h>
#include <rmw_microros/ping.h>
#include <rmw_microros/rmw_microros.h>
#include <rmw_microros/time_sync.h>
#include <rcutils/types/string_array.h>
#include <rosidl_runtime_c/string_functions.h>
#include <std_msgs/msg/int32.h>
#include <uxr/client/profile/transport/custom/custom_transport.h>

#define AGENT_ADDRESS "10.0.2.2"
#define AGENT_PORT 8888
#define EXPECTED_VALUE 42
#define FIBONACCI_ORDER 7
#define PUBLISH_COUNT 20
#define SERVICE_CLIENT_A 19
#define SERVICE_CLIENT_B 23
#define ACTION_CLIENT_SUCCESS_ORDER 5
#define ACTION_CLIENT_CANCEL_ORDER 10
#define ACTION_CLIENT_SEQUENCE_CAPACITY 16
#define LIFECYCLE_LABEL_CAPACITY 32

struct arceos_udp_transport {
    int socket;
    struct sockaddr_in agent;
};

struct lifecycle_transitions_context {
    rclc_lifecycle_node_t *lifecycle_node;
    bool full_graph;
};

static rcl_publisher_t counter_publisher;
static std_msgs__msg__Int32 counter_message;
static volatile bool timer_ok;
static volatile bool subscriber_ok;
static volatile bool service_ok;
static volatile bool service_client_ok;
static bool action_ok;
static pthread_mutex_t action_state_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_t action_worker;
static bool action_worker_started;
static rclc_action_client_t host_action_client;
static example_interfaces__action__Fibonacci_SendGoal_Request action_client_requests[2];
static bool action_client_feedback_ok;
static bool action_client_result_ok;
static bool action_client_cancel_accepted;
static bool action_client_cancel_result_ok;
static bool action_client_second_goal_sent;
static bool action_client_cancel_requested;
static bool action_client_ok;
static rclc_parameter_server_t parameter_server;
static bool parameter_ok;
static bool lifecycle_configure_ok;
static bool lifecycle_activate_ok;
static bool lifecycle_deactivate_ok;
static bool lifecycle_ok;
static bool time_sync_ok;
static bool guard_condition_ok;
static bool graph_ok;

static rcl_ret_t update_graph_status(const rcl_node_t *node, rcl_allocator_t allocator)
{
    if (graph_ok) {
        return RCL_RET_OK;
    }

    rcutils_string_array_t names = rcutils_get_zero_initialized_string_array();
    rcutils_string_array_t namespaces = rcutils_get_zero_initialized_string_array();
    rcl_ret_t result = rcl_get_node_names(node, allocator, &names, &namespaces);
    if (result == RCL_RET_OK && names.size > 0) {
        graph_ok = true;
        printf("MICRO_ROS_GRAPH_OK nodes=%zu\n", names.size);
    }
    if (names.data != NULL) {
        (void)rcutils_string_array_fini(&names);
    }
    if (namespaces.data != NULL) {
        (void)rcutils_string_array_fini(&namespaces);
    }
    return result;
}

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

static void update_action_client_status(void)
{
    if (!action_client_ok && action_client_feedback_ok && action_client_result_ok &&
        action_client_cancel_accepted && action_client_cancel_result_ok) {
        action_client_ok = true;
        puts("MICRO_ROS_ACTION_CLIENT_OK success=1 feedback=1 cancel=1");
    }
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
        puts("MICRO_ROS_EXECUTOR_TIMER_OK count=20");
    }
}

static void guard_condition_callback(void)
{
    guard_condition_ok = true;
    puts("MICRO_ROS_GUARD_CONDITION_OK");
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

static void service_client_callback(const void *response_message)
{
    const example_interfaces__srv__AddTwoInts_Response *response = response_message;

    printf("micro-ROS: service client received sum=%lld\n", (long long)response->sum);
    if (response->sum == SERVICE_CLIENT_A + SERVICE_CLIENT_B) {
        service_client_ok = true;
        puts("MICRO_ROS_SERVICE_CLIENT_OK sum=42");
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

static void action_client_goal_callback(rclc_action_goal_handle_t *goal_handle, bool accepted,
                                        void *context)
{
    (void)context;
    example_interfaces__action__Fibonacci_SendGoal_Request *request =
        (example_interfaces__action__Fibonacci_SendGoal_Request *)goal_handle->ros_goal_request;

    printf("micro-ROS: action client goal order=%d accepted=%d\n", (int)request->goal.order,
           accepted);
}

static void action_client_feedback_callback(rclc_action_goal_handle_t *goal_handle,
                                            void *feedback_message, void *context)
{
    (void)context;
    example_interfaces__action__Fibonacci_SendGoal_Request *request =
        (example_interfaces__action__Fibonacci_SendGoal_Request *)goal_handle->ros_goal_request;
    example_interfaces__action__Fibonacci_FeedbackMessage *feedback = feedback_message;

    printf("micro-ROS: action client feedback order=%d size=%zu\n", (int)request->goal.order,
           feedback->feedback.sequence.size);
    if (request->goal.order == ACTION_CLIENT_SUCCESS_ORDER &&
        feedback->feedback.sequence.size >= 3) {
        action_client_feedback_ok = true;
    }
    if (request->goal.order == ACTION_CLIENT_CANCEL_ORDER &&
        feedback->feedback.sequence.size >= 3 && !action_client_cancel_requested) {
        if (rclc_action_send_cancel_request(goal_handle) == RCL_RET_OK) {
            action_client_cancel_requested = true;
            puts("micro-ROS: action client requested cancellation");
        }
    }
}

static void action_client_result_callback(rclc_action_goal_handle_t *goal_handle,
                                          void *result_message, void *context)
{
    (void)context;
    example_interfaces__action__Fibonacci_SendGoal_Request *request =
        (example_interfaces__action__Fibonacci_SendGoal_Request *)goal_handle->ros_goal_request;
    example_interfaces__action__Fibonacci_GetResult_Response *response = result_message;

    printf("micro-ROS: action client result order=%d status=%d size=%zu\n",
           (int)request->goal.order, (int)response->status, response->result.sequence.size);
    if (request->goal.order == ACTION_CLIENT_SUCCESS_ORDER &&
        response->status == GOAL_STATE_SUCCEEDED && response->result.sequence.size == 6 &&
        response->result.sequence.data[5] == 5) {
        action_client_result_ok = true;
        if (!action_client_second_goal_sent &&
            rclc_action_send_goal_request(&host_action_client, &action_client_requests[1], NULL) ==
                RCL_RET_OK) {
            action_client_second_goal_sent = true;
            puts("micro-ROS: action client sent cancellation test goal");
        }
    } else if (request->goal.order == ACTION_CLIENT_CANCEL_ORDER &&
               response->status == GOAL_STATE_CANCELED) {
        action_client_cancel_result_ok = true;
    }
    update_action_client_status();
}

static void action_client_cancel_callback(rclc_action_goal_handle_t *goal_handle, bool cancelled,
                                          void *context)
{
    (void)goal_handle;
    (void)context;
    printf("micro-ROS: action client cancellation accepted=%d\n", cancelled);
    action_client_cancel_accepted = cancelled;
    update_action_client_status();
}

static bool parameter_changed_callback(const Parameter *old_parameter,
                                       const Parameter *new_parameter, void *context)
{
    (void)old_parameter;
    (void)context;
    if (new_parameter != NULL && strcmp(new_parameter->name.data, "arceos_answer") == 0 &&
        new_parameter->value.type == RCLC_PARAMETER_INT &&
        new_parameter->value.integer_value == EXPECTED_VALUE) {
        parameter_ok = true;
        puts("MICRO_ROS_PARAMETER_OK arceos_answer=42");
    }
    return true;
}

static rcl_ret_t lifecycle_on_configure(void)
{
    lifecycle_configure_ok = true;
    puts("micro-ROS: lifecycle configured");
    return RCL_RET_OK;
}

static rcl_ret_t lifecycle_on_activate(void)
{
    lifecycle_activate_ok = true;
    puts("micro-ROS: lifecycle activated");
    return RCL_RET_OK;
}

static rcl_ret_t lifecycle_on_deactivate(void)
{
    lifecycle_deactivate_ok = true;
    puts("micro-ROS: lifecycle deactivated");
    return RCL_RET_OK;
}

static rcl_ret_t lifecycle_on_cleanup(void)
{
    if (lifecycle_configure_ok && lifecycle_activate_ok && lifecycle_deactivate_ok) {
        lifecycle_ok = true;
        puts("MICRO_ROS_LIFECYCLE_OK transitions=4");
    }
    return RCL_RET_OK;
}

static bool fill_transition_description(
    lifecycle_msgs__msg__TransitionDescription *description,
    const rcl_lifecycle_transition_t *transition)
{
    description->transition.id = (uint8_t)transition->id;
    description->start_state.id = transition->start->id;
    description->goal_state.id = transition->goal->id;
    return rosidl_runtime_c__String__assign(&description->transition.label, transition->label) &&
           rosidl_runtime_c__String__assign(&description->start_state.label,
                                            transition->start->label) &&
           rosidl_runtime_c__String__assign(&description->goal_state.label,
                                            transition->goal->label);
}

static void lifecycle_get_transitions_callback(const void *request_message,
                                               void *response_message, void *context)
{
    (void)request_message;
    lifecycle_msgs__srv__GetAvailableTransitions_Response *response = response_message;
    const struct lifecycle_transitions_context *transitions_context = context;
    const rcl_lifecycle_state_machine_t *state_machine =
        transitions_context->lifecycle_node->state_machine;
    const rcl_lifecycle_transition_t *transitions;
    size_t transition_count;

    if (transitions_context->full_graph) {
        transitions = state_machine->transition_map.transitions;
        transition_count = state_machine->transition_map.transitions_size;
    } else {
        transitions = state_machine->current_state->valid_transitions;
        transition_count = state_machine->current_state->valid_transition_size;
    }
    response->available_transitions.size = 0;
    if (transition_count > response->available_transitions.capacity) {
        puts("micro-ROS: lifecycle transition response capacity exceeded");
        return;
    }
    for (size_t index = 0; index < transition_count; ++index) {
        if (!fill_transition_description(&response->available_transitions.data[index],
                                         &transitions[index])) {
            puts("micro-ROS: failed to populate lifecycle transition response");
            return;
        }
        response->available_transitions.size++;
    }
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
    rcl_client_t service_client = rcl_get_zero_initialized_client();
    rcl_timer_t timer = rcl_get_zero_initialized_timer();
    rcl_guard_condition_t guard_condition = rcl_get_zero_initialized_guard_condition();
    rclc_executor_t executor = rclc_executor_get_zero_initialized_executor();
    rclc_action_server_t action_server = {0};
    rcl_lifecycle_state_machine_t lifecycle_state_machine =
        rcl_lifecycle_get_zero_initialized_state_machine();
    rclc_lifecycle_node_t lifecycle_node = {0};
    rclc_lifecycle_service_context_t lifecycle_context = {
        .lifecycle_node = &lifecycle_node,
    };
    struct lifecycle_transitions_context available_transitions_context = {
        .lifecycle_node = &lifecycle_node,
        .full_graph = false,
    };
    struct lifecycle_transitions_context transition_graph_context = {
        .lifecycle_node = &lifecycle_node,
        .full_graph = true,
    };
    lifecycle_msgs__srv__GetAvailableTransitions_Request available_transitions_request = {0};
    lifecycle_msgs__srv__GetAvailableTransitions_Response available_transitions_response = {0};
    lifecycle_msgs__srv__GetAvailableTransitions_Request transition_graph_request = {0};
    lifecycle_msgs__srv__GetAvailableTransitions_Response transition_graph_response = {0};
    std_msgs__msg__Int32 subscription_message = {0};
    example_interfaces__srv__AddTwoInts_Request service_request = {0};
    example_interfaces__srv__AddTwoInts_Response service_response = {0};
    example_interfaces__srv__AddTwoInts_Request service_client_request = {
        .a = SERVICE_CLIENT_A,
        .b = SERVICE_CLIENT_B,
    };
    example_interfaces__srv__AddTwoInts_Response service_client_response = {0};
    example_interfaces__action__Fibonacci_SendGoal_Request action_requests[1] = {0};
    example_interfaces__action__Fibonacci_FeedbackMessage action_client_feedback = {0};
    example_interfaces__action__Fibonacci_GetResult_Response action_client_result = {0};
    int32_t action_client_feedback_sequence[ACTION_CLIENT_SEQUENCE_CAPACITY] = {0};
    int32_t action_client_result_sequence[ACTION_CLIENT_SEQUENCE_CAPACITY] = {0};
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
    if (rmw_uros_sync_session(1000) != RMW_RET_OK || !rmw_uros_epoch_synchronized() ||
        rmw_uros_epoch_millis() <= 0) {
        puts("micro-ROS: time synchronization failed");
        return 1;
    }
    time_sync_ok = true;
    printf("MICRO_ROS_TIME_SYNC_OK epoch_ms=%lld\n", (long long)rmw_uros_epoch_millis());
    result = rclc_node_init_default(&node, "arceos_micro_ros", "", &support);
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_node_init_default", result);
    }
    result = rclc_make_node_a_lifecycle_node(&lifecycle_node, &node, &lifecycle_state_machine,
                                             &allocator, true);
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_make_node_a_lifecycle_node", result);
    }
    (void)rclc_lifecycle_register_on_configure(&lifecycle_node, lifecycle_on_configure);
    (void)rclc_lifecycle_register_on_activate(&lifecycle_node, lifecycle_on_activate);
    (void)rclc_lifecycle_register_on_deactivate(&lifecycle_node, lifecycle_on_deactivate);
    (void)rclc_lifecycle_register_on_cleanup(&lifecycle_node, lifecycle_on_cleanup);
    if (!rosidl_runtime_c__String__resize(&lifecycle_node.cs_req.transition.label,
                                         LIFECYCLE_LABEL_CAPACITY - 1)) {
        puts("micro-ROS: failed to allocate lifecycle transition label");
        return 1;
    }
    lifecycle_node.cs_req.transition.label.data[0] = '\0';
    lifecycle_node.cs_req.transition.label.size = 0;
    lifecycle_msgs__srv__GetAvailableTransitions_Request__init(
        &available_transitions_request);
    lifecycle_msgs__srv__GetAvailableTransitions_Response__init(
        &available_transitions_response);
    lifecycle_msgs__srv__GetAvailableTransitions_Request__init(&transition_graph_request);
    lifecycle_msgs__srv__GetAvailableTransitions_Response__init(&transition_graph_response);
    size_t lifecycle_transition_capacity = lifecycle_state_machine.transition_map.transitions_size;
    if (!lifecycle_msgs__msg__TransitionDescription__Sequence__init(
            &available_transitions_response.available_transitions,
            lifecycle_transition_capacity) ||
        !lifecycle_msgs__msg__TransitionDescription__Sequence__init(
            &transition_graph_response.available_transitions,
            lifecycle_transition_capacity)) {
        puts("micro-ROS: failed to allocate lifecycle transition responses");
        return 1;
    }
    result = rclc_publisher_init_best_effort(
        &publisher, &node, ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, Int32), "arceos_counter");
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_publisher_init_default", result);
    }
    counter_publisher = publisher;
    result = rclc_subscription_init_best_effort(
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
    result = rclc_client_init_default(
        &service_client, &node,
        ROSIDL_GET_SRV_TYPE_SUPPORT(example_interfaces, srv, AddTwoInts),
        "host_add_two_ints");
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_client_init_default", result);
    }
    result = rclc_action_server_init_default(
        &action_server, &node, &support,
        ROSIDL_GET_ACTION_TYPE_SUPPORT(example_interfaces, Fibonacci), "arceos_fibonacci");
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_action_server_init_default", result);
    }
    result = rclc_action_client_init_default(
        &host_action_client, &node,
        ROSIDL_GET_ACTION_TYPE_SUPPORT(example_interfaces, Fibonacci), "host_fibonacci");
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_action_client_init_default", result);
    }
    result = rclc_parameter_server_init_default(&parameter_server, &node);
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_parameter_server_init_default", result);
    }
    result = rclc_timer_init_default2(&timer, &support, RCL_MS_TO_NS(500), timer_callback, true);
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_timer_init_default2", result);
    }
    result = rcl_guard_condition_init(&guard_condition, &support.context,
                                      rcl_guard_condition_get_default_options());
    if (result != RCL_RET_OK) {
        return report_rcl_error("rcl_guard_condition_init", result);
    }

    result = rclc_executor_init(&executor, &support.context, 24, &allocator);
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_executor_init", result);
    }
    if ((result = rclc_executor_add_timer(&executor, &timer)) != RCL_RET_OK) {
        return report_rcl_error("rclc_executor_add_timer", result);
    }
    if ((result = rclc_executor_add_guard_condition(
             &executor, &guard_condition, guard_condition_callback)) != RCL_RET_OK) {
        return report_rcl_error("rclc_executor_add_guard_condition", result);
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
    if ((result = rclc_executor_add_client(&executor, &service_client,
                                           &service_client_response,
                                           service_client_callback)) != RCL_RET_OK) {
        return report_rcl_error("rclc_executor_add_client", result);
    }
    if ((result = rclc_executor_add_action_server(
             &executor, &action_server, 1, action_requests, sizeof(action_requests[0]),
             action_goal_callback, action_cancel_callback, &action_server)) != RCL_RET_OK) {
        return report_rcl_error("rclc_executor_add_action_server", result);
    }
    action_client_feedback.feedback.sequence.data = action_client_feedback_sequence;
    action_client_feedback.feedback.sequence.capacity = ACTION_CLIENT_SEQUENCE_CAPACITY;
    action_client_result.result.sequence.data = action_client_result_sequence;
    action_client_result.result.sequence.capacity = ACTION_CLIENT_SEQUENCE_CAPACITY;
    if ((result = rclc_executor_add_action_client(
             &executor, &host_action_client, 2, &action_client_result, &action_client_feedback,
             action_client_goal_callback, action_client_feedback_callback,
             action_client_result_callback, action_client_cancel_callback,
             &host_action_client)) != RCL_RET_OK) {
        return report_rcl_error("rclc_executor_add_action_client", result);
    }
    if ((result = rclc_lifecycle_init_get_state_server(&lifecycle_context, &executor)) !=
        RCL_RET_OK) {
        return report_rcl_error("rclc_lifecycle_init_get_state_server", result);
    }
    if ((result = rclc_lifecycle_init_get_available_states_server(&lifecycle_context,
                                                                  &executor)) != RCL_RET_OK) {
        return report_rcl_error("rclc_lifecycle_init_get_available_states_server", result);
    }
    if ((result = rclc_lifecycle_init_change_state_server(&lifecycle_context, &executor)) !=
        RCL_RET_OK) {
        return report_rcl_error("rclc_lifecycle_init_change_state_server", result);
    }
    if ((result = rclc_executor_add_service_with_context(
             &executor, &lifecycle_state_machine.com_interface.srv_get_available_transitions,
             &available_transitions_request, &available_transitions_response,
             lifecycle_get_transitions_callback,
             &available_transitions_context)) != RCL_RET_OK) {
        return report_rcl_error("add get_available_transitions service", result);
    }
    if ((result = rclc_executor_add_service_with_context(
             &executor, &lifecycle_state_machine.com_interface.srv_get_transition_graph,
             &transition_graph_request, &transition_graph_response,
             lifecycle_get_transitions_callback, &transition_graph_context)) != RCL_RET_OK) {
        return report_rcl_error("add get_transition_graph service", result);
    }
    if ((result = rclc_executor_add_parameter_server(
             &executor, &parameter_server, parameter_changed_callback)) != RCL_RET_OK) {
        return report_rcl_error("rclc_executor_add_parameter_server", result);
    }
    if ((result = rclc_add_parameter(&parameter_server, "arceos_enabled",
                                     RCLC_PARAMETER_BOOL)) != RCL_RET_OK ||
        (result = rclc_add_parameter(&parameter_server, "arceos_answer",
                                     RCLC_PARAMETER_INT)) != RCL_RET_OK ||
        (result = rclc_add_parameter(&parameter_server, "arceos_gain",
                                     RCLC_PARAMETER_DOUBLE)) != RCL_RET_OK ||
        (result = rclc_parameter_set_bool(&parameter_server, "arceos_enabled", true)) !=
            RCL_RET_OK ||
        (result = rclc_parameter_set_int(&parameter_server, "arceos_answer", 7)) != RCL_RET_OK ||
        (result = rclc_parameter_set_double(&parameter_server, "arceos_gain", 0.5)) !=
            RCL_RET_OK) {
        return report_rcl_error("parameter initialization", result);
    }

    if (rmw_uros_enable_graph() != RMW_RET_OK) {
        puts("micro-ROS: rmw_uros_enable_graph failed");
        return 1;
    }
    puts("MICRO_ROS_GRAPH_REQUESTED");
    for (size_t attempt = 0; attempt < 3000 && !graph_ok; ++attempt) {
        result = rclc_executor_spin_some(&executor, RCL_MS_TO_NS(10));
        if (result != RCL_RET_OK && result != RCL_RET_TIMEOUT) {
            return report_rcl_error("graph rclc_executor_spin_some", result);
        }
        result = update_graph_status(&node, allocator);
        if (result != RCL_RET_OK) {
            return report_rcl_error("rcl_get_node_names", result);
        }
        usleep(10000);
    }
    if (!graph_ok) {
        puts("micro-ROS: graph discovery timed out");
        return 1;
    }

    puts("MICRO_ROS_FEATURES_READY");
    result = rcl_trigger_guard_condition(&guard_condition);
    if (result != RCL_RET_OK) {
        return report_rcl_error("rcl_trigger_guard_condition", result);
    }
    rclc_sleep_ms(2000);
    int64_t service_sequence_number;
    result = rcl_send_request(&service_client, &service_client_request,
                              &service_sequence_number);
    if (result != RCL_RET_OK) {
        return report_rcl_error("rcl_send_request", result);
    }
    puts("micro-ROS: service client sent 19 + 23");
    action_client_requests[0].goal.order = ACTION_CLIENT_SUCCESS_ORDER;
    action_client_requests[1].goal.order = ACTION_CLIENT_CANCEL_ORDER;
    result = rclc_action_send_goal_request(&host_action_client, &action_client_requests[0], NULL);
    if (result != RCL_RET_OK) {
        return report_rcl_error("rclc_action_send_goal_request", result);
    }
    puts("micro-ROS: action client sent success test goal");

    size_t spin_iterations = 0;
    while (!(timer_ok && subscriber_ok && service_ok && service_client_ok &&
             action_succeeded() && action_client_ok && parameter_ok && lifecycle_ok &&
             time_sync_ok && guard_condition_ok && graph_ok)) {
        result = rclc_executor_spin_some(&executor, RCL_MS_TO_NS(10));
        if (result != RCL_RET_OK && result != RCL_RET_TIMEOUT) {
            return report_rcl_error("rclc_executor_spin_some", result);
        }
        ++spin_iterations;
        if (!service_client_ok && spin_iterations % 200 == 0) {
            result = rcl_send_request(&service_client, &service_client_request,
                                      &service_sequence_number);
            if (result != RCL_RET_OK) {
                return report_rcl_error("service client retry", result);
            }
            puts("micro-ROS: service client retry sent");
        }
        usleep(10000);
    }

    puts("MICRO_ROS_FEATURES_OK executor=1 guard_condition=1 qos_best_effort=1 subscriber=1 service_server=1 service_client=1 action_server=1 action_client=1 parameter=1 lifecycle=1 time_sync=1 graph=1");
    if (action_worker_started) {
        (void)pthread_join(action_worker, NULL);
    }
    (void)rclc_executor_fini(&executor);
    (void)rcl_guard_condition_fini(&guard_condition);
    (void)rcl_timer_fini(&timer);
    (void)rclc_parameter_server_fini(&parameter_server, &node);
    lifecycle_msgs__srv__GetAvailableTransitions_Response__fini(
        &transition_graph_response);
    lifecycle_msgs__srv__GetAvailableTransitions_Request__fini(&transition_graph_request);
    lifecycle_msgs__srv__GetAvailableTransitions_Response__fini(
        &available_transitions_response);
    lifecycle_msgs__srv__GetAvailableTransitions_Request__fini(
        &available_transitions_request);
    (void)rclc_lifecycle_node_fini(&lifecycle_node, &allocator);
    (void)rclc_action_client_fini(&host_action_client, &node);
    (void)rclc_action_server_fini(&action_server, &node);
    (void)rcl_client_fini(&service_client, &node);
    (void)rcl_service_fini(&service, &node);
    (void)rcl_subscription_fini(&subscription, &node);
    (void)rcl_publisher_fini(&publisher, &node);
    (void)rcl_node_fini(&node);
    (void)rclc_support_fini(&support);
    transport_close(&(struct uxrCustomTransport){.args = &transport});
    return 0;
}
