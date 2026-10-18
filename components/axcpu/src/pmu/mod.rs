//! Hardware performance monitoring for the current CPU.

pub use crate::arch::current::pmu::{
    CounterId, CycleCounter, CycleScopeError, EventConfig, EventSupport, Pmu, PmuError, PmuInfo,
};
