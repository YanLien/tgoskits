#define _POSIX_C_SOURCE 200809L

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "../c/shm_transport.h"

#define DEFAULT_RAM_PATH "/dev/shm/arceos-micro-ros-benchmark.mem"
#define DEFAULT_AGENT_ADDRESS "127.0.0.1"
#define DEFAULT_AGENT_PORT 8888

static volatile sig_atomic_t stopping;

static void stop_bridge(int signal_number)
{
    (void)signal_number;
    stopping = 1;
}

static void sleep_ms(long milliseconds)
{
    struct timespec delay = {.tv_sec = milliseconds / 1000,
                             .tv_nsec = milliseconds % 1000 * 1000000L};
    (void)nanosleep(&delay, NULL);
}

static int wait_for_ram(const char *path)
{
    int descriptor;

    while (!stopping) {
        descriptor = open(path, O_RDWR);
        if (descriptor >= 0) {
            return descriptor;
        }
        if (errno != ENOENT) {
            perror("open shared RAM");
            return -1;
        }
        sleep_ms(10);
    }
    return -1;
}

static struct benchmark_shm_area *find_shared_area(uint8_t *ram, size_t ram_size)
{
    while (!stopping) {
        for (size_t offset = 0; offset + sizeof(struct benchmark_shm_area) <= ram_size;
             offset += sizeof(uint64_t)) {
            struct benchmark_shm_area *candidate = (struct benchmark_shm_area *)(ram + offset);
            uint64_t magic = __atomic_load_n(&candidate->magic, __ATOMIC_ACQUIRE);

            if (magic == BENCHMARK_SHM_MAGIC && candidate->version == BENCHMARK_SHM_VERSION &&
                candidate->area_size == sizeof(*candidate) &&
                candidate->ring_capacity == BENCHMARK_SHM_RING_CAPACITY &&
                candidate->slot_size == BENCHMARK_SHM_SLOT_SIZE) {
                printf("SHM_BRIDGE_READY offset=0x%zx area_size=%zu\n", offset,
                       sizeof(*candidate));
                fflush(stdout);
                return candidate;
            }
        }
        sleep_ms(10);
    }
    return NULL;
}

static int connect_agent(const char *address, unsigned port)
{
    struct sockaddr_in agent = {.sin_family = AF_INET, .sin_port = htons((uint16_t)port)};
    int descriptor = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK, IPPROTO_UDP);

    if (descriptor < 0) {
        perror("socket");
        return -1;
    }
    if (inet_pton(AF_INET, address, &agent.sin_addr) != 1 ||
        connect(descriptor, (struct sockaddr *)&agent, sizeof(agent)) != 0) {
        perror("connect Agent");
        close(descriptor);
        return -1;
    }
    return descriptor;
}

int main(int argc, char **argv)
{
    const char *ram_path = argc > 1 ? argv[1] : DEFAULT_RAM_PATH;
    const char *agent_address = argc > 2 ? argv[2] : DEFAULT_AGENT_ADDRESS;
    unsigned agent_port = argc > 3 ? (unsigned)strtoul(argv[3], NULL, 10) : DEFAULT_AGENT_PORT;
    struct stat ram_stat;
    struct benchmark_shm_area *shared;
    uint8_t packet[BENCHMARK_SHM_SLOT_SIZE];
    uint8_t *ram;
    int ram_fd;
    int agent_fd;

    signal(SIGINT, stop_bridge);
    signal(SIGTERM, stop_bridge);
    printf("SHM_BRIDGE_WAIT ram=%s agent=%s:%u\n", ram_path, agent_address, agent_port);
    fflush(stdout);
    ram_fd = wait_for_ram(ram_path);
    if (ram_fd < 0 || fstat(ram_fd, &ram_stat) != 0) {
        perror("stat shared RAM");
        return 1;
    }
    ram = mmap(NULL, (size_t)ram_stat.st_size, PROT_READ | PROT_WRITE, MAP_SHARED, ram_fd, 0);
    if (ram == MAP_FAILED) {
        perror("mmap shared RAM");
        return 1;
    }
    shared = find_shared_area(ram, (size_t)ram_stat.st_size);
    agent_fd = connect_agent(agent_address, agent_port);
    if (shared == NULL || agent_fd < 0) {
        return 1;
    }

    while (!stopping) {
        size_t length;
        ssize_t received;

        if (benchmark_shm_load_acquire(&shared->guest_done) != 0) {
            break;
        }
        if (benchmark_shm_load_acquire(&shared->guest_ready) == 0) {
            sleep_ms(1);
            continue;
        }
        while ((length = benchmark_shm_ring_read(&shared->guest_to_host, packet,
                                                 sizeof(packet))) != 0) {
            ssize_t sent;

            if (length == SIZE_MAX) {
                fputs("invalid guest packet length\n", stderr);
                stopping = 1;
                break;
            }
            do {
                sent = send(agent_fd, packet, length, 0);
            } while (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) && !stopping);
            if (sent != (ssize_t)length) {
                perror("forward guest packet");
                stopping = 1;
                break;
            }
        }
        while ((received = recv(agent_fd, packet, sizeof(packet), MSG_DONTWAIT)) > 0) {
            while (!benchmark_shm_ring_write(&shared->host_to_guest, packet, (size_t)received) &&
                   !stopping) {
            }
        }
        if (received < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
            perror("receive Agent packet");
            break;
        }
    }

    close(agent_fd);
    munmap(ram, (size_t)ram_stat.st_size);
    close(ram_fd);
    puts("SHM_BRIDGE_STOPPED");
    return 0;
}
