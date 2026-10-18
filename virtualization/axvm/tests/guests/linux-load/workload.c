#define _GNU_SOURCE
#include <errno.h>
#include <inttypes.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

#ifndef LINUX_FENCES
#define LINUX_FENCES 0
#endif
#if LINUX_FENCES != 0 && LINUX_FENCES != 1
#error "LINUX_FENCES must be zero or one"
#endif

#if LINUX_FENCES
static volatile sig_atomic_t control_pending;

static void input_ready(int signal_number)
{
    (void)signal_number;
    control_pending = 1;
}

static int timespec_ns(const struct timespec *value, uint64_t *ns)
{
    if (value->tv_sec < 0 || value->tv_nsec < 0 || value->tv_nsec >= 1000000000L ||
        (uint64_t)value->tv_sec > (UINT64_MAX - (uint64_t)value->tv_nsec) / UINT64_C(1000000000))
        return -1;
    *ns = (uint64_t)value->tv_sec * UINT64_C(1000000000) + (uint64_t)value->tv_nsec;
    return 0;
}

static int fences_init(uint64_t *resolution)
{
    struct termios terminal;
    struct sigaction action = {0};
    struct timespec value;
    sigset_t signals;
    int flags;
    action.sa_handler = input_ready;
    action.sa_flags = SA_RESTART;
    sigemptyset(&action.sa_mask);
    sigemptyset(&signals);
    sigaddset(&signals, SIGIO);
    if (tcgetattr(STDIN_FILENO, &terminal) || sigaction(SIGIO, &action, NULL) ||
        sigprocmask(SIG_UNBLOCK, &signals, NULL))
        return -1;
    cfmakeraw(&terminal);
    flags = fcntl(STDIN_FILENO, F_GETFL);
    if (tcsetattr(STDIN_FILENO, TCSANOW, &terminal) || flags < 0 ||
        fcntl(STDIN_FILENO, F_SETOWN, getpid()) < 0 ||
        fcntl(STDIN_FILENO, F_SETFL, flags | O_NONBLOCK | O_ASYNC) < 0 ||
        clock_getres(CLOCK_MONOTONIC_RAW, &value) || timespec_ns(&value, resolution) ||
        *resolution == 0 || *resolution > 1000000)
        return -1;
    return 0;
}
#endif

#ifndef LINUX_MEMORY_BYTES
#define LINUX_MEMORY_BYTES 0
#endif
#ifndef LINUX_MEMORY_EVERY
#define LINUX_MEMORY_EVERY 1
#endif
#if LINUX_MEMORY_BYTES > 0
#if LINUX_MEMORY_BYTES < 1048576 || LINUX_MEMORY_BYTES > 67108864 || LINUX_MEMORY_BYTES % 8192
#error "memory working set must be 1..64 MiB and 8192-byte aligned"
#endif
#if LINUX_MEMORY_EVERY < 1 || LINUX_MEMORY_EVERY > 1024
#error "memory duty divisor must be 1..1024"
#endif
#endif

int main(void)
{
    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(0, &mask);
    setvbuf(stdout, NULL, _IONBF, 0);
    if (sched_setaffinity(0, sizeof(mask), &mask) != 0) {
        printf("LINUX_LOAD_FAILED operation=affinity errno=%d\n", errno);
        return 1;
    }
#if LINUX_FENCES
    uint64_t resolution;
    unsigned int control_phase = 0;
    if (fences_init(&resolution)) {
        printf("LINUX_LOAD_FAILED operation=fence_setup errno=%d\n", errno);
        return 1;
    }
#endif
#if LINUX_MEMORY_BYTES > 0
    const size_t words = LINUX_MEMORY_BYTES / sizeof(uint64_t);
    volatile uint64_t *memory = malloc(LINUX_MEMORY_BYTES);
    if (memory == NULL) {
        printf("LINUX_LOAD_FAILED operation=memory_alloc errno=%d\n", errno);
        return 1;
    }
    for (size_t i = 0; i < words; ++i)
        memory[i] = i;
    size_t cursor = 0;
    uint64_t passes = 0, memory_batches = 0, memory_checksum = 0;
#endif
    printf("LINUX_LOAD_READY version=%d guest_cpu=0 batch_iterations=8192 report_batches=256\n",
           LINUX_FENCES ? 2 : 1);
#if LINUX_MEMORY_BYTES > 0
    printf("LINUX_MEMORY_READY version=1 working_set_bytes=%llu every_batches=%u chunk_words=8192\n",
           (unsigned long long)LINUX_MEMORY_BYTES, (unsigned int)LINUX_MEMORY_EVERY);
#endif
#if LINUX_FENCES
    printf("LINUX_FENCE_READY version=1 clock=monotonic_raw resolution_ns=%" PRIu64
           " working_set_bytes=%llu every_batches=%u\n", resolution,
           (unsigned long long)LINUX_MEMORY_BYTES, (unsigned int)LINUX_MEMORY_EVERY);
#endif
    volatile uint64_t checksum = 1;
    uint64_t batches = 0;
    for (;;) {
        for (unsigned int i = 0; i < 8192; ++i)
            checksum = checksum * UINT64_C(6364136223846793005) + 1;
#if LINUX_MEMORY_BYTES > 0
        if (batches % LINUX_MEMORY_EVERY == 0) {
            for (unsigned int i = 0; i < 8192; ++i) {
                uint64_t value = memory[cursor];
                if (value != (uint64_t)cursor + passes) {
                    printf("LINUX_LOAD_FAILED operation=memory_verify index=%zu\n", cursor);
                    return 1;
                }
                memory[cursor] = value + 1;
                memory_checksum += value + 1;
                if (++cursor == words) {
                    cursor = 0;
                    ++passes;
                }
            }
            ++memory_batches;
        }
#endif
        ++batches;
#if LINUX_FENCES
        if (control_pending) {
            control_pending = 0;
            for (;;) {
                char command;
                ssize_t count = read(STDIN_FILENO, &command, 1);
                if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
                    break;
                if (count < 0 && errno == EINTR)
                    continue;
                if (count != 1 || control_phase >= 2 || command != (control_phase == 0 ? 'B' : 'E')) {
                    printf("LINUX_LOAD_FAILED operation=fence_phase\n");
                    return 1;
                }
                struct timespec stamp;
                uint64_t ns;
                if (clock_gettime(CLOCK_MONOTONIC_RAW, &stamp) || timespec_ns(&stamp, &ns) || sched_getcpu() != 0) {
                    printf("LINUX_LOAD_FAILED operation=fence_clock_or_cpu errno=%d\n", errno);
                    return 1;
                }
                const char *phase = control_phase == 0 ? "begin" : "end";
#if LINUX_MEMORY_BYTES > 0
                printf("LINUX_FENCE_REPLY version=1 phase=%s batches=%" PRIu64
                       " checksum=%" PRIu64 " time_ns=%" PRIu64 " guest_cpu=0 memory_batches=%" PRIu64
                       " logical_bytes=%" PRIu64 " memory_checksum=%" PRIu64 "\n",
                       phase, batches, checksum, ns, memory_batches,
                       memory_batches * UINT64_C(8192) * 16, memory_checksum);
#else
                printf("LINUX_FENCE_REPLY version=1 phase=%s batches=%" PRIu64
                       " checksum=%" PRIu64 " time_ns=%" PRIu64 " guest_cpu=0\n",
                       phase, batches, checksum, ns);
#endif
                ++control_phase;
            }
        }
#endif
        if (batches % 256 == 0) {
            int cpu = sched_getcpu();
            if (cpu != 0) {
                printf("LINUX_LOAD_FAILED operation=cpu guest_cpu=%d\n", cpu);
                return 1;
            }
#if LINUX_MEMORY_BYTES > 0
            printf("LINUX_LOAD_PROGRESS batches=%" PRIu64 " checksum=%" PRIu64
                   " guest_cpu=%d memory_batches=%" PRIu64 " logical_bytes=%" PRIu64
                   " memory_checksum=%" PRIu64 "\n", batches, checksum, cpu, memory_batches,
                   memory_batches * UINT64_C(8192) * 16, memory_checksum);
#else
            printf("LINUX_LOAD_PROGRESS batches=%" PRIu64 " checksum=%" PRIu64 " guest_cpu=%d\n",
                   batches, checksum, cpu);
#endif
        }
    }
}
