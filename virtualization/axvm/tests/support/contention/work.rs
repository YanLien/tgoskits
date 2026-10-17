//! Worker-owned operations; neither buffers nor pointers leave this module.

use std::vec::Vec;

use anyhow::{Context, Result, ensure};

pub const CPU_ITERATIONS: u64 = 8192;
pub const MEMORY_WORDS_PER_BATCH: usize = 1024;
pub const MEMORY_BYTES_PER_BATCH: usize = MEMORY_WORDS_PER_BATCH * 8;

#[derive(Clone, Copy)]
pub enum Workload {
    Cpu,
    Memory { bytes: usize, cpu: usize },
}

impl Workload {
    pub(super) fn cpu(self) -> usize {
        match self {
            Self::Cpu => 1,
            Self::Memory { cpu, .. } => cpu,
        }
    }

    pub(super) fn validate(self) -> Result<()> {
        if let Self::Memory { bytes, cpu } = self {
            ensure!(
                matches!(cpu, 2 | 3),
                "memory worker must use a dedicated fixture CPU"
            );
            ensure!(
                (1024 * 1024..=64 * 1024 * 1024).contains(&bytes)
                    && bytes.is_multiple_of(MEMORY_BYTES_PER_BATCH),
                "invalid memory working set"
            );
        }
        Ok(())
    }
}

pub(super) enum WorkState {
    Cpu { checksum: u64 },
    Memory { words: Vec<u64>, cursor: usize },
}

pub(super) enum WorkResult {
    Cpu {
        checksum: u64,
    },
    Memory {
        bytes: usize,
        checksum: u64,
        verified_words: usize,
        read_bytes: u64,
        write_bytes: u64,
    },
}

impl WorkState {
    pub(super) fn new(spec: Workload) -> Result<Self> {
        match spec {
            Workload::Cpu => Ok(Self::Cpu { checksum: 1 }),
            Workload::Memory { bytes, .. } => {
                let len = bytes / 8;
                let mut words = Vec::new();
                words
                    .try_reserve_exact(len)
                    .context("allocate memory working set")?;
                words.extend((0..len).map(|index| index as u64));
                Ok(Self::Memory { words, cursor: 0 })
            }
        }
    }

    pub(super) fn run_batch(&mut self) {
        match self {
            Self::Cpu { checksum } => {
                for _ in 0..CPU_ITERATIONS {
                    *checksum = std::hint::black_box(
                        checksum.wrapping_mul(6364136223846793005).wrapping_add(1),
                    );
                }
            }
            Self::Memory { words, cursor } => {
                for word in &mut words[*cursor..*cursor + MEMORY_WORDS_PER_BATCH] {
                    let pointer = word as *mut u64;
                    // SAFETY: the safe slice iterator supplies one aligned,
                    // initialized word in this worker's exclusive live Vec.
                    // No other task, guest or DMA agent has its address. These
                    // accesses finish before yielding or freeing the buffer.
                    unsafe {
                        let value = pointer.read_volatile();
                        pointer.write_volatile(value.wrapping_add(1));
                    }
                }
                *cursor += MEMORY_WORDS_PER_BATCH;
                if *cursor == words.len() {
                    *cursor = 0;
                }
            }
        }
    }

    pub(super) fn finish(self, batches: u64) -> Result<WorkResult> {
        match self {
            Self::Cpu { checksum } => Ok(WorkResult::Cpu { checksum }),
            Self::Memory { words, .. } => {
                let chunks = words.len() / MEMORY_WORDS_PER_BATCH;
                let sweeps = batches / chunks as u64;
                let extra_words = (batches % chunks as u64) as usize * MEMORY_WORDS_PER_BATCH;
                let mut checksum = 0u64;
                for (index, actual) in words.iter().enumerate() {
                    let expected = (index as u64)
                        .wrapping_add(sweeps)
                        .wrapping_add(u64::from(index < extra_words));
                    ensure!(
                        *actual == expected,
                        "memory working set verification failed at word {index}"
                    );
                    checksum = checksum.wrapping_add(*actual);
                }
                let bytes = words.len() * 8;
                let read_bytes = batches
                    .checked_mul(MEMORY_BYTES_PER_BATCH as u64)
                    .context("memory byte count overflow")?;
                Ok(WorkResult::Memory {
                    bytes,
                    checksum,
                    verified_words: words.len(),
                    read_bytes,
                    write_bytes: read_bytes,
                })
            }
        }
    }
}
