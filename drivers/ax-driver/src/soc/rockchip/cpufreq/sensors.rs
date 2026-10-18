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

//! RK3588 CPU OPP OTP-bin access; thermal conversion has one separate owner.

use alloc::{format, vec::Vec};
use core::{
    ptr::NonNull,
    sync::atomic::{AtomicBool, AtomicU32, Ordering},
    time::Duration,
};

use log::info;
use rdrive::{probe::OnProbeError, register::FdtInfo};

pub(super) use super::super::thermal::{
    refresh_soc_temperature_millidegrees, soc_temperature_millidegrees,
};
use crate::{mmio::iomap, register::ProbeFdt};

const OTP_SIZE: usize = 0x400;
const CRU_GATE18: usize = 0x800 + 18 * 4;
// The board DTB omits CLK_OTPC_ARB and CLK_OTPC_AUTO_RD_G. Linux's RK3588
// clock data places these alongside the three clocks listed by the DTB.
const OTP_GATE_BITS: u32 = (1 << 9) | (1 << 10) | (1 << 11) | (1 << 12) | (1 << 13);

const OTP_AUTO_CTRL: usize = 0x04;
const OTP_AUTO_EN: usize = 0x08;
const OTP_DOUT0: usize = 0x20;
const OTP_INT_ST: usize = 0x84;
const OTP_RD_DONE: u32 = 1 << 1;
const OTP_NONSECURE_BASE: u32 = 0x300;
const OTP_BURST_ONE: u32 = 1 << 8;
const OTP_SPEC_OFFSET: usize = 6;
const OTP_CACHE_SIZE: usize = 0x80;
const OTP_POLL_LIMIT_US: usize = 10_000;

static OTP_WORDS: [AtomicU32; OTP_CACHE_SIZE / 4] =
    [const { AtomicU32::new(0) }; OTP_CACHE_SIZE / 4];
static OTP_READY: AtomicBool = AtomicBool::new(false);
/// A sensor failure keeps the associated high-frequency OPPs unavailable.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SensorError {
    NotReady,
    InvalidReading,
    Timeout,
}

crate::model_register!(
    name: "RK3588 CPU DVFS silicon sensors",
    level: ProbeLevel::PostKernel,
    priority: ProbePriority::DEFAULT,
    probe_kinds: &[ProbeKind::Fdt { compatibles: &["rockchip,rk3588-otp"], on_probe: probe_otp }],
);

/// Return a bounded slice of the OTP nonsecure area cached at probe time.
///
/// The cache covers all CPU OPP nvmem cells in the Orange Pi board DTB. A
/// failed, unstable, or incomplete OTP read publishes no bytes.
pub fn read_otp_bytes(offset: usize, len: usize) -> Result<Vec<u8>, SensorError> {
    let end = offset.checked_add(len).ok_or(SensorError::InvalidReading)?;
    if end > OTP_CACHE_SIZE {
        return Err(SensorError::InvalidReading);
    }
    if !OTP_READY.load(Ordering::Acquire) {
        return Err(SensorError::NotReady);
    }
    let mut bytes = Vec::with_capacity(len);
    for index in offset..end {
        let word = OTP_WORDS[index / 4].load(Ordering::Relaxed);
        bytes.push(word.to_le_bytes()[index % 4]);
    }
    Ok(bytes)
}

/// Return the raw OTP specification byte (bit[4:0] selects the CPU SKU).
pub fn otp_specification_byte() -> Result<u8, SensorError> {
    Ok(read_otp_bytes(OTP_SPEC_OFFSET, 1)?[0])
}

/// Return the CPU SKU serial from the five low bits of the OTP cell.
pub fn sku_serial() -> Result<u8, SensorError> {
    Ok(otp_specification_byte()? & 0x1f)
}

fn probe_otp(probe: ProbeFdt<'_>) -> Result<(), OnProbeError> {
    let (info, _) = probe.into_parts();
    let (otp_address, _) = checked_reg(&info, OTP_SIZE)?;
    let cru = rdrive::fdt_ref()
        .ok_or_else(|| OnProbeError::other("RK3588 FDT is unavailable"))?
        .find_compatible(&["rockchip,rk3588-cru"])
        .into_iter()
        .next()
        .ok_or_else(|| OnProbeError::other("RK3588 OTP has no CRU node"))?;
    let cru_phandle = cru
        .as_node()
        .phandle()
        .ok_or_else(|| OnProbeError::other("RK3588 CRU has no phandle"))?;
    let clocks = info.clocks()?;
    let selectors = clocks
        .iter()
        .map(|clock| clock.select())
        .collect::<Vec<_>>();
    if clocks.iter().any(|clock| clock.phandle != cru_phandle)
        || (selectors.as_slice() != [Some(150), Some(149), Some(153)]
            && selectors.as_slice() != [Some(150), Some(149), Some(151), Some(153)])
    {
        return Err(OnProbeError::other(
            "unexpected RK3588 OTP clock references",
        ));
    }
    let cru_reg = cru
        .regs()
        .into_iter()
        .next()
        .ok_or_else(|| OnProbeError::other("RK3588 CRU has no register range"))?;
    let cru_address = usize::try_from(cru_reg.address)
        .map_err(|_| OnProbeError::other("RK3588 CRU address overflow"))?;
    let cru_size = usize::try_from(cru_reg.size.unwrap_or(0))
        .map_err(|_| OnProbeError::other("RK3588 CRU size overflow"))?;
    if cru_size < CRU_GATE18 + 4 {
        return Err(OnProbeError::other(
            "RK3588 CRU gate register is outside range",
        ));
    }
    let cru_mmio = iomap(cru_address, CRU_GATE18 + 4)?;
    enable_otp_clocks(cru_mmio)?;

    let otp_mmio = iomap(otp_address, OTP_SIZE)?;
    for (word_offset, word) in OTP_WORDS.iter().enumerate() {
        let first = read_otp_word(otp_mmio, word_offset).map_err(|error| {
            OnProbeError::other(format!(
                "RK3588 OTP word {word_offset} read failed: {error:?}"
            ))
        })?;
        let second = read_otp_word(otp_mmio, word_offset).map_err(|error| {
            OnProbeError::other(format!(
                "RK3588 OTP word {word_offset} reread failed: {error:?}"
            ))
        })?;
        if first != second {
            return Err(OnProbeError::other(format!(
                "RK3588 OTP word {word_offset} was unstable"
            )));
        }
        if word_offset == OTP_SPEC_OFFSET / 4 && (first == 0 || first == u32::MAX) {
            return Err(OnProbeError::other(
                "RK3588 OTP specification word is invalid",
            ));
        }
        word.store(first, Ordering::Relaxed);
    }
    OTP_READY.store(true, Ordering::Release);
    let specification = otp_specification_byte().map_err(|_| OnProbeError::other("OTP cache"))?;
    info!("RK3588 OTP specification byte: {specification:#04x}");
    Ok(())
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

fn enable_otp_clocks(cru: NonNull<u8>) -> Result<(), OnProbeError> {
    // RK3588 CRU gates are write-masked: the upper 16 bits select which gate
    // bits to clear. This preserves all other CRU clients sharing gate 18.
    write32(cru, CRU_GATE18, OTP_GATE_BITS << 16);
    axklib::time::busy_wait(Duration::from_micros(5));
    if read32(cru, CRU_GATE18) & OTP_GATE_BITS != 0 {
        return Err(OnProbeError::other("RK3588 OTP clocks did not ungate"));
    }
    Ok(())
}

fn read_otp_word(otp: NonNull<u8>, word_offset: usize) -> Result<u32, SensorError> {
    let address = OTP_NONSECURE_BASE + word_offset as u32;
    write32(otp, OTP_INT_ST, OTP_RD_DONE);
    if read32(otp, OTP_INT_ST) & OTP_RD_DONE != 0 {
        return Err(SensorError::InvalidReading);
    }
    write32(otp, OTP_AUTO_CTRL, (address << 16) | OTP_BURST_ONE);
    write32(otp, OTP_AUTO_EN, 1);
    for _ in 0..OTP_POLL_LIMIT_US {
        if read32(otp, OTP_INT_ST) & OTP_RD_DONE != 0 {
            write32(otp, OTP_INT_ST, OTP_RD_DONE);
            return Ok(read32(otp, OTP_DOUT0));
        }
        axklib::time::busy_wait(Duration::from_micros(1));
    }
    Err(SensorError::Timeout)
}

fn read32(base: NonNull<u8>, offset: usize) -> u32 {
    // SAFETY: callers validate a permanent mapping containing each aligned
    // 32-bit register offset; volatile access is required for MMIO semantics.
    unsafe { base.as_ptr().add(offset).cast::<u32>().read_volatile() }
}

fn write32(base: NonNull<u8>, offset: usize, value: u32) {
    // SAFETY: callers validate a permanent mapping containing each aligned
    // 32-bit register offset and own these writable OTP/CRU registers.
    unsafe {
        base.as_ptr()
            .add(offset)
            .cast::<u32>()
            .write_volatile(value)
    }
}
