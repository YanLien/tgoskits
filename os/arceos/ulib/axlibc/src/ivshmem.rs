use core::{
    ffi::c_void,
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};

use ax_hal::irq::IrqReturn;
use ax_task::IrqNotify;

static NOTIFY: IrqNotify = IrqNotify::new();
static IRQ_COUNT: AtomicU64 = AtomicU64::new(0);

#[unsafe(no_mangle)]
pub extern "C" fn ax_ivshmem_init() -> i32 {
    match ax_driver::ivshmem::install_irq_handler(|_| {
        IRQ_COUNT.fetch_add(1, Ordering::Relaxed);
        NOTIFY.notify_irq();
        IrqReturn::Handled
    }) {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn ax_ivshmem_shared_memory(size: *mut usize) -> *mut c_void {
    let Some((address, length)) = ax_driver::ivshmem::shared_memory() else {
        return core::ptr::null_mut();
    };
    if !size.is_null() {
        unsafe { size.write(length) };
    }
    address.cast()
}

#[unsafe(no_mangle)]
pub extern "C" fn ax_ivshmem_notify(peer: u16, vector: u16) -> i32 {
    if ax_driver::ivshmem::notify(peer, vector) {
        0
    } else {
        -1
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn ax_ivshmem_wait(timeout_ms: u32) -> i32 {
    if timeout_ms == 0 {
        return 0;
    }
    (!NOTIFY.wait_timeout(Duration::from_millis(u64::from(timeout_ms)))) as i32
}

#[unsafe(no_mangle)]
pub extern "C" fn ax_ivshmem_irq_count() -> u64 {
    IRQ_COUNT.load(Ordering::Relaxed)
}
