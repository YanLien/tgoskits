#ifndef MICRO_ROS_BENCHMARK_SHM_TRANSPORT_H
#define MICRO_ROS_BENCHMARK_SHM_TRANSPORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define BENCHMARK_SHM_MAGIC UINT64_C(0x415243454d525348)
#define BENCHMARK_SHM_VERSION 1U
#define BENCHMARK_SHM_RING_CAPACITY 64U
#define BENCHMARK_SHM_SLOT_SIZE 2048U

struct benchmark_shm_slot {
    uint32_t length;
    uint32_t reserved;
    uint8_t data[BENCHMARK_SHM_SLOT_SIZE];
};

struct benchmark_shm_ring {
    uint32_t producer;
    uint32_t consumer;
    uint32_t reserved[14];
    struct benchmark_shm_slot slots[BENCHMARK_SHM_RING_CAPACITY];
};

struct benchmark_shm_area {
    uint64_t magic;
    uint32_t version;
    uint32_t area_size;
    uint32_t ring_capacity;
    uint32_t slot_size;
    uint32_t guest_ready;
    uint32_t reserved[9];
    struct benchmark_shm_ring guest_to_host;
    struct benchmark_shm_ring host_to_guest;
};

static inline uint32_t benchmark_shm_load_acquire(const uint32_t *value)
{
    return __atomic_load_n(value, __ATOMIC_ACQUIRE);
}

static inline void benchmark_shm_store_release(uint32_t *value, uint32_t next)
{
    __atomic_store_n(value, next, __ATOMIC_RELEASE);
}

static inline bool benchmark_shm_ring_write(struct benchmark_shm_ring *ring,
                                            const uint8_t *data, size_t length)
{
    uint32_t producer = __atomic_load_n(&ring->producer, __ATOMIC_RELAXED);
    uint32_t consumer = benchmark_shm_load_acquire(&ring->consumer);
    struct benchmark_shm_slot *slot;

    if (length == 0 || length > BENCHMARK_SHM_SLOT_SIZE ||
        producer - consumer >= BENCHMARK_SHM_RING_CAPACITY) {
        return false;
    }
    slot = &ring->slots[producer % BENCHMARK_SHM_RING_CAPACITY];
    memcpy(slot->data, data, length);
    slot->length = (uint32_t)length;
    benchmark_shm_store_release(&ring->producer, producer + 1U);
    return true;
}

static inline size_t benchmark_shm_ring_read(struct benchmark_shm_ring *ring, uint8_t *data,
                                             size_t capacity)
{
    uint32_t consumer = __atomic_load_n(&ring->consumer, __ATOMIC_RELAXED);
    uint32_t producer = benchmark_shm_load_acquire(&ring->producer);
    struct benchmark_shm_slot *slot;
    size_t length;

    if (consumer == producer) {
        return 0;
    }
    slot = &ring->slots[consumer % BENCHMARK_SHM_RING_CAPACITY];
    length = slot->length;
    if (length == 0 || length > BENCHMARK_SHM_SLOT_SIZE || length > capacity) {
        return SIZE_MAX;
    }
    memcpy(data, slot->data, length);
    benchmark_shm_store_release(&ring->consumer, consumer + 1U);
    return length;
}

#endif
