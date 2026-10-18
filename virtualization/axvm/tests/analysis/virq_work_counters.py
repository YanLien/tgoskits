"""Independent closed-form work checks shared by report and fence consumers."""

import re

LINUX_PROGRESS = re.compile(r"LINUX_LOAD_PROGRESS batches=(\d+) checksum=(\d+) guest_cpu=0(?: memory_batches=(\d+) logical_bytes=(\d+) memory_checksum=(\d+))?")


def checksum_after(iterations):
    """Advance the affine recurrence by exponentiation, modulo 2**64."""
    mask = (1 << 64) - 1
    multiplier, increment, checksum = 6364136223846793005, 1, 1
    while iterations:
        if iterations & 1:
            checksum = (multiplier * checksum + increment) & mask
        increment = (multiplier * increment + increment) & mask
        multiplier = multiplier * multiplier & mask
        iterations >>= 1
    return checksum


def linux_memory_expected(batches, size, every):
    """Closed-form sum of sequential read/increment/write values, modulo 2**64."""
    memory_batches = (batches + every - 1) // every
    accesses = memory_batches * 8192
    if not 0 < batches <= (1 << 64) - 1 or accesses * 16 >= 1 << 64:
        raise ValueError('Linux memory counter overflow')
    words = size // 8
    q, r = divmod(accesses, words)
    checksum = (q * words * (words + 1) // 2 + words * q * (q - 1) // 2
                + r * (r + 1) // 2 + r * q) % (1 << 64)
    return memory_batches, accesses * 16, checksum
