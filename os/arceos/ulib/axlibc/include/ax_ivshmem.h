#ifndef AX_IVSHMEM_H
#define AX_IVSHMEM_H

#include <stddef.h>
#include <stdint.h>

int ax_ivshmem_init(void);
void *ax_ivshmem_shared_memory(size_t *size);
int ax_ivshmem_notify(uint16_t peer, uint16_t vector);
int ax_ivshmem_wait(uint32_t timeout_ms);
uint64_t ax_ivshmem_irq_count(void);

#endif
