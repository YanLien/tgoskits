//! Boot-scoped kernel-test observations at runnable queue transitions.

use core::sync::atomic::{AtomicPtr, Ordering};

use crate::{
    sched::CpuId,
    thread::{ThreadCore, ThreadId},
};

/// Transition path, distinct from policy eligibility or physical execution.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u64)]
pub enum ReadyKind {
    DirectWake         = 1,
    OnRunQueueWake     = 2,
    OwnerWake          = 3,
    OwnerYield         = 4,
    OwnerPreempted     = 5,
    OwnerReplenished   = 6,
    OwnerMigrated      = 7,
    OwnerPolicyChanged = 8,
}

/// Values observed after queue/state updates and before the rq lock is released.
#[derive(Clone, Copy, Debug)]
pub struct ReadyTraceRecord {
    pub thread: ThreadId,
    pub destination_cpu: u32,
    pub kind: ReadyKind,
    /// True for a context still owning a CPU, including put_prev observations.
    pub on_cpu: bool,
    /// Identity only. Never dereference or reconstruct an extension from it.
    pub extension_ops: usize,
}

/// Runs under scheduler locks: no allocation, blocking, printing, notification,
/// scheduler reentry or registration changes are allowed in the observer.
pub type ReadyTraceHook = fn(ReadyTraceRecord);

static READY_HOOK: AtomicPtr<()> = AtomicPtr::new(core::ptr::null_mut());

/// A different boot-lifetime observer is already installed.
#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
#[error("a different ready trace observer is already installed")]
pub struct ReadyObserverAlreadyInstalled;

/// Installs one static function for the kernel boot, before starting a workload.
/// Reinstalling the same function succeeds; replacement/unregistration is not
/// supported because producers can concurrently execute the existing function.
pub fn install_ready_trace_hook(hook: ReadyTraceHook) -> Result<(), ReadyObserverAlreadyInstalled> {
    let pointer = hook as *mut ();
    match READY_HOOK.compare_exchange(
        core::ptr::null_mut(),
        pointer,
        Ordering::AcqRel,
        Ordering::Acquire,
    ) {
        Ok(_) => Ok(()),
        Err(installed) if installed == pointer => Ok(()),
        Err(_) => Err(ReadyObserverAlreadyInstalled),
    }
}

pub(crate) fn record_ready(core: &ThreadCore, destination: CpuId, kind: ReadyKind, on_cpu: bool) {
    let pointer = READY_HOOK.load(Ordering::Acquire);
    if pointer.is_null() {
        return;
    }
    let extension_ops = core
        .extension_view()
        .map_or(0, |extension| extension.ops() as *const _ as usize);
    let record = ReadyTraceRecord {
        thread: core.id(),
        destination_cpu: destination.as_u32(),
        kind,
        on_cpu,
        extension_ops,
    };
    // SAFETY: the non-null value can only be published by installation from
    // this exact ReadyTraceHook type. It is never replaced or reclaimed; a fn
    // pointer has no captured environment and its code remains linked through
    // shutdown. This round-trip preserves the original Rust calling convention.
    let hook: ReadyTraceHook = unsafe { core::mem::transmute(pointer) };
    hook(record);
}
