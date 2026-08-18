#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#ifdef BENCHMARK_SHM_TRANSPORT
#include "shm_transport.h"
#else
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/time.h>
#endif

#include <example_interfaces/srv/add_two_ints.h>
#include <example_interfaces/srv/detail/add_two_ints__rosidl_typesupport_microxrcedds_c.h>
#include <rcl/rcl.h>
#include <rclc/executor.h>
#include <rclc/rclc.h>
#include <rclc/timer.h>
#include <rmw_microros/custom_transport.h>
#include <rmw_microros/ping.h>
#include <std_msgs/msg/int32.h>
#include <std_msgs/msg/detail/int32__rosidl_typesupport_microxrcedds_c.h>
#include <uxr/client/profile/transport/custom/custom_transport.h>

#ifndef BENCHMARK_PLATFORM
#define BENCHMARK_PLATFORM "arceos"
#endif
#ifndef BENCHMARK_AGENT_ADDRESS
#define BENCHMARK_AGENT_ADDRESS "10.0.2.2"
#endif
#ifndef BENCHMARK_AGENT_PORT
#define BENCHMARK_AGENT_PORT 8888
#endif
#ifndef BENCHMARK_WARMUP_SAMPLES
#define BENCHMARK_WARMUP_SAMPLES 100
#endif
#ifndef BENCHMARK_MEASURED_SAMPLES
#define BENCHMARK_MEASURED_SAMPLES 1000
#endif
#ifndef BENCHMARK_TIMER_PERIOD_MS
#define BENCHMARK_TIMER_PERIOD_MS 10
#endif

#define BENCHMARK_PHASE_TIMEOUT_MS 30000
#define BENCHMARK_DISCOVERY_DELAY_MS 1000
#define BENCHMARK_SPIN_TIMEOUT_MS 1
#define BENCHMARK_TOTAL_SAMPLES (BENCHMARK_WARMUP_SAMPLES + BENCHMARK_MEASURED_SAMPLES)

enum benchmark_phase {
    BENCHMARK_TOPIC_RTT,
    BENCHMARK_SERVICE_RTT,
    BENCHMARK_TIMER_JITTER,
    BENCHMARK_FINISHED,
    BENCHMARK_FAILED,
};

struct benchmark_transport {
#ifdef BENCHMARK_SHM_TRANSPORT
    struct benchmark_shm_area *shared;
#else
    int socket;
    struct sockaddr_in agent;
#endif
};

#ifdef BENCHMARK_SHM_TRANSPORT
static struct benchmark_shm_area benchmark_shared_area __attribute__((aligned(4096), used));
#endif

struct benchmark_state {
    enum benchmark_phase phase;
    uint32_t completed_samples;
    uint64_t request_started_ns;
    uint64_t samples_ns[BENCHMARK_MEASURED_SAMPLES];
    int64_t request_sequence_number;
    const char *failure;
    rcl_publisher_t *ping_publisher;
    rcl_client_t *service_client;
    rcl_timer_t *timer;
    std_msgs__msg__Int32 ping_message;
    example_interfaces__srv__AddTwoInts_Request service_request;
};

static struct benchmark_state *active_benchmark;

static int run_benchmark(void);
static bool initialize_transport(struct benchmark_transport *transport);
static void finish_transport(struct benchmark_transport *transport);
static bool initialize_entities(rclc_support_t *support, rcl_node_t *node,
                                rcl_publisher_t *publisher, rcl_subscription_t *subscription,
                                rcl_client_t *client, rcl_timer_t *timer,
                                rclc_executor_t *executor, rcl_allocator_t *allocator,
                                std_msgs__msg__Int32 *pong_message,
                                example_interfaces__srv__AddTwoInts_Response *service_response);
static bool run_phase(rclc_executor_t *executor, enum benchmark_phase phase);
static bool begin_sample(void);
static void complete_sample(uint64_t elapsed_ns);
static void report_samples(const char *test);
static void sort_samples(uint64_t *samples, size_t count);
static uint64_t monotonic_now_ns(void);
static void fail_benchmark(const char *operation);
static void pong_callback(const void *message);
static void service_callback(const void *message);
static void timer_callback(rcl_timer_t *timer, int64_t last_call_time);
static bool transport_open(struct uxrCustomTransport *transport);
static bool transport_close(struct uxrCustomTransport *transport);
static size_t transport_write(struct uxrCustomTransport *transport, const uint8_t *buffer,
                              size_t length, uint8_t *error_code);
static size_t transport_read(struct uxrCustomTransport *transport, uint8_t *buffer, size_t length,
                             int timeout_ms, uint8_t *error_code);

int main(void)
{
    return run_benchmark();
}

static int run_benchmark(void)
{
#ifdef BENCHMARK_SHM_TRANSPORT
    struct benchmark_transport transport = {.shared = &benchmark_shared_area};
#else
    struct benchmark_transport transport = {.socket = -1};
#endif
    rcl_allocator_t allocator = rcl_get_default_allocator();
    rclc_support_t support = {0};
    rcl_node_t node = rcl_get_zero_initialized_node();
    rcl_publisher_t publisher = rcl_get_zero_initialized_publisher();
    rcl_subscription_t subscription = rcl_get_zero_initialized_subscription();
    rcl_client_t client = rcl_get_zero_initialized_client();
    rcl_timer_t timer = rcl_get_zero_initialized_timer();
    rclc_executor_t executor = rclc_executor_get_zero_initialized_executor();
    std_msgs__msg__Int32 pong_message = {0};
    example_interfaces__srv__AddTwoInts_Response service_response = {0};
    struct benchmark_state benchmark = {
        .phase = BENCHMARK_TOPIC_RTT,
        .ping_publisher = &publisher,
        .service_client = &client,
        .timer = &timer,
    };

    active_benchmark = &benchmark;
#ifdef BENCHMARK_SHM_TRANSPORT
    const char *transport_name = "shared-memory-poll";
#else
    const char *transport_name = "udp";
#endif
    printf("BENCHMARK_CONFIG platform=%s transport=%s qos=reliable warmup=%u samples=%u "
           "timer_period_us=%u\n",
           BENCHMARK_PLATFORM, transport_name, (unsigned)BENCHMARK_WARMUP_SAMPLES,
           (unsigned)BENCHMARK_MEASURED_SAMPLES, (unsigned)(BENCHMARK_TIMER_PERIOD_MS * 1000));
    if (!initialize_transport(&transport) ||
        !initialize_entities(&support, &node, &publisher, &subscription, &client, &timer,
                             &executor, &allocator, &pong_message, &service_response)) {
        finish_transport(&transport);
        return 1;
    }

    for (unsigned elapsed_ms = 0; elapsed_ms < BENCHMARK_DISCOVERY_DELAY_MS;
         elapsed_ms += BENCHMARK_SPIN_TIMEOUT_MS) {
        if (rclc_executor_spin_some(&executor, RCL_MS_TO_NS(BENCHMARK_SPIN_TIMEOUT_MS)) !=
            RCL_RET_OK) {
            fail_benchmark("discovery spin");
            finish_transport(&transport);
            return 1;
        }
    }

    if (!run_phase(&executor, BENCHMARK_TOPIC_RTT) ||
        !run_phase(&executor, BENCHMARK_SERVICE_RTT) ||
        !run_phase(&executor, BENCHMARK_TIMER_JITTER)) {
        printf("MICRO_ROS_BENCHMARK_FAILED platform=%s phase=%d operation=%s\n",
               BENCHMARK_PLATFORM, (int)benchmark.phase,
               benchmark.failure == NULL ? "timeout" : benchmark.failure);
        finish_transport(&transport);
        return 1;
    }

    benchmark.phase = BENCHMARK_FINISHED;
    finish_transport(&transport);
    printf("MICRO_ROS_BENCHMARK_OK platform=%s tests=3 samples=%u\n", BENCHMARK_PLATFORM,
           (unsigned)BENCHMARK_MEASURED_SAMPLES);
    return 0;
}

static void finish_transport(struct benchmark_transport *transport)
{
#ifdef BENCHMARK_SHM_TRANSPORT
    benchmark_shm_store_release(&transport->shared->guest_done, 1U);
#else
    (void)transport;
#endif
}

static bool initialize_transport(struct benchmark_transport *transport)
{
#ifdef BENCHMARK_SHM_TRANSPORT
    puts("micro-ROS benchmark: connecting to Agent through shared RAM bridge");
#else
    printf("micro-ROS benchmark: connecting to Agent at %s:%u\n", BENCHMARK_AGENT_ADDRESS,
           (unsigned)BENCHMARK_AGENT_PORT);
#endif
    if (rmw_uros_set_custom_transport(false, transport, transport_open, transport_close,
                                      transport_write, transport_read) != RMW_RET_OK) {
        fail_benchmark("configure transport");
        return false;
    }
    if (rmw_uros_ping_agent(1000, 5) != RMW_RET_OK) {
        fail_benchmark("agent ping");
        return false;
    }
    return true;
}

static bool initialize_entities(rclc_support_t *support, rcl_node_t *node,
                                rcl_publisher_t *publisher, rcl_subscription_t *subscription,
                                rcl_client_t *client, rcl_timer_t *timer,
                                rclc_executor_t *executor, rcl_allocator_t *allocator,
                                std_msgs__msg__Int32 *pong_message,
                                example_interfaces__srv__AddTwoInts_Response *service_response)
{
    rcl_ret_t result;

    if ((result = rclc_support_init(support, 0, NULL, allocator)) != RCL_RET_OK ||
        (result = rclc_node_init_default(node, "micro_ros_benchmark", "", support)) !=
            RCL_RET_OK ||
        (result = rclc_publisher_init_default(
             publisher, node,
             ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
                 rosidl_typesupport_microxrcedds_c, std_msgs, msg, Int32)(),
             "benchmark/ping")) != RCL_RET_OK ||
        (result = rclc_subscription_init_default(
             subscription, node,
             ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
                 rosidl_typesupport_microxrcedds_c, std_msgs, msg, Int32)(),
             "benchmark/pong")) != RCL_RET_OK ||
        (result = rclc_client_init_default(
             client, node,
             ROSIDL_TYPESUPPORT_INTERFACE__SERVICE_SYMBOL_NAME(
                 rosidl_typesupport_microxrcedds_c, example_interfaces, srv, AddTwoInts)(),
             "benchmark/add_two_ints")) != RCL_RET_OK ||
        (result = rclc_timer_init_default2(timer, support,
                                           RCL_MS_TO_NS(BENCHMARK_TIMER_PERIOD_MS),
                                           timer_callback, false)) != RCL_RET_OK ||
        (result = rclc_executor_init(executor, &support->context, 3, allocator)) != RCL_RET_OK ||
        (result = rclc_executor_add_subscription(executor, subscription, pong_message,
                                                 pong_callback, ON_NEW_DATA)) != RCL_RET_OK ||
        (result = rclc_executor_add_client(executor, client, service_response,
                                           service_callback)) != RCL_RET_OK ||
        (result = rclc_executor_add_timer(executor, timer)) != RCL_RET_OK) {
        printf("micro-ROS benchmark: entity initialization failed: rcl_ret=%d\n", (int)result);
        fail_benchmark("entity initialization");
        return false;
    }
    return true;
}

static bool run_phase(rclc_executor_t *executor, enum benchmark_phase phase)
{
    struct benchmark_state *benchmark = active_benchmark;
    uint64_t deadline_ns;
    uint64_t spin_timeout_ns =
        phase == BENCHMARK_TIMER_JITTER ? 0 : RCL_MS_TO_NS(BENCHMARK_SPIN_TIMEOUT_MS);

    benchmark->phase = phase;
    benchmark->completed_samples = 0;
    benchmark->failure = NULL;
    memset(benchmark->samples_ns, 0, sizeof(benchmark->samples_ns));

    if (phase == BENCHMARK_TIMER_JITTER) {
        if (rcl_timer_reset(benchmark->timer) != RCL_RET_OK) {
            fail_benchmark("timer reset");
            return false;
        }
    } else if (!begin_sample()) {
        return false;
    }

    deadline_ns = monotonic_now_ns() + (uint64_t)BENCHMARK_PHASE_TIMEOUT_MS * 1000000ULL;
    while (benchmark->phase == phase && monotonic_now_ns() < deadline_ns) {
        if (rclc_executor_spin_some(executor, spin_timeout_ns) != RCL_RET_OK) {
            fail_benchmark("executor spin");
            return false;
        }
    }
    return benchmark->phase != BENCHMARK_FAILED && benchmark->phase != phase;
}

static bool begin_sample(void)
{
    struct benchmark_state *benchmark = active_benchmark;
    int64_t sequence = (int64_t)benchmark->completed_samples + 1;
    rcl_ret_t result;

    benchmark->request_started_ns = monotonic_now_ns();
    if (benchmark->phase == BENCHMARK_TOPIC_RTT) {
        benchmark->ping_message.data = (int32_t)sequence;
        result = rcl_publish(benchmark->ping_publisher, &benchmark->ping_message, NULL);
    } else {
        benchmark->service_request.a = sequence;
        benchmark->service_request.b = 1;
        result = rcl_send_request(benchmark->service_client, &benchmark->service_request,
                                  &benchmark->request_sequence_number);
    }
    if (result != RCL_RET_OK) {
        fail_benchmark(benchmark->phase == BENCHMARK_TOPIC_RTT ? "topic publish"
                                                               : "service request");
        return false;
    }
    return true;
}

static void complete_sample(uint64_t elapsed_ns)
{
    struct benchmark_state *benchmark = active_benchmark;

    if (benchmark->completed_samples >= BENCHMARK_WARMUP_SAMPLES) {
        benchmark->samples_ns[benchmark->completed_samples - BENCHMARK_WARMUP_SAMPLES] =
            elapsed_ns;
    }
    benchmark->completed_samples++;
    if (benchmark->completed_samples == BENCHMARK_TOTAL_SAMPLES) {
        const char *test = benchmark->phase == BENCHMARK_TOPIC_RTT     ? "topic_rtt"
                           : benchmark->phase == BENCHMARK_SERVICE_RTT ? "service_rtt"
                                                                        : "executor_timer_jitter";
        report_samples(test);
        benchmark->phase = (enum benchmark_phase)(benchmark->phase + 1);
    } else if (benchmark->phase != BENCHMARK_TIMER_JITTER) {
        (void)begin_sample();
    }
}

static void report_samples(const char *test)
{
    struct benchmark_state *benchmark = active_benchmark;
    uint64_t sum_ns = 0;
    size_t p50 = (BENCHMARK_MEASURED_SAMPLES - 1) * 50 / 100;
    size_t p95 = (BENCHMARK_MEASURED_SAMPLES - 1) * 95 / 100;
    size_t p99 = (BENCHMARK_MEASURED_SAMPLES - 1) * 99 / 100;

    sort_samples(benchmark->samples_ns, BENCHMARK_MEASURED_SAMPLES);
    for (size_t index = 0; index < BENCHMARK_MEASURED_SAMPLES; ++index) {
        sum_ns += benchmark->samples_ns[index];
    }
    printf("BENCH_RESULT platform=%s test=%s qos=reliable samples=%u min_ns=%llu mean_ns=%llu "
           "p50_ns=%llu p95_ns=%llu p99_ns=%llu max_ns=%llu failures=0\n",
           BENCHMARK_PLATFORM, test, (unsigned)BENCHMARK_MEASURED_SAMPLES,
           (unsigned long long)benchmark->samples_ns[0],
           (unsigned long long)(sum_ns / BENCHMARK_MEASURED_SAMPLES),
           (unsigned long long)benchmark->samples_ns[p50],
           (unsigned long long)benchmark->samples_ns[p95],
           (unsigned long long)benchmark->samples_ns[p99],
           (unsigned long long)benchmark->samples_ns[BENCHMARK_MEASURED_SAMPLES - 1]);
}

static void sort_samples(uint64_t *samples, size_t count)
{
    for (size_t index = 1; index < count; ++index) {
        uint64_t sample = samples[index];
        size_t position = index;

        while (position > 0 && samples[position - 1] > sample) {
            samples[position] = samples[position - 1];
            position--;
        }
        samples[position] = sample;
    }
}

static uint64_t monotonic_now_ns(void)
{
    struct timespec now;

    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
        fail_benchmark("monotonic clock");
        return 0;
    }
    return (uint64_t)now.tv_sec * 1000000000ULL + (uint64_t)now.tv_nsec;
}

static void fail_benchmark(const char *operation)
{
    if (active_benchmark != NULL) {
        active_benchmark->failure = operation;
        active_benchmark->phase = BENCHMARK_FAILED;
    }
}

static void pong_callback(const void *message)
{
    const std_msgs__msg__Int32 *pong = message;
    struct benchmark_state *benchmark = active_benchmark;

    if (benchmark->phase != BENCHMARK_TOPIC_RTT ||
        pong->data != (int32_t)benchmark->completed_samples + 1) {
        return;
    }
    complete_sample(monotonic_now_ns() - benchmark->request_started_ns);
}

static void service_callback(const void *message)
{
    const example_interfaces__srv__AddTwoInts_Response *response = message;
    struct benchmark_state *benchmark = active_benchmark;
    int64_t expected = (int64_t)benchmark->completed_samples + 2;

    if (benchmark->phase != BENCHMARK_SERVICE_RTT || response->sum != expected) {
        return;
    }
    complete_sample(monotonic_now_ns() - benchmark->request_started_ns);
}

static void timer_callback(rcl_timer_t *timer, int64_t last_call_time)
{
    int64_t period_ns = RCL_MS_TO_NS(BENCHMARK_TIMER_PERIOD_MS);
    uint64_t jitter_ns;

    if (timer == NULL || active_benchmark->phase != BENCHMARK_TIMER_JITTER) {
        return;
    }
    jitter_ns = (uint64_t)(last_call_time >= period_ns ? last_call_time - period_ns
                                                       : period_ns - last_call_time);
    complete_sample(jitter_ns);
}

static bool transport_open(struct uxrCustomTransport *transport)
{
    struct benchmark_transport *context = transport->args;

#ifdef BENCHMARK_SHM_TRANSPORT
    memset(context->shared, 0, sizeof(*context->shared));
    context->shared->version = BENCHMARK_SHM_VERSION;
    context->shared->area_size = (uint32_t)sizeof(*context->shared);
    context->shared->ring_capacity = BENCHMARK_SHM_RING_CAPACITY;
    context->shared->slot_size = BENCHMARK_SHM_SLOT_SIZE;
    benchmark_shm_store_release(&context->shared->guest_ready, 1U);
    __atomic_store_n(&context->shared->magic, BENCHMARK_SHM_MAGIC, __ATOMIC_RELEASE);
    return true;
#else
    context->socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (context->socket < 0) {
        transport_close(transport);
        return false;
    }
    memset(&context->agent, 0, sizeof(context->agent));
    context->agent.sin_family = AF_INET;
    context->agent.sin_port = htons(BENCHMARK_AGENT_PORT);
    if (inet_pton(AF_INET, BENCHMARK_AGENT_ADDRESS, &context->agent.sin_addr) != 1 ||
        connect(context->socket, (struct sockaddr *)&context->agent, sizeof(context->agent)) != 0) {
        transport_close(transport);
        return false;
    }
    return true;
#endif
}

static bool transport_close(struct uxrCustomTransport *transport)
{
    struct benchmark_transport *context = transport->args;
#ifdef BENCHMARK_SHM_TRANSPORT
    benchmark_shm_store_release(&context->shared->guest_ready, 0U);
    return true;
#else
    if (context->socket >= 0) {
        close(context->socket);
        context->socket = -1;
    }
    return true;
#endif
}

static size_t transport_write(struct uxrCustomTransport *transport, const uint8_t *buffer,
                              size_t length, uint8_t *error_code)
{
    struct benchmark_transport *context = transport->args;
#ifdef BENCHMARK_SHM_TRANSPORT
    while (!benchmark_shm_ring_write(&context->shared->guest_to_host, buffer, length)) {
        if (length == 0 || length > BENCHMARK_SHM_SLOT_SIZE) {
            *error_code = EMSGSIZE;
            return 0;
        }
    }
    return length;
#else
    ssize_t written = send(context->socket, buffer, length, 0);

    if (written < 0) {
        *error_code = (uint8_t)errno;
        return 0;
    }
    return (size_t)written;
#endif
}

static size_t transport_read(struct uxrCustomTransport *transport, uint8_t *buffer, size_t length,
                             int timeout_ms, uint8_t *error_code)
{
    struct benchmark_transport *context = transport->args;
#ifdef BENCHMARK_SHM_TRANSPORT
    uint64_t deadline_ns = monotonic_now_ns() + (uint64_t)(timeout_ms > 0 ? timeout_ms : 0) *
                                                       UINT64_C(1000000);

    do {
        size_t received =
            benchmark_shm_ring_read(&context->shared->host_to_guest, buffer, length);
        if (received != 0 && received != SIZE_MAX) {
            return received;
        }
        if (received == SIZE_MAX) {
            *error_code = EMSGSIZE;
            return 0;
        }
    } while (timeout_ms > 0 && monotonic_now_ns() < deadline_ns);
    return 0;
#else
    int flags = 0;
    struct timeval timeout = {
        .tv_sec = timeout_ms / 1000,
        .tv_usec = (timeout_ms % 1000) * 1000,
    };

    if (timeout_ms <= 0) {
        flags = MSG_DONTWAIT;
    } else if (setsockopt(context->socket, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) !=
               0) {
        *error_code = (uint8_t)errno;
        return 0;
    }

    ssize_t received = recv(context->socket, buffer, length, flags);
    if (received >= 0) {
        return (size_t)received;
    }
    if (errno != EAGAIN && errno != EWOULDBLOCK) {
        *error_code = (uint8_t)errno;
    }
    return 0;
#endif
}
