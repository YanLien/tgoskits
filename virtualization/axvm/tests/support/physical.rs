//! Exclusive QEMU virt CNTP/PPI source, controlled from CPU0.

use core::marker::PhantomData;
use std::sync::{
    Arc,
    atomic::{AtomicU32, Ordering},
};

use anyhow::{Context, Result, ensure};
use ax_cpu::timer::{Timer, TimerControl, TimerKind};
use ax_std::os::arceos::{guard::IrqSaveGuard, modules::ax_hal};
use axvm::{VcpuInterruptPort, diagnostics::HostIrqCapture};

#[derive(Default)]
struct Counters {
    handled: AtomicU32,
    errors: AtomicU32,
}

pub struct PhysicalTimer {
    cpu: usize,
    irq: Option<ax_hal::irq::IrqHandle>,
    counters: Arc<Counters>,
    observation: Option<HostIrqCapture>,
    original: Option<(u64, TimerControl)>,
    _not_send_sync: PhantomData<*mut ()>,
}

impl PhysicalTimer {
    pub fn start(port: VcpuInterruptPort, cpu: usize) -> Result<Self> {
        ensure!(
            ax_hal::platform_name() == "linux,dummy-virt",
            "CNTP fixture requires QEMU virt"
        );
        ensure!(
            ax_cpu::registers::current_exception_level() == 2,
            "physical source needs EL2"
        );
        ensure!(
            ax_hal::percpu::this_cpu_id() == 0,
            "physical controller needs CPU0"
        );
        ensure!(
            cpu <= 1 && cpu < ax_hal::cpu_num(),
            "invalid physical source CPU"
        );
        let irq = ax_hal::irq::resolve_percpu_irq(ax_hal::irq::HwIrq(30))?;
        let host_irq = ax_hal::time::irq_num();
        ensure!(
            host_irq.domain == irq.domain && host_irq.hwirq.0 == 26,
            "QEMU EL2 CNTHP scheduler PPI26 is required"
        );
        ensure!(irq != host_irq, "CNTP is the host scheduler timer");
        let counters = Arc::new(Counters::default());
        let handler_counters = counters.clone();
        let handle = ax_hal::irq::request_irq(
            irq,
            ax_hal::irq::IrqRequest::new_concurrent(move |context| {
                // SAFETY: this action exclusively owns this CPU's CNTP PPI.
                // IRQ exclusion serializes all bounded task/hard-call sessions;
                // host clockevents use CNTHP and guest CNTP accesses are trapped.
                let mut timer = unsafe { Timer::current(TimerKind::Physical) };
                let pending = timer.control().contains(TimerControl::PENDING);
                timer.set_control(TimerControl::MASKED);
                if context.cpu != ax_hal::irq::CpuId(cpu) || !pending || port.pulse().is_err() {
                    handler_counters.errors.fetch_add(1, Ordering::Relaxed);
                }
                handler_counters.handled.fetch_add(1, Ordering::Release);
                ax_hal::irq::IrqReturn::Handled
            })
            .scope(ax_hal::irq::IrqScope::PerCpu {
                cpus: ax_hal::irq::CpuMask::from_cpu(ax_hal::irq::CpuId(cpu)),
            })
            .auto_enable(ax_hal::irq::AutoEnable::No),
        )
        .context("request exclusive QEMU CNTP PPI")?;
        let mut source = Self {
            cpu,
            irq: Some(handle),
            counters,
            observation: None,
            original: None,
            _not_send_sync: PhantomData,
        };
        on_cpu(cpu, Operation::SetTrigger(irq))?;
        source.original = Some(on_cpu(cpu, Operation::Snapshot)?);
        source.observation = Some(axvm::diagnostics::observe_host_irq(30)?);
        ax_hal::irq::enable_irq(handle)?;
        Ok(source)
    }

    pub fn arm(&self, sequence: u32) -> Result<u64> {
        ensure!(
            ax_hal::percpu::this_cpu_id() == 0,
            "timer controller left CPU0"
        );
        ensure!(
            self.counters.errors.load(Ordering::Acquire) == 0,
            "physical IRQ handler error"
        );
        ensure!(
            self.counters.handled.load(Ordering::Acquire) == sequence - 1,
            "unexpected physical IRQ count"
        );
        on_cpu(self.cpu, Operation::Arm).map(|(due, _)| due)
    }

    pub fn check_delivered(&self, sequence: u32) -> Result<()> {
        ensure!(
            self.counters.handled.load(Ordering::Acquire) == sequence,
            "physical source did not deliver exactly once"
        );
        ensure!(
            self.counters.errors.load(Ordering::Acquire) == 0,
            "physical source handler failed"
        );
        Ok(())
    }

    pub fn finish(mut self, policy: &str, samples: u32) -> Result<()> {
        self.check_delivered(samples)?;
        self.close()?;
        println!(
            "VIRQ_PHYSICAL_SUMMARY policy={policy} intid=30 cpu={} handled={samples} errors=0 \
             retired=1",
            self.cpu
        );
        Ok(())
    }

    fn close(&mut self) -> Result<()> {
        ensure!(
            ax_hal::percpu::this_cpu_id() == 0,
            "timer cleanup left controller CPU0"
        );
        if let Some(handle) = self.irq {
            if self.original.is_some() {
                on_cpu(self.cpu, Operation::Mask)?;
            }
            ax_hal::irq::disable_irq(handle)?;
            ax_hal::irq::synchronize_irq(handle)?;
            ax_hal::irq::free_irq(handle)?;
            self.irq = None;
        }
        // Retain the saved bank across a failed remote restore so Drop can retry.
        if let Some((compare, control)) = self.original {
            on_cpu(self.cpu, Operation::Restore(compare, control))?;
            self.original = None;
        }
        self.observation.take();
        Ok(())
    }
}

impl Drop for PhysicalTimer {
    fn drop(&mut self) {
        if let Err(error) = self.close() {
            println!("VIRQ_PHYSICAL_CLEANUP_FAILED {error:#}");
        }
    }
}

#[derive(Clone, Copy)]
enum Operation {
    SetTrigger(ax_hal::irq::IrqId),
    Snapshot,
    Arm,
    Mask,
    Restore(u64, TimerControl),
}

struct Request {
    operation: Operation,
    reply: Option<core::result::Result<(u64, TimerControl), &'static str>>,
}

fn on_cpu(cpu: usize, operation: Operation) -> Result<(u64, TimerControl)> {
    let mut request = Request {
        operation,
        reply: None,
    };
    // SAFETY: the unique, aligned stack request remains live and unmoved until
    // synchronous completion/cancellation; no caller lock is held. The callback
    // is bounded, IRQ-masked, nonallocating, and retains no pointer or Timer view.
    unsafe {
        ax_hal::irq::run_on_cpu_sync(
            ax_hal::irq::CpuId(cpu),
            operate,
            core::ptr::from_mut(&mut request).cast(),
        )?;
    }
    request
        .reply
        .context("physical hard call did not complete")?
        .map_err(anyhow::Error::msg)
}

unsafe fn operate(argument: *mut ()) {
    // SAFETY: on_cpu owns this initialized stack Request until synchronous
    // completion; it does not access the request while the callback executes.
    let request = unsafe { &mut *argument.cast::<Request>() };
    let _irq = IrqSaveGuard::new();
    if let Operation::SetTrigger(irq) = request.operation {
        request.reply = Some(
            ax_hal::irq::set_trigger(irq, ax_hal::irq::IrqTrigger::Level)
                .map(|()| (0, TimerControl::empty()))
                .map_err(|_| "set CNTP PPI trigger failed"),
        );
        return;
    }
    // SAFETY: the fixture reserved this CPU's disabled PPI before Snapshot;
    // subsequent operations retain ownership until Mask/synchronize/free, then
    // Restore. Local IRQ exclusion prevents simultaneous handler access. Guest
    // CNTP is emulated and CNTHP owns host clockevents, so no other bank user exists.
    let mut timer = unsafe { Timer::current(TimerKind::Physical) };
    request.reply = Some(match request.operation {
        Operation::Snapshot => {
            let control = timer.control();
            if control.contains(TimerControl::ENABLE) {
                Err("CNTP is already enabled")
            } else {
                Ok((timer.compare(), control))
            }
        }
        Operation::Arm => {
            let delay = ax_cpu::timer::counter_frequency() / 1000;
            if timer.control().contains(TimerControl::ENABLE) {
                Err("previous comparator remains enabled")
            } else if delay == 0 {
                Err("counter frequency is too low")
            } else if let Some(due) = timer.counter().checked_add(delay) {
                timer.set_compare(due);
                timer.set_control(TimerControl::ENABLE);
                Ok((due, TimerControl::ENABLE))
            } else {
                Err("timer deadline overflow")
            }
        }
        Operation::Mask => {
            timer.set_control(TimerControl::MASKED);
            Ok((0, TimerControl::MASKED))
        }
        Operation::Restore(compare, control) => {
            timer.set_compare(compare);
            timer.set_control(control);
            Ok((compare, control))
        }
        Operation::SetTrigger(_) => unreachable!(),
    });
}
