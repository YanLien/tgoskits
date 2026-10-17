//! AArch64 kernel-test runtime observations, absent from production builds.
//!
//! Capture is boot-scoped, bounded and append-only. It never owns scheduler,
//! VM, interrupt-controller or thread lifetimes.

use std::{
    sync::{
        OnceLock,
        atomic::{AtomicBool, AtomicU32, AtomicU64, AtomicUsize, Ordering},
    },
    vec::Vec,
};

use aarch64_cpu::asm::barrier::{SY, isb};
use ax_std::os::arceos::guard::IrqSaveGuard;

use crate::{AxVmError, AxVmResult};

const CAPACITY: usize = 16_384;
static STORE: OnceLock<Vec<CpuBuffer>> = OnceLock::new();
static ENABLED: AtomicBool = AtomicBool::new(false);
static WRITERS: AtomicUsize = AtomicUsize::new(0);
static OBSERVED_HOST_IRQ: AtomicU32 = AtomicU32::new(u32::MAX);
static DROPPED: AtomicUsize = AtomicUsize::new(0);

/// Software observation points; wake completion is deliberately not "ready".
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u64)]
pub enum EventKind {
    Binding            = 1,
    IrqKick            = 2,
    WakeBegin          = 3,
    WakeEnd            = 4,
    Running            = 5,
    Stopped            = 6,
    GuestEntryBoundary = 7,
    Marker             = 8,
    ReadyEnqueue       = 9,
    HostIrqEntry       = 10,
}

impl EventKind {
    fn from_raw(kind: u64) -> Option<Self> {
        Some(match kind {
            1 => Self::Binding,
            2 => Self::IrqKick,
            3 => Self::WakeBegin,
            4 => Self::WakeEnd,
            5 => Self::Running,
            6 => Self::Stopped,
            7 => Self::GuestEntryBoundary,
            8 => Self::Marker,
            9 => Self::ReadyEnqueue,
            10 => Self::HostIrqEntry,
            _ => return None,
        })
    }
}

/// One committed observation. Thread IDs include the scheduler generation.
#[derive(Clone, Copy, Debug)]
pub struct Event {
    pub cpu: usize,
    pub sequence: usize,
    pub ticks: u64,
    pub kind: EventKind,
    pub thread: u64,
    /// Binding: VM ID. Marker: index. ReadyEnqueue: destination CPU.
    /// HostIrqEntry: acknowledged INTID. Otherwise zero.
    pub value0: u64,
    /// Binding: vCPU ID. ReadyEnqueue: path and on_cpu flag.
    /// HostIrqEntry: 1 for the current-EL callback, 2 for low-EL pre-IAR assembly.
    /// Otherwise zero.
    pub value1: u64,
}

/// Frozen value snapshot; dropped or incomplete observations invalidate it.
#[derive(Debug)]
pub struct Snapshot {
    pub events: Vec<Event>,
    pub dropped: usize,
    pub incomplete: usize,
}

struct Slot {
    kind: AtomicU64,
    ticks: AtomicU64,
    thread: AtomicU64,
    value0: AtomicU64,
    value1: AtomicU64,
}

impl Slot {
    fn new() -> Self {
        Self {
            kind: AtomicU64::new(0),
            ticks: AtomicU64::new(0),
            thread: AtomicU64::new(0),
            value0: AtomicU64::new(0),
            value1: AtomicU64::new(0),
        }
    }
}

struct CpuBuffer {
    next: AtomicUsize,
    slots: Vec<Slot>,
}

/// Allocates before guest startup and enables capture once per kernel boot.
/// Invalid CPU counts and repeated initialization return an error.
pub fn initialize(cpu_count: usize) -> AxVmResult {
    if !(1..=64).contains(&cpu_count) {
        return Err(AxVmError::invalid_config("invalid runtime trace CPU count"));
    }
    let buffers = (0..cpu_count)
        .map(|_| CpuBuffer {
            next: AtomicUsize::new(0),
            slots: (0..CAPACITY).map(|_| Slot::new()).collect(),
        })
        .collect();
    STORE
        .set(buffers)
        .map_err(|_| AxVmError::invalid_config("runtime trace already initialized"))?;
    #[cfg(axtest)]
    ax_std::os::arceos::task::diagnostics::install_ready_trace_hook(capture_ready).map_err(
        |_| AxVmError::resource_unavailable("install ready trace", "observer already installed"),
    )?;
    ENABLED.store(true, Ordering::SeqCst);
    Ok(())
}

struct Writer;
impl Drop for Writer {
    fn drop(&mut self) {
        WRITERS.fetch_sub(1, Ordering::SeqCst);
    }
}

pub(crate) fn record(kind: EventKind, thread: u64, value0: u64, value1: u64) {
    record_at(kind, thread, value0, value1, None);
}

fn record_at(kind: EventKind, thread: u64, value0: u64, value1: u64, captured: Option<u64>) {
    if !ENABLED.load(Ordering::SeqCst) {
        return;
    }
    let _irq = IrqSaveGuard::new();
    WRITERS.fetch_add(1, Ordering::SeqCst);
    let _writer = Writer;
    // Paired with finish: a producer registering after the freeze cannot write.
    if !ENABLED.load(Ordering::SeqCst) {
        return;
    }
    let cpu = crate::host::task::current_cpu_id();
    let Some(buffer) = STORE.get().and_then(|buffers| buffers.get(cpu)) else {
        DROPPED.fetch_add(1, Ordering::Relaxed);
        return;
    };
    let sequence = buffer.next.fetch_add(1, Ordering::Relaxed);
    let Some(slot) = buffer.slots.get(sequence) else {
        DROPPED.fetch_add(1, Ordering::Relaxed);
        return;
    };
    let ticks = captured.unwrap_or_else(ax_cpu::timer::physical_counter);
    isb(SY);
    // Each reservation owns its slot forever; no slot is reused or overwritten.
    slot.ticks.store(ticks, Ordering::Relaxed);
    slot.thread.store(thread, Ordering::Relaxed);
    slot.value0.store(value0, Ordering::Relaxed);
    slot.value1.store(value1, Ordering::Relaxed);
    slot.kind.store(kind as u64, Ordering::Release);
}

/// Adds an experiment marker without acquiring scheduler or VM state.
pub fn mark(marker: u64) {
    record(EventKind::Marker, 0, marker, 0);
}

/// Closes admission and copies committed records in per-CPU reservation order.
/// A producer still in flight returns a retryable error; capture stays closed.
/// Call after joining the workload. No buffers are reclaimed before shutdown.
pub fn finish() -> AxVmResult<Snapshot> {
    ENABLED.store(false, Ordering::SeqCst);
    if WRITERS.load(Ordering::SeqCst) != 0 {
        return Err(AxVmError::resource_unavailable(
            "freeze runtime trace",
            "producer still in flight",
        ));
    }
    let buffers = STORE
        .get()
        .ok_or_else(|| AxVmError::invalid_config("runtime trace not initialized"))?;
    let mut snapshot = Snapshot {
        events: Vec::new(),
        dropped: DROPPED.load(Ordering::Acquire),
        incomplete: 0,
    };
    for (cpu, buffer) in buffers.iter().enumerate() {
        let length = buffer.next.load(Ordering::Acquire).min(CAPACITY);
        for (sequence, slot) in buffer.slots[..length].iter().enumerate() {
            let Some(kind) = EventKind::from_raw(slot.kind.load(Ordering::Acquire)) else {
                snapshot.incomplete += 1;
                continue;
            };
            snapshot.events.push(Event {
                cpu,
                sequence,
                kind,
                ticks: slot.ticks.load(Ordering::Relaxed),
                thread: slot.thread.load(Ordering::Relaxed),
                value0: slot.value0.load(Ordering::Relaxed),
                value1: slot.value1.load(Ordering::Relaxed),
            });
        }
    }
    Ok(snapshot)
}

#[cfg(axtest)]
fn capture_ready(event: ax_std::os::arceos::task::diagnostics::ReadyTraceRecord) {
    if !crate::task::owns_extension_ops(event.extension_ops) {
        return;
    }
    record(
        EventKind::ReadyEnqueue,
        event.thread.as_u64(),
        u64::from(event.destination_cpu),
        event.kind as u64 | (u64::from(event.on_cpu) << 8),
    );
}

/// Owns a test-only current- and lower-EL physical IRQ observation filter.
pub struct HostIrqCapture {
    intid: u32,
}

/// Enables one exclusive GIC PPI/SPI filter for current- and lower-EL observations.
/// Stop and synchronize the source before dropping the returned observation.
pub fn observe_host_irq(intid: u32) -> AxVmResult<HostIrqCapture> {
    if !(16..1020).contains(&intid) {
        return Err(AxVmError::invalid_config(
            "physical IRQ observation requires a standard GIC PPI or SPI",
        ));
    }
    OBSERVED_HOST_IRQ
        .compare_exchange(u32::MAX, intid, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| {
            AxVmError::resource_unavailable("observe physical IRQ", "observer already active")
        })?;
    Ok(HostIrqCapture { intid })
}

impl Drop for HostIrqCapture {
    fn drop(&mut self) {
        let _ = OBSERVED_HOST_IRQ.compare_exchange(
            self.intid,
            u32::MAX,
            Ordering::AcqRel,
            Ordering::Acquire,
        );
    }
}

pub(crate) fn current_irq_begin() -> Option<u64> {
    if OBSERVED_HOST_IRQ.load(Ordering::Acquire) == u32::MAX {
        return None;
    }
    let ticks = ax_cpu::timer::physical_counter();
    isb(SY);
    Some(ticks)
}

pub(crate) fn current_irq_acknowledged(ticks: Option<u64>, intid: u32) {
    if let Some(ticks) = ticks
        && OBSERVED_HOST_IRQ.load(Ordering::Acquire) == intid
    {
        record_at(EventKind::HostIrqEntry, 0, u64::from(intid), 1, Some(ticks));
    }
}

/// Publishes an already captured low-EL timestamp after host restoration.
pub(crate) fn lower_irq_entry(ticks: u64, acknowledged: u32) {
    // Admitted PPIs/SPIs have no SGI source bits in their raw INTID.
    if ticks != 0 && OBSERVED_HOST_IRQ.load(Ordering::Acquire) == acknowledged {
        record_at(
            EventKind::HostIrqEntry,
            0,
            u64::from(acknowledged),
            2,
            Some(ticks),
        );
    }
}
