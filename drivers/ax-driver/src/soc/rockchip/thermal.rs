// Copyright 2026 The Axvisor Team
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

//! RK3588 thermal sampling independent of CPU OPP control.
//!
//! The single FDT probe owns the permanent TSADC mapping and prepares protected
//! conversion before publishing it. Queries only read data and protection state.

use alloc::format;
use core::{
    ptr::{NonNull, null_mut},
    sync::atomic::{AtomicPtr, Ordering},
    time::Duration,
};

use log::info;
#[cfg(feature = "rk3588-cpufreq")]
use log::warn;
use rdrive::{probe::OnProbeError, register::FdtInfo};

use crate::{mmio::iomap, register::ProbeFdt};

const TSADC_SIZE: usize = 0x400;
const TSADC_AUTO_CON: usize = 0x04;
const TSADC_AUTO_SRC_CON: usize = 0x0c;
const TSADC_HSHUT_CRU_EN: usize = 0x1c;
const TSADC_DATA0: usize = 0x2c;
const TSADC_COMP_SHUT0: usize = 0x10c;
const TSADC_INT_DEBOUNCE: usize = 0x14c;
const TSADC_SHUT_DEBOUNCE: usize = 0x150;
const TSADC_AUTO_PERIOD: usize = 0x154;
const TSADC_AUTO_PERIOD_HT: usize = 0x158;
const TSADC_CODE_MASK: u32 = 0x1ff;
const TSADC_RATE_HZ: u64 = 2_000_000;
// Linear interpolation of the BSP RK3588 table maps 120 C to ADC code 389.
const TSADC_SHUT_CODE: u32 = 389;
const TSADC_CHANNELS: usize = 7;

static TSADC_MMIO: AtomicPtr<u8> = AtomicPtr::new(null_mut());

/// An unavailable or unprotected sensor never supplies a substitute reading.
#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum TemperatureError {
    /// No successfully initialized TSADC converter is available.
    #[error("thermal converter is not ready")]
    NotReady,
    /// The ADC value is outside the characterized conversion table.
    #[error("thermal reading is outside the characterized range")]
    InvalidReading,
    /// Sampling or hardware shutdown no longer meets the admitted policy.
    #[error("thermal sampling lacks the required hardware protection")]
    Unprotected,
}

/// Physical RK3588 sensors, independent of VM and logical CPU numbering.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TemperatureSensor {
    /// The top-level SoC sensor, TSADC channel 0.
    Soc,
    /// The shared Cortex-A55 cluster sensor, TSADC channel 3.
    LittleCpu,
}

impl TemperatureSensor {
    const fn channel(self) -> usize {
        match self {
            Self::Soc => 0,
            Self::LittleCpu => 3,
        }
    }
}

crate::model_register!(
    name: "RK3588 thermal sensors",
    level: ProbeLevel::PostKernel,
    priority: ProbePriority::DEFAULT,
    probe_kinds: &[ProbeKind::Fdt {
        compatibles: &["rockchip,rk3588-tsadc"], on_probe: probe_tsadc
    }],
);

/// Reads one protected, already sampled sensor in millidegrees Celsius.
/// No clock, reset, threshold, route, OPP or sampling state is changed here.
/// A reading is instantaneous evidence, not a window maximum or thermal cap.
pub fn temperature_millidegrees(sensor: TemperatureSensor) -> Result<i32, TemperatureError> {
    // Acquire observes the completed probe; this mapping is never reclaimed.
    let mmio =
        NonNull::new(TSADC_MMIO.load(Ordering::Acquire)).ok_or(TemperatureError::NotReady)?;
    read_tsadc_temperature(mmio, sensor)
}

#[cfg(feature = "rk3588-cpufreq")]
pub(crate) fn soc_temperature_millidegrees() -> Result<i32, TemperatureError> {
    temperature_millidegrees(TemperatureSensor::Soc)
}

fn check_tsadc_sampling(mmio: NonNull<u8>, channel: usize) -> Result<(), TemperatureError> {
    let auto_con = read32(mmio, TSADC_AUTO_CON);
    if auto_con & 1 == 0 || read32(mmio, TSADC_AUTO_SRC_CON) & (1 << channel) == 0 {
        return Err(TemperatureError::NotReady);
    }
    if auto_con & ((1 << 1) | (1 << 8)) != 0 {
        return Err(TemperatureError::Unprotected);
    }
    let shut_mask = 1 << channel;
    if read32(mmio, TSADC_HSHUT_CRU_EN) & shut_mask == 0 {
        return Err(TemperatureError::Unprotected);
    }
    Ok(())
}

fn read_tsadc_temperature(
    mmio: NonNull<u8>,
    sensor: TemperatureSensor,
) -> Result<i32, TemperatureError> {
    check_tsadc_sampling(mmio, sensor.channel())?;
    let shut_code = read32(mmio, TSADC_COMP_SHUT0 + sensor.channel() * 4);
    if !(215..=TSADC_SHUT_CODE).contains(&shut_code) {
        return Err(TemperatureError::Unprotected);
    }
    code_to_millidegrees(read32(mmio, TSADC_DATA0 + sensor.channel() * 4))
        .ok_or(TemperatureError::InvalidReading)
}

/// Refreshes the runtime temperature while maintaining the host shutdown ceiling.
#[cfg(feature = "rk3588-cpufreq")]
pub(crate) fn refresh_soc_temperature_millidegrees() -> Result<i32, TemperatureError> {
    let mmio =
        NonNull::new(TSADC_MMIO.load(Ordering::Acquire)).ok_or(TemperatureError::NotReady)?;
    refresh_tsadc_temperature(mmio)
}

#[cfg(feature = "rk3588-cpufreq")]
fn refresh_tsadc_temperature(mmio: NonNull<u8>) -> Result<i32, TemperatureError> {
    check_tsadc_sampling(mmio, 0)?;
    let previous = read32(mmio, TSADC_COMP_SHUT0);
    if !(215..=395).contains(&previous) {
        return Err(TemperatureError::Unprotected);
    }
    if previous > TSADC_SHUT_CODE {
        // A passthrough thermal driver can rewrite the shared comparator.
        // Tighten only a characterized threshold, preserving stricter limits
        // and every conversion/route/polarity bit. Never admit high OPPs using
        // stale temperature or by accepting a weaker shutdown ceiling.
        write32(mmio, TSADC_COMP_SHUT0, TSADC_SHUT_CODE);
        if read32(mmio, TSADC_COMP_SHUT0) != TSADC_SHUT_CODE {
            return Err(TemperatureError::Unprotected);
        }
        warn!("TSADC shutdown threshold tightened from {previous} to {TSADC_SHUT_CODE}");
    }
    read_tsadc_temperature(mmio, TemperatureSensor::Soc)
}

fn probe_tsadc(probe: ProbeFdt<'_>) -> Result<(), OnProbeError> {
    let (info, _) = probe.into_parts();
    let (address, _) = checked_reg(&info, TSADC_SIZE)?;
    let node = info.node.as_node();
    let tshut_temp = node
        .get_property("rockchip,hw-tshut-temp")
        .and_then(|property| property.get_u32());
    let tshut_mode = node
        .get_property("rockchip,hw-tshut-mode")
        .and_then(|property| property.get_u32());
    let tshut_polarity = node
        .get_property("rockchip,hw-tshut-polarity")
        .and_then(|property| property.get_u32());
    if (tshut_temp, tshut_mode, tshut_polarity) != (Some(120_000), Some(0), Some(0)) {
        return Err(OnProbeError::other(
            "RK3588 TSADC hardware shutdown does not match board policy",
        ));
    }
    let clock = info
        .find_clock_line_by_name("tsadc")?
        .ok_or_else(|| OnProbeError::other("RK3588 TSADC clock is absent"))?;
    let pclk = info
        .find_clock_line_by_name("apb_pclk")?
        .ok_or_else(|| OnProbeError::other("RK3588 TSADC APB clock is absent"))?;
    let assigned = info
        .node
        .as_node()
        .get_property("assigned-clock-rates")
        .and_then(|property| property.get_u32());
    if assigned != Some(TSADC_RATE_HZ as u32) || clock.rate()? != TSADC_RATE_HZ {
        return Err(OnProbeError::other(
            "RK3588 TSADC is not clocked at its 2 MHz DT rate",
        ));
    }
    pclk.enable()?;
    clock.enable()?;
    let resets = info.reset_lines()?;
    if resets.len() != 2 {
        return Err(OnProbeError::other(
            "RK3588 TSADC reset references are incomplete",
        ));
    }
    for reset in resets {
        // Releasing an asserted reset is idempotent; never pulse or assert it
        // against a running thermal protection controller.
        reset.deassert()?;
    }
    let mmio = iomap(address, TSADC_SIZE)?;
    prepare_tsadc(mmio)?;
    TSADC_MMIO.store(mmio.as_ptr(), Ordering::Release);
    info!("RK3588 TSADC sampling with verified <=120 C hardware shutdown on all channels");
    Ok(())
}

fn prepare_tsadc(mmio: NonNull<u8>) -> Result<(), OnProbeError> {
    let running = read32(mmio, TSADC_AUTO_CON) & 1 != 0;
    if read32(mmio, TSADC_AUTO_CON) & (1 << 1) != 0 {
        if running {
            return Err(OnProbeError::other(
                "active RK3588 TSADC has unexpected ADC code inversion",
            ));
        }
        write32(mmio, TSADC_AUTO_CON, 1 << 17);
        if read32(mmio, TSADC_AUTO_CON) & (1 << 1) != 0 {
            return Err(OnProbeError::other(
                "RK3588 TSADC ADC code direction did not verify",
            ));
        }
    }
    if read32(mmio, TSADC_AUTO_CON) & (1 << 8) != 0 {
        // The board DTB requests low-active shutdown. Changing an active
        // controller's polarity could temporarily disarm protection.
        if running {
            return Err(OnProbeError::other(
                "active RK3588 TSADC has unexpected TSHUT polarity",
            ));
        }
        write32(mmio, TSADC_AUTO_CON, 1 << 24);
        if read32(mmio, TSADC_AUTO_CON) & (1 << 8) != 0 {
            return Err(OnProbeError::other(
                "RK3588 TSADC TSHUT polarity did not verify",
            ));
        }
    }

    if !running {
        // BSP rk_tsadcv8_initialize: 5000 cycles at 2 MHz is 2.5 ms.
        for (offset, value) in [
            (TSADC_AUTO_PERIOD, 5000),
            (TSADC_AUTO_PERIOD_HT, 5000),
            (TSADC_INT_DEBOUNCE, 4),
            (TSADC_SHUT_DEBOUNCE, 4),
        ] {
            write32(mmio, offset, value);
            if read32(mmio, offset) != value {
                return Err(OnProbeError::other(format!(
                    "RK3588 TSADC timing register {offset:#x} did not verify"
                )));
            }
        }
    }

    for channel in 0..TSADC_CHANNELS {
        let mask = 1u32 << channel;
        // Set the shutdown comparator before enabling the auto source and
        // CRU route. All three readbacks precede AUTO_EN on a stopped block.
        let threshold_offset = TSADC_COMP_SHUT0 + channel * 4;
        let previous = read32(mmio, threshold_offset);
        if running && previous < 215 {
            return Err(OnProbeError::other(format!(
                "active RK3588 TSADC channel {channel} has an unknown low shutdown code"
            )));
        }
        let shutdown_code = if running && (215..=TSADC_SHUT_CODE).contains(&previous) {
            previous
        } else {
            TSADC_SHUT_CODE
        };
        if previous != shutdown_code {
            write32(mmio, threshold_offset, shutdown_code);
        }
        if read32(mmio, threshold_offset) != shutdown_code {
            return Err(OnProbeError::other(format!(
                "RK3588 TSADC channel {channel} shutdown threshold did not verify"
            )));
        }
        write32(mmio, TSADC_HSHUT_CRU_EN, mask | (mask << 16));
        if read32(mmio, TSADC_HSHUT_CRU_EN) & mask == 0 {
            return Err(OnProbeError::other(format!(
                "RK3588 TSADC channel {channel} shutdown route did not verify"
            )));
        }
        write32(mmio, TSADC_AUTO_SRC_CON, mask | (mask << 16));
        if read32(mmio, TSADC_AUTO_SRC_CON) & mask == 0 {
            return Err(OnProbeError::other(format!(
                "RK3588 TSADC channel {channel} auto source did not verify"
            )));
        }
    }

    if !running {
        write32(mmio, TSADC_AUTO_CON, (1 << 16) | 1);
        if read32(mmio, TSADC_AUTO_CON) & 1 == 0 {
            return Err(OnProbeError::other("RK3588 TSADC AUTO_EN did not verify"));
        }
    }
    for _ in 0..50 {
        if [1, 2, 3]
            .into_iter()
            .all(|channel| code_to_millidegrees(read32(mmio, TSADC_DATA0 + channel * 4)).is_some())
        {
            return Ok(());
        }
        axklib::time::busy_wait(Duration::from_millis(1));
    }
    Err(OnProbeError::other(
        "RK3588 TSADC CPU channels did not produce valid samples",
    ))
}

fn checked_reg(info: &FdtInfo<'_>, minimum: usize) -> Result<(usize, usize), OnProbeError> {
    let reg = info
        .node
        .regs()
        .into_iter()
        .next()
        .ok_or_else(|| OnProbeError::other(format!("{} has no registers", info.node.name())))?;
    let address = usize::try_from(reg.address)
        .map_err(|_| OnProbeError::other(format!("{} address overflow", info.node.name())))?;
    let size = usize::try_from(reg.size.unwrap_or(0))
        .map_err(|_| OnProbeError::other(format!("{} size overflow", info.node.name())))?;
    if address % 4 != 0 || size < minimum || address.checked_add(size).is_none() {
        return Err(OnProbeError::other(format!(
            "{} invalid register range",
            info.node.name()
        )));
    }
    Ok((address, size))
}

fn code_to_millidegrees(code: u32) -> Option<i32> {
    // RK3588 table from the local Orange Pi BSP rockchip_thermal.c. Reject
    // sentinel values, including values outside the characterized -40..125 C.
    const POINTS: [(u32, i32); 4] = [(215, -40_000), (285, 25_000), (350, 85_000), (395, 125_000)];
    let code = code & TSADC_CODE_MASK;
    for pair in POINTS.windows(2) {
        let (low_code, low_temp) = pair[0];
        let (high_code, high_temp) = pair[1];
        if (low_code..=high_code).contains(&code) {
            return Some(
                low_temp
                    + ((code - low_code) as i32 * (high_temp - low_temp))
                        / (high_code - low_code) as i32,
            );
        }
    }
    None
}

fn read32(base: NonNull<u8>, offset: usize) -> u32 {
    // SAFETY: callers validate a permanent mapping containing each aligned
    // 32-bit register offset; volatile access is required for MMIO semantics.
    unsafe { base.as_ptr().add(offset).cast::<u32>().read_volatile() }
}

fn write32(base: NonNull<u8>, offset: usize, value: u32) {
    // SAFETY: callers validate a permanent mapping containing each aligned
    // 32-bit register offset and own these writable TSADC registers.
    unsafe {
        base.as_ptr()
            .add(offset)
            .cast::<u32>()
            .write_volatile(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rk3588_tsadc_thresholds_and_invalid_samples() {
        assert_eq!(code_to_millidegrees(285), Some(25_000));
        assert_eq!(code_to_millidegrees(350), Some(85_000));
        assert_eq!(code_to_millidegrees(299), Some(37_923));
        assert_eq!(code_to_millidegrees(0), None);
        assert_eq!(code_to_millidegrees(455), None);

        // Exercise the production refresh against volatile register storage.
        let mut registers = [0u32; TSADC_SIZE / 4];
        registers[TSADC_AUTO_CON / 4] = 1;
        registers[TSADC_AUTO_SRC_CON / 4] = 1;
        registers[TSADC_HSHUT_CRU_EN / 4] = 1;
        registers[TSADC_COMP_SHUT0 / 4] = 390;
        registers[TSADC_DATA0 / 4] = 285;
        let mmio = NonNull::new(registers.as_mut_ptr().cast()).unwrap();
        let original = registers;
        assert_eq!(
            read_tsadc_temperature(mmio, TemperatureSensor::Soc),
            Err(TemperatureError::Unprotected)
        );
        assert_eq!(registers, original, "queries must never tighten thresholds");
        registers[TSADC_COMP_SHUT0 / 4] = 350;
        assert_eq!(
            read_tsadc_temperature(mmio, TemperatureSensor::Soc),
            Ok(25_000)
        );
        registers[TSADC_AUTO_SRC_CON / 4] |= 1 << 3;
        registers[TSADC_HSHUT_CRU_EN / 4] |= 1 << 3;
        registers[(TSADC_COMP_SHUT0 + 12) / 4] = 350;
        registers[(TSADC_DATA0 + 12) / 4] = 299;
        let original = registers;
        assert_eq!(
            read_tsadc_temperature(mmio, TemperatureSensor::LittleCpu),
            Ok(37_923)
        );
        assert_eq!(registers, original);
        registers[TSADC_HSHUT_CRU_EN / 4] &= !(1 << 3);
        assert_eq!(
            read_tsadc_temperature(mmio, TemperatureSensor::LittleCpu),
            Err(TemperatureError::Unprotected)
        );
        assert_eq!(
            read_tsadc_temperature(mmio, TemperatureSensor::Soc),
            Ok(25_000)
        );
        #[cfg(feature = "rk3588-cpufreq")]
        {
            registers[TSADC_COMP_SHUT0 / 4] = 390;
            assert_eq!(refresh_tsadc_temperature(mmio), Ok(25_000));
            assert_eq!(registers[TSADC_COMP_SHUT0 / 4], TSADC_SHUT_CODE);
            registers[TSADC_DATA0 / 4] = 350;
            assert_eq!(refresh_tsadc_temperature(mmio), Ok(85_000));

            // A stricter shutdown stays intact; missing protection and unknown
            // thresholds must still reject high-OPP temperature admission.
            registers[TSADC_COMP_SHUT0 / 4] = 350;
            assert_eq!(refresh_tsadc_temperature(mmio), Ok(85_000));
            assert_eq!(registers[TSADC_COMP_SHUT0 / 4], 350);
            registers[TSADC_HSHUT_CRU_EN / 4] = 0;
            registers[TSADC_COMP_SHUT0 / 4] = 390;
            assert_eq!(
                refresh_tsadc_temperature(mmio),
                Err(TemperatureError::Unprotected)
            );
            assert_eq!(registers[TSADC_COMP_SHUT0 / 4], 390);
            registers[TSADC_HSHUT_CRU_EN / 4] = 1;
            registers[TSADC_COMP_SHUT0 / 4] = 511;
            assert_eq!(
                refresh_tsadc_temperature(mmio),
                Err(TemperatureError::Unprotected)
            );
            assert_eq!(registers[TSADC_COMP_SHUT0 / 4], 511);
        }
    }
}
