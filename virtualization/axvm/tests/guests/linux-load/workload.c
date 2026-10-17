#define _GNU_SOURCE
#include <errno.h>
#include <inttypes.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>

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
    printf("LINUX_LOAD_READY version=1 guest_cpu=0 batch_iterations=8192 report_batches=256\n");
    volatile uint64_t checksum = 1;
    uint64_t batches = 0;
    for (;;) {
        for (unsigned int i = 0; i < 8192; ++i)
            checksum = checksum * UINT64_C(6364136223846793005) + 1;
        ++batches;
        if (batches % 256 == 0) {
            int cpu = sched_getcpu();
            if (cpu != 0) {
                printf("LINUX_LOAD_FAILED operation=cpu guest_cpu=%d\n", cpu);
                return 1;
            }
            printf("LINUX_LOAD_PROGRESS batches=%" PRIu64 " checksum=%" PRIu64 " guest_cpu=%d\n",
                   batches, checksum, cpu);
        }
    }
}
