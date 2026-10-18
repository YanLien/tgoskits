//! Quiescent sensor observations; no active-chain formatting or OPP control.

use anyhow::{Context, Result, ensure};
use ax_driver::soc::{TemperatureSensor, temperature_millidegrees};

pub struct Snapshot {
    policy: &'static str,
    point: &'static str,
    begin_ticks: u64,
    end_ticks: u64,
    soc_mc: i32,
    little_mc: i32,
}

impl Snapshot {
    pub fn capture(policy: &'static str, point: &'static str) -> Result<Self> {
        let begin_ticks = super::clock::host_ticks();
        let soc_mc = temperature_millidegrees(TemperatureSensor::Soc)
            .context("required SoC temperature unavailable")?;
        let little_mc = temperature_millidegrees(TemperatureSensor::LittleCpu)
            .context("required A55 cluster temperature unavailable")?;
        let end_ticks = super::clock::host_ticks();
        ensure!(
            end_ticks >= begin_ticks,
            "thermal observation counter reversed"
        );
        Ok(Self {
            policy,
            point,
            begin_ticks,
            end_ticks,
            soc_mc,
            little_mc,
        })
    }

    pub fn report(self) {
        println!(
            "VIRQ_THERMAL_SAMPLE policy={} point={} begin_ticks={} end_ticks={} frequency_hz={} \
             soc_mc={} little_mc={}",
            self.policy,
            self.point,
            self.begin_ticks,
            self.end_ticks,
            ax_cpu::timer::counter_frequency(),
            self.soc_mc,
            self.little_mc
        );
    }
}
