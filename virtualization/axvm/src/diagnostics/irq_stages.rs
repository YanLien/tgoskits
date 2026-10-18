//! Correlated test-only spans; these values never own physical IRQ tokens.

use core::marker::PhantomData;

use super::{EventKind, OBSERVED_HOST_IRQ, Ordering, record};

#[derive(Clone, Copy)]
pub(crate) struct ObservedIrq {
    entry_ticks: u64,
    intid: u32,
}

/// Reuses the boot-scoped filter without reading any hardware state.
/// Call only within the original IRQ-masked, CPU-pinned transaction.
pub(crate) fn observe_irq(entry_ticks: u64, intid: u32) -> Option<ObservedIrq> {
    (entry_ticks != 0 && OBSERVED_HOST_IRQ.load(Ordering::Acquire) == intid)
        .then_some(ObservedIrq { entry_ticks, intid })
}

impl ObservedIrq {
    pub(crate) fn dispatch(self) -> IrqStage {
        self.begin(EventKind::IrqDispatchBegin, EventKind::IrqDispatchEnd)
    }

    pub(crate) fn timer_sync(self) -> IrqStage {
        self.begin(EventKind::TimerSyncBegin, EventKind::TimerSyncEnd)
    }

    fn begin(self, begin: EventKind, end: EventKind) -> IrqStage {
        record(begin, 0, u64::from(self.intid), self.entry_ticks);
        IrqStage {
            irq: self,
            end,
            _cpu_local: PhantomData,
        }
    }
}

/// A control-flow interval, including on error; not proof of IRQ success.
/// It must end on the same CPU before the enclosing IRQ guard is released.
#[must_use]
pub(crate) struct IrqStage {
    irq: ObservedIrq,
    end: EventKind,
    _cpu_local: PhantomData<*mut ()>,
}

impl Drop for IrqStage {
    fn drop(&mut self) {
        record(self.end, 0, u64::from(self.irq.intid), self.irq.entry_ticks);
    }
}
