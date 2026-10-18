#include <stdint.h>
#include <stddef.h>
#include <zephyr/arch/arm64/arm-smccc.h>
#include <zephyr/irq.h>
#include <zephyr/kernel.h>
#include <zephyr/sys_clock.h>
#include <zephyr/dt-bindings/interrupt-controller/arm-gic.h>

#define SOFTWARE_VIRQ 48
#ifndef SAMPLE_COUNT
#define SAMPLE_COUNT 300
#endif
#if SAMPLE_COUNT < 1 || SAMPLE_COUNT > 1000
#error "SAMPLE_COUNT must be between 1 and 1000"
#endif
#define TIMER_IRQ 27
#ifndef TASK_MODE
#define TASK_MODE 0
#endif
#ifndef TASK_BLOCKING
#define TASK_BLOCKING 0
#endif
#ifndef TASK_PERIODIC
#define TASK_PERIODIC 0
#endif
#ifndef TASK_ROUNDS
#define TASK_ROUNDS 4096
#endif
#if TASK_PERIODIC && (!TASK_MODE || !TASK_BLOCKING)
#error "periodic tasks require blocked task mode"
#endif
#if TASK_ROUNDS < 4096 || TASK_ROUNDS > 1048576
#error "invalid task workload"
#endif
#if TASK_MODE && TASK_BLOCKING
#if TASK_PERIODIC
K_SEM_DEFINE(task_ready, 0, SAMPLE_COUNT);
#else
K_SEM_DEFINE(task_ready, 0, 1);
#endif
#endif
#define PSCI_CPU_SUSPEND_64 0xc4000001UL
#define PSCI_SYSTEM_OFF_32 0x84000008UL

/* Test-only mailbox in normal coherent guest RAM. Each word has one writer:
 * CPU0 owns ready0/parks0. CPU1 release-publishes clock replies and ISR
 * timestamps. Host owns complete/clock_request; reply payloads remain stable
 * until the next request, and each ISR slot is written only once.
 * The build tool obtains its GPA from the ELF symbol, never a guessed address.
 */
struct virq_mailbox {
	uint32_t ready0;
	uint32_t ready1;
	uint32_t received;
	uint32_t parks0;
	uint32_t complete;
	uint32_t clock_request;
	uint32_t clock_ack;
	uint32_t running_mode;
	uint64_t clock_ticks;
	uint64_t frequency;
	uint64_t isr_ticks[SAMPLE_COUNT];
	uint64_t isr_end_ticks[SAMPLE_COUNT];
#if TASK_MODE
	uint32_t task_completed;
	uint32_t task_protocol;
	uint64_t task_start_ticks[SAMPLE_COUNT];
	uint64_t task_end_ticks[SAMPLE_COUNT];
	uint64_t task_checksum[SAMPLE_COUNT];
#if TASK_PERIODIC
	uint32_t periodic_protocol;
	uint32_t periodic_rounds;
	uint64_t isr_outstanding[SAMPLE_COUNT];
	uint64_t task_outstanding[SAMPLE_COUNT];
#endif
#endif
};
struct virq_mailbox virq_mailbox;
_Static_assert(offsetof(struct virq_mailbox, clock_ticks) == 32, "clock layout");
_Static_assert(offsetof(struct virq_mailbox, isr_ticks) == 48, "ISR layout");
_Static_assert(offsetof(struct virq_mailbox, isr_end_ticks) == 48 + SAMPLE_COUNT * 8, "ISR end layout");
#if TASK_MODE
_Static_assert(offsetof(struct virq_mailbox, task_completed) == 48 + SAMPLE_COUNT * 16, "task publication layout");
_Static_assert(offsetof(struct virq_mailbox, task_start_ticks) == 56 + SAMPLE_COUNT * 16, "task start layout");
_Static_assert(offsetof(struct virq_mailbox, task_end_ticks) == 56 + SAMPLE_COUNT * 24, "task end layout");
_Static_assert(offsetof(struct virq_mailbox, task_checksum) == 56 + SAMPLE_COUNT * 32, "task checksum layout");
#if TASK_PERIODIC
_Static_assert(offsetof(struct virq_mailbox, periodic_protocol) == 56 + SAMPLE_COUNT * 40, "periodic extension");
_Static_assert(offsetof(struct virq_mailbox, isr_outstanding) == 64 + SAMPLE_COUNT * 40, "ISR backlog");
_Static_assert(offsetof(struct virq_mailbox, task_outstanding) == 64 + SAMPLE_COUNT * 48, "task backlog");
_Static_assert(sizeof(struct virq_mailbox) == 64 + SAMPLE_COUNT * 56, "periodic mailbox size");
#else
_Static_assert(sizeof(struct virq_mailbox) == 56 + SAMPLE_COUNT * 40, "task mailbox size");
#endif
#else
_Static_assert(sizeof(struct virq_mailbox) == 48 + SAMPLE_COUNT * 16, "mailbox size");
#endif

static uint64_t counter_ticks(void)
{
    uint64_t ticks;
    /* CNTVCT is direct; CNTPCT is trapped by the hypervisor. ISB and the
     * compiler memory clobber delimit the C ISR observation point. */
    __asm__ volatile("isb; mrs %0, cntvct_el0; isb" : "=r"(ticks) : : "memory");
    return ticks;
}

static void clock_reply(void)
{
    uint32_t request = __atomic_load_n(&virq_mailbox.clock_request, __ATOMIC_ACQUIRE);
    uint32_t ack = __atomic_load_n(&virq_mailbox.clock_ack, __ATOMIC_RELAXED);
    if (request != 0 && request != 33 && request != ack && request <= 65) {
        virq_mailbox.clock_ticks = counter_ticks();
        __atomic_store_n(&virq_mailbox.clock_ack, request, __ATOMIC_RELEASE);
    }
}

static void suspend_cpu(void)
{
	struct arm_smccc_res res;
	arm_smccc_hvc(PSCI_CPU_SUSPEND_64, 0, 0, 0, 0, 0, 0, 0, &res);
	if (res.a0 != 0) {
		printk("SOFTWARE VIRQ FAIL suspend=%ld\n", res.a0);
		k_panic();
	}
}

static void software_virq_isr(const void *arg)
{
	uint64_t ticks = counter_ticks();
	ARG_UNUSED(arg);
	uint32_t count = __atomic_load_n(&virq_mailbox.received, __ATOMIC_RELAXED);
	if (arch_curr_cpu()->id != 1 || count >= SAMPLE_COUNT) {
		printk("SOFTWARE VIRQ FAIL cpu=%d count=%u\n", arch_curr_cpu()->id, count);
		k_panic();
	}
	virq_mailbox.isr_ticks[count] = ticks;
#if TASK_PERIODIC
	virq_mailbox.isr_outstanding[count] = count + 1 -
		__atomic_load_n(&virq_mailbox.task_completed, __ATOMIC_ACQUIRE);
#endif
	/* Publish the end read before received. The host acknowledgement poll is
	 * therefore outside the ISR execution interval. */
	virq_mailbox.isr_end_ticks[count] = counter_ticks();
	__atomic_store_n(&virq_mailbox.received, count + 1, __ATOMIC_RELEASE);
#if TASK_MODE && TASK_BLOCKING
	k_sem_give(&task_ready);
#endif
}

static K_THREAD_STACK_DEFINE(consumer_stack, 4096);
static struct k_thread consumer_thread;

#if TASK_MODE
static void execute_task(uint32_t index)
{
#if TASK_PERIODIC
	unsigned int key = irq_lock();
#endif
	virq_mailbox.task_start_ticks[index] = counter_ticks();
#if TASK_PERIODIC
	virq_mailbox.task_outstanding[index] =
		__atomic_load_n(&virq_mailbox.received, __ATOMIC_ACQUIRE) - index;
	irq_unlock(key);
#endif
	/* Volatile local state keeps the bounded workload in the Guest thread.
	 * The configured recurrence is checked independently by the Host. */
	volatile uint32_t state = 0x12345678U;
	for (uint32_t round = 0; round < TASK_ROUNDS; ++round) {
		state = state * 1664525U + 1013904223U;
	}
	virq_mailbox.task_checksum[index] = state;
#if TASK_PERIODIC
	key = irq_lock();
#endif
	virq_mailbox.task_end_ticks[index] = counter_ticks();
	__atomic_store_n(&virq_mailbox.task_completed, index + 1, __ATOMIC_RELEASE);
#if TASK_PERIODIC
	irq_unlock(key);
#endif
}
#endif

static void consumer_entry(void *a, void *b, void *c)
{
	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);
	/* Enabling the SPI on CPU1 sets its GICv3 routing affinity to CPU1. */
	irq_enable(SOFTWARE_VIRQ);
	irq_disable(TIMER_IRQ);
    uint64_t frequency;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
    virq_mailbox.frequency = frequency;
#if defined(CONFIG_TIMER_READS_ITS_FREQUENCY_AT_RUNTIME)
    if (frequency == 0 || frequency != (uint64_t)sys_clock_hw_cycles_per_sec()) {
        printk("SOFTWARE VIRQ FAIL timer frequency\n");
        k_panic();
    }
    printk("SOFTWARE VIRQ CLOCK timer_hz=%u counter_hz=%llu\n",
           (unsigned int)sys_clock_hw_cycles_per_sec(), (unsigned long long)frequency);
#endif
#if TASK_MODE
	virq_mailbox.task_protocol = 1;
#if TASK_PERIODIC
	virq_mailbox.periodic_protocol = 1;
	virq_mailbox.periodic_rounds = TASK_ROUNDS;
#endif
#endif
	__atomic_store_n(&virq_mailbox.ready1, 1, __ATOMIC_RELEASE);
    while (__atomic_load_n(&virq_mailbox.clock_request, __ATOMIC_ACQUIRE) != 33) {
        clock_reply();
        arch_nop();
    }
#if TASK_MODE
	/* The semaphore retains an ISR token that arrives before take; the
	 * Zephyr idle thread uses trapped WFI when this consumer is blocked. */
	uint32_t completed = 0;
	while (completed < SAMPLE_COUNT) {
#if TASK_BLOCKING
		uint32_t available;
		if (k_sem_take(&task_ready, K_FOREVER) != 0) {
			printk("SOFTWARE VIRQ FAIL task take\n");
			k_panic();
		}
		available = __atomic_load_n(&virq_mailbox.received, __ATOMIC_ACQUIRE);
		if (TASK_PERIODIC ? available <= completed : available != completed + 1) {
			printk("SOFTWARE VIRQ FAIL task wake\n");
			k_panic();
		}
		execute_task(completed++);
#else
		if (__atomic_load_n(&virq_mailbox.received, __ATOMIC_ACQUIRE) > completed) {
			execute_task(completed++);
		} else {
			arch_nop();
		}
#endif
	}
#if TASK_PERIODIC
	printk("SOFTWARE VIRQ TASKS_DRAINED samples=%u\n", SAMPLE_COUNT);
#endif
#else
	while (__atomic_load_n(&virq_mailbox.received, __ATOMIC_ACQUIRE) < SAMPLE_COUNT) {
        if (__atomic_load_n(&virq_mailbox.running_mode, __ATOMIC_ACQUIRE)) {
            arch_nop();
        } else {
            suspend_cpu();
        }
	}
#endif
	/* The host acknowledges that it checked all deliveries and idle-CPU
	 * isolation before we power off. No additional interrupt is injected.
	 */
	while (!__atomic_load_n(&virq_mailbox.complete, __ATOMIC_ACQUIRE)) {
        clock_reply();
		arch_nop();
	}
	printk("SOFTWARE VIRQ COMPLETE streams=1 samples_each=%u total=%u\n",
               SAMPLE_COUNT, SAMPLE_COUNT);
	struct arm_smccc_res res;
	arm_smccc_hvc(PSCI_SYSTEM_OFF_32, 0, 0, 0, 0, 0, 0, 0, &res);
	k_panic();
}

int main(void)
{
	IRQ_CONNECT(SOFTWARE_VIRQ, 1, software_virq_isr, NULL, IRQ_TYPE_EDGE);
	k_thread_create(&consumer_thread, consumer_stack, K_THREAD_STACK_SIZEOF(consumer_stack),
			consumer_entry, NULL, NULL, NULL, K_PRIO_PREEMPT(0), 0, K_FOREVER);
	if (k_thread_cpu_pin(&consumer_thread, 1) != 0) {
		printk("SOFTWARE VIRQ FAIL pin\n");
		return 1;
	}
	k_thread_start(&consumer_thread);
	irq_disable(TIMER_IRQ);
	printk("SOFTWARE VIRQ READY suspend vector=48 samples=%u\n", SAMPLE_COUNT);
	__atomic_store_n(&virq_mailbox.ready0, 1, __ATOMIC_RELEASE);
	for (;;) {
		__atomic_fetch_add(&virq_mailbox.parks0, 1, __ATOMIC_RELEASE);
		suspend_cpu();
	}
	return 0;
}
