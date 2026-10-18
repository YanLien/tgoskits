//! Resource admission for the architectural timer fixture, before any bank write.

use anyhow::{Context, Result, ensure};
use ax_std::os::arceos::modules::ax_hal;

#[derive(Clone, Copy, PartialEq)]
pub enum TimerPlatform {
    Qemu,
    OrangePi5Plus,
}

impl TimerPlatform {
    pub fn detect() -> Result<Self> {
        ensure!(
            ax_cpu::registers::current_exception_level() == 2,
            "timer fixture requires EL2"
        );
        let fdt = ax_hal::dtb::get_fdt().context("timer fixture needs Host FDT")?;
        let root = fdt.all_nodes().next().context("Host FDT has no root")?;
        ensure!(root.name() == "/", "Host FDT root identity invalid");
        let platform = if root.compatibles().any(|s| s == "linux,dummy-virt") {
            Self::Qemu
        } else {
            ensure!(
                root.compatibles().any(|s| matches!(
                    s,
                    "xunlong,orangepi-5-plus" | "rockchip,rk3588-orangepi-5-plus"
                )) && root.compatibles().any(|s| s == "rockchip,rk3588"),
                "timer fixture does not admit this Host platform"
            );
            Self::OrangePi5Plus
        };
        let mut timers = fdt.find_compatible(&["arm,armv8-timer"]);
        let timer = timers.next().context("architectural timer absent")?;
        ensure!(timers.next().is_none(), "multiple architectural timers");
        ensure!(
            matches!(
                timer.find_property("status").map(|p| p.str()),
                None | Some("okay" | "ok")
            ),
            "architectural timer disabled"
        );
        let parent = timer
            .interrupt_parent()
            .context("timer interrupt parent absent")?;
        ensure!(
            parent.node.compatibles().any(|s| s == "arm,gic-v3")
                && parent
                    .node
                    .find_property("#interrupt-cells")
                    .map(|p| p.u32())
                    == Some(3),
            "timer fixture needs a three-cell GICv3 parent"
        );
        let interrupts: Vec<u32> = timer
            .find_property("interrupts")
            .context("timer needs explicit interrupt specifiers")?
            .u32_list()
            .collect();
        ensure!(
            interrupts.len() == 12,
            "timer needs four three-cell PPI specifiers"
        );
        for (cells, ppi) in interrupts.chunks_exact(3).zip([13, 14, 11, 10]) {
            ensure!(
                cells[0] == 1 && cells[1] == ppi && cells[2] & 0xf == 4 && cells[2] & !0xff0f == 0,
                "timer PPI identity or trigger mismatch"
            );
        }
        let source = ax_hal::irq::resolve_percpu_irq(ax_hal::irq::HwIrq(30))?;
        let scheduler = ax_hal::time::irq_num();
        ensure!(
            scheduler.domain == source.domain && scheduler.hwirq.0 == 26 && source != scheduler,
            "CNTP fixture requires distinct Host CNTHP PPI26"
        );
        let frequency = ax_cpu::timer::counter_frequency();
        ensure!(frequency > 0, "zero Host counter frequency");
        if let Some(property) = timer.find_property("clock-frequency") {
            let values: Vec<u32> = property.u32_list().collect();
            ensure!(
                values.len() == 1 && u64::from(values[0]) == frequency,
                "firmware timer frequency disagrees with the counter"
            );
        }
        Ok(platform)
    }

    pub fn validate_cpu(self, cpu: usize) -> Result<()> {
        ensure!(
            cpu <= 1 && cpu < ax_hal::cpu_num(),
            "invalid timer fixture CPU"
        );
        ensure!(
            self == Self::Qemu || cpu == 0,
            "native timer fixture admits CPU0 only"
        );
        Ok(())
    }

    pub fn report(self) {
        println!(
            "VIRQ_PLATFORM kind={} el=2 cpus={} physical_ppi=30 scheduler_ppi=26 frequency_hz={}",
            if self == Self::Qemu {
                "qemu_virt"
            } else {
                "orangepi5plus_rk3588"
            },
            ax_hal::cpu_num(),
            ax_cpu::timer::counter_frequency()
        );
    }
}
