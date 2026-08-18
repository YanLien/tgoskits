//! QEMU ivshmem-doorbell transport used by the micro-ROS benchmark.

extern crate alloc;

use ax_sync::SpinLock;
use axklib::irq::{IrqHandle, IrqId, IrqReturn};
use mmio_api::Mmio;
use pcie::CommandRegister;
use rdrive::probe::{
    OnProbeError,
    pci::{FnOnProbe, ProbePci},
};

use crate::{
    IrqBindingLease,
    pci::PciIrqLease,
    register::{ProbeKind, ProbeLevel, ProbePriority},
};

const IVSHMEM_VENDOR_ID: u16 = 0x1af4;
const IVSHMEM_DEVICE_ID: u16 = 0x1110;
const DOORBELL_OFFSET: usize = 0x0c;

static DEVICE: SpinLock<Option<IvshmemDevice>> = SpinLock::new(None);

crate::model_register!(
    name: "QEMU ivshmem doorbell",
    level: ProbeLevel::PostKernel,
    priority: ProbePriority::DEFAULT,
    probe_kinds: &[ProbeKind::Pci {
        on_probe: probe as FnOnProbe,
    }],
);

pub struct IvshmemDevice {
    registers: Mmio,
    shared: Mmio,
    irq_lease: PciIrqLease,
    irq: IrqId,
    irq_handle: Option<IrqHandle>,
}

impl IvshmemDevice {
    pub fn shared_ptr(&self) -> *mut u8 {
        self.shared.as_ptr()
    }

    pub fn shared_size(&self) -> usize {
        self.shared.size()
    }

    pub fn notify(&self, peer: u16, vector: u16) {
        self.registers
            .write::<u32>(DOORBELL_OFFSET, (u32::from(peer) << 16) | u32::from(vector));
    }
}

fn probe(mut probe: ProbePci<'_>) -> Result<(), OnProbeError> {
    let info = probe.info();
    let endpoint = probe.endpoint_mut();
    if endpoint.vendor_id() != IVSHMEM_VENDOR_ID || endpoint.device_id() != IVSHMEM_DEVICE_ID {
        return Err(OnProbeError::NotMatch);
    }
    let registers_bar = endpoint
        .bar_mmio(0)
        .ok_or_else(|| OnProbeError::other("ivshmem BAR0 registers are missing"))?;
    let shared_bar = endpoint
        .bar_mmio(2)
        .ok_or_else(|| OnProbeError::other("ivshmem BAR2 shared memory is missing"))?;
    let irq_lease = PciIrqLease::allocate(endpoint, info, 1)?;
    let irq = irq_lease
        .binding_info()
        .irq()
        .and_then(|binding| binding.irq_id())
        .ok_or_else(|| OnProbeError::other("ivshmem MSI-X vector has no IRQ id"))?;

    endpoint.update_command(|mut command| {
        command.insert(
            CommandRegister::MEMORY_ENABLE
                | CommandRegister::BUS_MASTER_ENABLE
                | CommandRegister::INTERRUPT_DISABLE,
        );
        command
    });
    let registers = axklib::mmio::ioremap(registers_bar.start.into(), registers_bar.count())
        .map_err(|err| OnProbeError::other(alloc::format!("map ivshmem BAR0: {err}")))?;
    let shared = axklib::mmio::ioremap(shared_bar.start.into(), shared_bar.count())
        .map_err(|err| OnProbeError::other(alloc::format!("map ivshmem BAR2: {err}")))?;
    let mut slot = DEVICE.lock();
    if slot.is_some() {
        return Err(OnProbeError::other(
            "only one ivshmem doorbell device is supported",
        ));
    }
    *slot = Some(IvshmemDevice {
        registers,
        shared,
        irq_lease,
        irq,
        irq_handle: None,
    });
    log::info!(
        "registered QEMU ivshmem doorbell endpoint at {}",
        info.address
    );
    Ok(())
}

pub fn install_irq_handler(
    handler: impl FnMut(axklib::irq::IrqContext) -> IrqReturn + Send + 'static,
) -> Result<(), &'static str> {
    let mut slot = DEVICE.lock();
    let device = slot.as_mut().ok_or("ivshmem device was not probed")?;
    if device.irq_handle.is_some() {
        return Ok(());
    }
    let handle = axklib::irq::request_shared_disabled(device.irq, handler)
        .map_err(|_| "request ivshmem MSI-X IRQ failed")?;
    device.irq_lease.enable_binding_source(0);
    if axklib::irq::enable(handle).is_err() {
        let _ = axklib::irq::free(handle);
        return Err("enable ivshmem MSI-X IRQ failed");
    }
    device.irq_handle = Some(handle);
    Ok(())
}

pub fn shared_memory() -> Option<(*mut u8, usize)> {
    let slot = DEVICE.lock();
    let device = slot.as_ref()?;
    Some((device.shared_ptr(), device.shared_size()))
}

pub fn notify(peer: u16, vector: u16) -> bool {
    let slot = DEVICE.lock();
    let Some(device) = slot.as_ref() else {
        return false;
    };
    device.notify(peer, vector);
    true
}
