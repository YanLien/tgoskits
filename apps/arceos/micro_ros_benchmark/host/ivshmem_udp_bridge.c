#define _GNU_SOURCE

#include <arpa/inet.h>
#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/eventfd.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#define BENCHMARK_SHM_RING_CAPACITY 64U
#define BENCHMARK_SHM_SLOT_SIZE 2048U
#define BENCHMARK_SHM_REGION_SIZE (512U * 1024U)
#include "../c/shm_transport.h"

#define DEFAULT_SOCKET_PATH "/tmp/micro-ros-ivshmem.sock"
#define DEFAULT_SHM_PATH "/dev/shm/micro-ros-ivshmem.mem"
#define DEFAULT_AGENT_ADDRESS "127.0.0.1"
#define DEFAULT_AGENT_PORT 8888
#define SHM_SIZE BENCHMARK_SHM_REGION_SIZE
#define MAX_EVENTS 2

static volatile sig_atomic_t stopping;

static void stop_bridge(int signal_number)
{
    (void)signal_number;
    stopping = 1;
}

static int send_protocol_message(int socket_fd, int64_t value, int passed_fd)
{
    uint64_t encoded = htole64((uint64_t)value);
    struct iovec iov = {.iov_base = &encoded, .iov_len = sizeof(encoded)};
    char control[CMSG_SPACE(sizeof(int))] = {0};
    struct msghdr message = {.msg_iov = &iov, .msg_iovlen = 1};

    if (passed_fd >= 0) {
        struct cmsghdr *header;

        message.msg_control = control;
        message.msg_controllen = sizeof(control);
        header = CMSG_FIRSTHDR(&message);
        header->cmsg_level = SOL_SOCKET;
        header->cmsg_type = SCM_RIGHTS;
        header->cmsg_len = CMSG_LEN(sizeof(int));
        memcpy(CMSG_DATA(header), &passed_fd, sizeof(passed_fd));
    }
    return sendmsg(socket_fd, &message, MSG_NOSIGNAL) == (ssize_t)sizeof(encoded) ? 0 : -1;
}

static int create_server(const char *path)
{
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    int descriptor = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);

    if (descriptor < 0 || strlen(path) >= sizeof(address.sun_path)) {
        return -1;
    }
    memcpy(address.sun_path, path, strlen(path) + 1);
    unlink(path);
    if (bind(descriptor, (struct sockaddr *)&address, sizeof(address)) != 0 ||
        listen(descriptor, 1) != 0) {
        close(descriptor);
        return -1;
    }
    return descriptor;
}

static int connect_agent(const char *address, unsigned port)
{
    struct sockaddr_in agent = {.sin_family = AF_INET, .sin_port = htons((uint16_t)port)};
    int descriptor = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, IPPROTO_UDP);

    if (descriptor < 0 || inet_pton(AF_INET, address, &agent.sin_addr) != 1 ||
        connect(descriptor, (struct sockaddr *)&agent, sizeof(agent)) != 0) {
        if (descriptor >= 0) {
            close(descriptor);
        }
        return -1;
    }
    return descriptor;
}

static void drain_eventfd(int descriptor)
{
    uint64_t value;

    while (read(descriptor, &value, sizeof(value)) == (ssize_t)sizeof(value)) {
    }
}

static bool notify_guest(int descriptor)
{
    uint64_t value = 1;

    return write(descriptor, &value, sizeof(value)) == (ssize_t)sizeof(value) ||
           errno == EAGAIN;
}

static bool forward_guest_packets(struct benchmark_shm_area *shared, int agent_fd,
                                  uint64_t *packet_count)
{
    uint8_t packet[BENCHMARK_SHM_SLOT_SIZE];
    size_t length;

    while ((length = benchmark_shm_ring_read(&shared->guest_to_host, packet,
                                             sizeof(packet))) != 0) {
        ssize_t sent;

        if (length == SIZE_MAX) {
            fputs("invalid guest packet length\n", stderr);
            return false;
        }
        do {
            sent = send(agent_fd, packet, length, 0);
        } while (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) && !stopping);
        if (sent != (ssize_t)length) {
            perror("forward guest packet");
            return false;
        }
        ++*packet_count;
    }
    return true;
}

static bool forward_agent_packets(struct benchmark_shm_area *shared, int agent_fd,
                                  int guest_irq_fd, uint64_t *packet_count,
                                  uint64_t *interrupt_count)
{
    uint8_t packet[BENCHMARK_SHM_SLOT_SIZE];
    ssize_t received;

    while ((received = recv(agent_fd, packet, sizeof(packet), MSG_DONTWAIT)) > 0) {
        while (!benchmark_shm_ring_write(&shared->host_to_guest, packet, (size_t)received)) {
            if (!notify_guest(guest_irq_fd) || stopping) {
                return false;
            }
            sched_yield();
        }
        if (!notify_guest(guest_irq_fd)) {
            perror("notify guest");
            return false;
        }
        ++*packet_count;
        ++*interrupt_count;
    }
    if (received < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
        perror("receive Agent packet");
        return false;
    }
    return true;
}

int main(int argc, char **argv)
{
    const char *socket_path = argc > 1 ? argv[1] : DEFAULT_SOCKET_PATH;
    const char *shm_path = argc > 2 ? argv[2] : DEFAULT_SHM_PATH;
    const char *agent_address = argc > 3 ? argv[3] : DEFAULT_AGENT_ADDRESS;
    unsigned agent_port = argc > 4 ? (unsigned)strtoul(argv[4], NULL, 10) : DEFAULT_AGENT_PORT;
    struct benchmark_shm_area *shared;
    struct epoll_event events[MAX_EVENTS];
    struct epoll_event event;
    uint64_t guest_kicks = 0;
    uint64_t guest_packets = 0;
    uint64_t agent_packets = 0;
    uint64_t guest_interrupts = 0;
    int server_fd = -1, client_fd = -1, shm_fd = -1;
    int host_kick_fd = -1, guest_irq_fd = -1, agent_fd = -1, epoll_fd = -1;
    int result = 1;

    signal(SIGINT, stop_bridge);
    signal(SIGTERM, stop_bridge);
    shm_fd = open(shm_path, O_CREAT | O_TRUNC | O_RDWR | O_CLOEXEC, 0600);
    if (shm_fd < 0 || ftruncate(shm_fd, SHM_SIZE) != 0) {
        perror("create ivshmem file");
        goto out;
    }
    shared = mmap(NULL, SHM_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, shm_fd, 0);
    if (shared == MAP_FAILED) {
        perror("map ivshmem file");
        goto out;
    }
    server_fd = create_server(socket_path);
    host_kick_fd = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
    guest_irq_fd = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
    agent_fd = connect_agent(agent_address, agent_port);
    if (server_fd < 0 || host_kick_fd < 0 || guest_irq_fd < 0 || agent_fd < 0) {
        perror("initialize ivshmem bridge");
        goto unmap;
    }
    printf("IVSHMEM_BRIDGE_WAIT socket=%s shm=%s agent=%s:%u\n", socket_path, shm_path,
           agent_address, agent_port);
    fflush(stdout);
    client_fd = accept4(server_fd, NULL, NULL, SOCK_CLOEXEC);
    if (client_fd < 0 || send_protocol_message(client_fd, 0, -1) != 0 ||
        send_protocol_message(client_fd, 0, -1) != 0 ||
        send_protocol_message(client_fd, -1, shm_fd) != 0 ||
        send_protocol_message(client_fd, 1, host_kick_fd) != 0 ||
        send_protocol_message(client_fd, 0, guest_irq_fd) != 0) {
        perror("ivshmem handshake");
        goto unmap;
    }
    epoll_fd = epoll_create1(EPOLL_CLOEXEC);
    event.events = EPOLLIN;
    event.data.fd = host_kick_fd;
    if (epoll_fd < 0 || epoll_ctl(epoll_fd, EPOLL_CTL_ADD, host_kick_fd, &event) != 0) {
        perror("watch host kick eventfd");
        goto unmap;
    }
    event.data.fd = agent_fd;
    if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, agent_fd, &event) != 0) {
        perror("watch Agent socket");
        goto unmap;
    }
    while (!stopping && __atomic_load_n(&shared->magic, __ATOMIC_ACQUIRE) != BENCHMARK_SHM_MAGIC) {
        int ready = epoll_wait(epoll_fd, events, MAX_EVENTS, 1000);
        if (ready < 0 && errno != EINTR) {
            perror("wait for guest initialization");
            goto unmap;
        }
        drain_eventfd(host_kick_fd);
    }
    if (stopping || shared->version != BENCHMARK_SHM_VERSION ||
        shared->area_size != sizeof(*shared)) {
        fputs("invalid or missing guest shared-memory header\n", stderr);
        goto unmap;
    }
    printf("IVSHMEM_BRIDGE_READY mode=doorbell area_size=%zu\n", sizeof(*shared));
    fflush(stdout);
    while (!stopping && benchmark_shm_load_acquire(&shared->guest_done) == 0) {
        int ready = epoll_wait(epoll_fd, events, MAX_EVENTS, -1);

        if (ready < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("epoll_wait");
            goto unmap;
        }
        for (int index = 0; index < ready; ++index) {
            if (events[index].data.fd == host_kick_fd) {
                drain_eventfd(host_kick_fd);
                ++guest_kicks;
                if (!forward_guest_packets(shared, agent_fd, &guest_packets)) {
                    goto unmap;
                }
            } else if (events[index].data.fd == agent_fd &&
                       !forward_agent_packets(shared, agent_fd, guest_irq_fd, &agent_packets,
                                              &guest_interrupts)) {
                goto unmap;
            }
        }
    }
    printf("IVSHMEM_BRIDGE_STATS guest_kicks=%llu guest_packets=%llu agent_packets=%llu "
           "guest_interrupts=%llu\n",
           (unsigned long long)guest_kicks, (unsigned long long)guest_packets,
           (unsigned long long)agent_packets, (unsigned long long)guest_interrupts);
    result = 0;

unmap:
    munmap(shared, SHM_SIZE);
out:
    if (epoll_fd >= 0) close(epoll_fd);
    if (agent_fd >= 0) close(agent_fd);
    if (guest_irq_fd >= 0) close(guest_irq_fd);
    if (host_kick_fd >= 0) close(host_kick_fd);
    if (client_fd >= 0) close(client_fd);
    if (server_fd >= 0) close(server_fd);
    if (shm_fd >= 0) close(shm_fd);
    unlink(socket_path);
    puts("IVSHMEM_BRIDGE_STOPPED");
    return result;
}
