"""Shared selection of explicit virtual Guest firmware for both preparers."""

import os


def explicit_enabled():
    value = os.environ.get('VIRQ_EXPLICIT_DTB', '0')
    if value not in ('0', '1'):
        raise ValueError('VIRQ_EXPLICIT_DTB must be 0 or 1')
    return value == '1'


def gic_layout():
    value = os.environ.get('VIRQ_GIC_LAYOUT', 'qemu')
    if value not in ('qemu', 'rk3588'):
        raise ValueError('VIRQ_GIC_LAYOUT must be qemu or rk3588')
    if value == 'rk3588' and not explicit_enabled():
        raise ValueError('RK3588 GIC layout requires explicit Guest firmware')
    return value


def linux_host_cpu():
    """Select an admitted Linux placement without changing its Guest CPU id."""
    value = os.environ.get('VIRQ_LINUX_HOST_CPU', '3')
    if value not in ('1', '3'):
        raise ValueError('VIRQ_LINUX_HOST_CPU must be 1 or 3')
    if value == '1' and not (
        explicit_enabled()
        and os.environ.get('VIRQ_HOST_LOAD') in ('linux_cpu', 'linux_memory')
        and os.environ.get('VIRQ_TASK') == '1'
        and os.environ.get('VIRQ_TASK_WAIT') == 'blocked'
        and os.environ.get('VIRQ_SOURCE') in ('physical_timer_ppi', 'pl031_spi')
        and os.environ.get('VIRQ_IRQ_CONTEXT', 'current_el') == 'current_el'
        and os.environ.get('VIRQ_SERVICE_PLACEMENT') == 'cpu0'
    ):
        raise ValueError('Linux CPU1 sharing requires explicit firmware, blocked dual-VM tasks, current-EL physical IRQs and CPU0 services')
    return int(value)
