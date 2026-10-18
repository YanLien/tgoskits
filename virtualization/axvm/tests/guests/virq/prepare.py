#!/usr/bin/env python3
"""Build the pinned Zephyr guest and the resources of the `vcpu_runtime` case.

The script only prepares build inputs for the `axvm` `vcpu_runtime` ktest case.
It compiles the fixed Zephyr revision, derives the guest entry point and the
`virq_mailbox` address from the produced ELF, and writes the VM description
(`vm.toml`) together with the host-initramfs fixture
(`resources/tests/vcpu-runtime.toml`). It never starts the Axvisor host, never
runs QEMU and never judges test output: the ktest suite marker decides pass and
fail at runtime.

The pinned Zephyr checkout, the GNU Arm 10.3-2021.07 toolchain and the Python
virtualenv used by CMake live in one cache directory so that a machine or CI
job without local tools can reproduce the same guest build. `ZEPHYR_BASE`,
`CROSS_COMPILE` and `AXBUILD_TARGET_DIR` are honoured, and every path can be
overridden on the command line.
"""

import argparse
import hashlib
import importlib.util
import os
import re
from pathlib import Path
import subprocess
import sys
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from guest_firmware import explicit_enabled, gic_layout, linux_host_cpu

ZEPHYR_REVISION = "32229d0b6cc60a1906307311b8e79ec483ad1e88"
ZEPHYR_REPOSITORY = "https://github.com/zephyrproject-rtos/zephyr"
TOOLCHAIN_ARCHIVE_URL = (
    "https://developer.arm.com/-/media/Files/downloads/gnu-a/10.3-2021.07/binrel/"
    "gcc-arm-10.3-2021.07-x86_64-aarch64-none-elf.tar.xz"
)
TOOLCHAIN_ROOT_NAME = "gcc-arm-10.3-2021.07-x86_64-aarch64-none-elf"
# The old standalone workflow pinned these versions; keep the same set so the
# guest build stays byte-comparable with the previous runs.
PINNED_PYTHON_PACKAGES = (
    "cmake==4.4.3",
    "ninja==1.13.2",
    "pyelftools==0.33",
    "PyYAML==6.0.3",
    "packaging==26.3",
    "pykwalify==1.8.0",
)
BOARD = "qemu_cortex_a53/qemu_cortex_a53/smp"
MAILBOX_SYMBOL = "virq_mailbox"
def sample_count() -> int:
    """One build input shared by Guest layout and generated Host resources."""
    value = os.environ.get("VIRQ_SAMPLES", "300")
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 1000:
        raise ValueError("VIRQ_SAMPLES must be an integer between 1 and 1000")
    return int(value)


def task_enabled() -> bool:
    value = os.environ.get("VIRQ_TASK", "0")
    if value not in ("0", "1"):
        raise ValueError("VIRQ_TASK must be 0 or 1")
    return value == "1"


def task_deadline_ns() -> int:
    value = os.environ.get("VIRQ_TASK_DEADLINE_US", "10000")
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 1_000_000:
        raise ValueError("VIRQ_TASK_DEADLINE_US must be between 1 and 1000000")
    return int(value) * 1000


def task_wait_mode() -> str:
    mode = os.environ.get("VIRQ_TASK_WAIT", "spin")
    if mode not in ("spin", "blocked") or (mode == "blocked" and not task_enabled()):
        raise ValueError("VIRQ_TASK_WAIT must be spin, or blocked with VIRQ_TASK=1")
    return mode


def periodic_settings():
    period = os.environ.get("VIRQ_PERIOD_US", "0")
    rounds = os.environ.get("VIRQ_TASK_ROUNDS", "4096")
    if not period.isascii() or not period.isdecimal() or not rounds.isascii() or not rounds.isdecimal():
        raise ValueError("period and task rounds must be decimal integers")
    period, rounds = int(period), int(rounds)
    if (period != 0 and not 100 <= period <= 1000000) or not 4096 <= rounds <= 1048576:
        raise ValueError("period or workload out of range")
    if period and (not task_enabled() or task_wait_mode() != "blocked"):
        raise ValueError("periodic release requires blocked tasks")
    if not period and rounds != 4096:
        raise ValueError("non-periodic tasks retain 4096 rounds")
    return period, rounds


def mailbox_size() -> int:
    if periodic_settings()[0]:
        return 64 + sample_count() * 56
    return 56 + sample_count() * 40 if task_enabled() else 48 + sample_count() * 16

GUEST_RAM_START = 0x4000_0000
GUEST_RAM_SIZE = 0x0800_0000
DTB_LOAD_ADDR = 0x47E0_0000
VM_ID = 2
VM_CPU_NUM = 2
VM_NAME = "zephyr-vcpu-runtime"


def repo_root() -> Path:
    """Workspace root derived from this file, independent of the cwd."""
    return Path(__file__).resolve().parents[5]


def run(command: Sequence[str], *, env: dict[str, str] | None = None) -> None:
    """Run one preparation command and fail loudly with its own output."""
    result = subprocess.run(command, env=env, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"command failed with status {result.returncode}: {' '.join(command)}")


def target_dir() -> Path:
    """Axbuild target directory, `AXBUILD_TARGET_DIR` or `<repo>/target`."""
    configured = os.environ.get("AXBUILD_TARGET_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return repo_root() / "target"


def default_output() -> Path:
    return target_dir() / "axbuild/axvm/vcpu-runtime"


def default_cache() -> Path:
    configured = os.environ.get("VIRQ_CACHE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return target_dir() / "axbuild/axvm/vcpu-runtime-cache"


def python_tools_dir(cache: Path) -> Path:
    """Return the `bin` directory of the pinned build virtualenv."""
    venv = cache / "venv"
    stamp = venv / "requirements.sha256"
    signature = hashlib.sha256("\n".join(PINNED_PYTHON_PACKAGES).encode()).hexdigest()
    if not stamp.is_file() or stamp.read_text().strip() != signature:
        venv.parent.mkdir(parents=True, exist_ok=True)
        print(f"[virq] creating build virtualenv {venv}")
        if not (venv / "bin/python3").is_file():
            run([sys.executable, "-m", "venv", str(venv)])
        run(
            [
                str(venv / "bin/pip"),
                "install",
                "--disable-pip-version-check",
                *PINNED_PYTHON_PACKAGES,
            ]
        )
        stamp.write_text(signature + "\n")
    return venv / "bin"


def ensure_python_runtime(cache: Path) -> Path:
    """Re-execute this script inside the cached build virtualenv.

    CMake, Ninja, PyYAML and pyelftools all come from the same pinned
    virtualenv, so a runner only needs a `python3` able to create virtualenvs
    instead of preinstalled distribution packages.
    """
    venv = cache / "venv"
    interpreter = python_tools_dir(cache) / "python3"
    if Path(sys.prefix).resolve() == venv.resolve():
        return interpreter
    print(f"[virq] re-executing under {interpreter}")
    os.execv(str(interpreter), [str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]])
    raise AssertionError("os.execv returned unexpectedly")


def git(source: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(source), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def clone_pinned(source: Path) -> None:
    """Clone exactly the pinned revision into the cache directory."""
    source.parent.mkdir(parents=True, exist_ok=True)
    print(f"[virq] cloning Zephyr {ZEPHYR_REVISION} into {source}")
    run(["git", "init", "--quiet", str(source)])
    run(["git", "-C", str(source), "remote", "add", "origin", ZEPHYR_REPOSITORY])
    try:
        run(
            [
                "git",
                "-C",
                str(source),
                "fetch",
                "--depth",
                "1",
                "origin",
                ZEPHYR_REVISION,
            ]
        )
    except RuntimeError:
        print("[virq] shallow fetch of the pinned revision failed; fetching all refs")
        run(["git", "-C", str(source), "fetch", "origin"])
    run(["git", "-C", str(source), "checkout", "--detach", ZEPHYR_REVISION])


def verify_zephyr_source(source: Path) -> None:
    """Require the pinned revision and a clean tracked tree before building."""
    if not (source / "CMakeLists.txt").is_file():
        raise RuntimeError(f"{source} is not a Zephyr checkout")
    revision = git(source, "rev-parse", "HEAD").strip()
    if revision != ZEPHYR_REVISION:
        raise RuntimeError(f"expected Zephyr {ZEPHYR_REVISION}, found {revision} in {source}")
    dirty = git(source, "status", "--porcelain").strip()
    if dirty:
        raise RuntimeError(
            f"Zephyr sources in {source} are modified:\n{dirty}\n"
            "use a clean checkout of the pinned revision"
        )


def ensure_zephyr_source(cache: Path, override: Path | None) -> Path:
    """Resolve the Zephyr sources from the CLI, `ZEPHYR_BASE` or the cache."""
    if override is not None:
        source = override
    else:
        configured = os.environ.get("ZEPHYR_BASE")
        source = Path(configured).expanduser().resolve() if configured else cache / "zephyr"
        if not (source / "CMakeLists.txt").is_file() and not configured:
            clone_pinned(source)
    verify_zephyr_source(source)
    return source


def install_toolchain(cache: Path) -> str:
    """Download and unpack the pinned GNU Arm bare-metal toolchain."""
    root = cache / "toolchain"
    prefix = root / TOOLCHAIN_ROOT_NAME / "bin/aarch64-none-elf-"
    archive = root / Path(TOOLCHAIN_ARCHIVE_URL).name
    if not Path(f"{prefix}gcc").is_file():
        root.mkdir(parents=True, exist_ok=True)
        if not archive.is_file():
            print(f"[virq] downloading {TOOLCHAIN_ARCHIVE_URL}")
            run(["curl", "-fL", "--retry", "3", "--output", str(archive), TOOLCHAIN_ARCHIVE_URL])
        expected = os.environ.get("VIRQ_TOOLCHAIN_SHA256")
        if expected:
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if digest != expected.casefold():
                raise RuntimeError(
                    f"toolchain archive {archive} has sha256 {digest}, expected {expected}"
                )
        print(f"[virq] unpacking {archive}")
        run(["tar", "-xJf", str(archive), "-C", str(root)])
    if not Path(f"{prefix}gcc").is_file():
        raise RuntimeError(f"{prefix}gcc is missing after unpacking {archive}")
    return str(prefix)


def ensure_cross_compile(cache: Path, override: str | None) -> str:
    """Resolve an absolute CROSS_COMPILE prefix for the guest build."""
    prefix = override or os.environ.get("CROSS_COMPILE") or install_toolchain(cache)
    if not Path(prefix).is_absolute():
        raise RuntimeError(f"CROSS_COMPILE must be an absolute prefix, got {prefix}")
    if not Path(f"{prefix}gcc").is_file():
        raise RuntimeError(f"{prefix}gcc is missing; pass a full toolchain prefix")
    return prefix


def report_toolchain(prefix: str) -> None:
    version = subprocess.run(
        [f"{prefix}gcc", "--version"], check=False, capture_output=True, text=True
    ).stdout.splitlines()
    print(f"[virq] CROSS_COMPILE={prefix} {version[0] if version else 'unknown version'}")


def build_guest(
    source_dir: Path,
    build_dir: Path,
    zephyr_base: Path,
    cross_compile: str,
    tools_dir: Path,
    python: Path,
    jobs: str,
) -> Path:
    """Configure and build the Zephyr guest, returning the produced ELF."""
    env = dict(os.environ)
    env["ZEPHYR_BASE"] = str(zephyr_base)
    env["ZEPHYR_TOOLCHAIN_VARIANT"] = "cross-compile"
    # Keep the build from picking up unrelated west modules.
    env["WEST"] = "NOTFOUND"
    env["PATH"] = os.pathsep.join([str(tools_dir), env.get("PATH", "")])
    cmake = tools_dir / "cmake"
    build_dir.mkdir(parents=True, exist_ok=True)
    run(
        [
            str(cmake),
            "--fresh",
            "-GNinja",
            "-S",
            str(source_dir),
            "-B",
            str(build_dir),
            f"-DBOARD={BOARD}",
            f"-DVIRQ_SAMPLES={sample_count()}",
            f"-DVIRQ_TASK={int(task_enabled())}",
            f"-DVIRQ_TASK_BLOCKING={int(task_wait_mode() == 'blocked')}",
            f"-DVIRQ_TASK_PERIODIC={int(periodic_settings()[0] != 0)}",
            f"-DVIRQ_TASK_ROUNDS={periodic_settings()[1]}",
            f"-DCONFIG_TIMER_READS_ITS_FREQUENCY_AT_RUNTIME={'y' if explicit_enabled() else 'n'}",
            "-DWEST=NOTFOUND",
            "-DCONFIG_MINIMAL_LIBC=y",
            f"-DCROSS_COMPILE={cross_compile}",
            f"-DPython3_EXECUTABLE={python}",
        ] + ([f"-DDTC_OVERLAY_FILE={source_dir / 'rk3588.overlay'}"]
             if gic_layout() == 'rk3588' else []),
        env=env,
    )
    run([str(cmake), "--build", str(build_dir), "-j", jobs], env=env)
    elf = build_dir / "zephyr/zephyr.elf"
    if not elf.is_file():
        raise RuntimeError(f"the guest build did not produce {elf}")
    return elf


def inspect_guest(elf: Path) -> tuple[int, int]:
    """Read the entry point and mailbox address and enforce the RAM contract."""
    from elftools.elf.elffile import ELFFile

    with elf.open("rb") as stream:
        image = ELFFile(stream)
        entry = int(image.header.e_entry)
        symbols = image.get_section_by_name(".symtab")
        if symbols is None:
            raise RuntimeError(f"{elf} has no symbol table; cannot locate {MAILBOX_SYMBOL}")
        matches = symbols.get_symbol_by_name(MAILBOX_SYMBOL)
        if not matches:
            raise RuntimeError(f"{elf} does not define {MAILBOX_SYMBOL}")
        symbol = matches[0]
        mailbox = int(symbol["st_value"])
        size = int(symbol["st_size"])
    expected_size = mailbox_size()
    if size != expected_size:
        raise RuntimeError(f"{MAILBOX_SYMBOL} is {size} bytes, expected {expected_size}")
    end = GUEST_RAM_START + GUEST_RAM_SIZE
    if not GUEST_RAM_START <= mailbox or mailbox + expected_size > end:
        raise RuntimeError(
            f"{MAILBOX_SYMBOL} at 0x{mailbox:x} does not fit guest RAM "
            f"[0x{GUEST_RAM_START:x}, 0x{end:x})"
        )
    if not GUEST_RAM_START <= entry < end:
        raise RuntimeError(f"entry point 0x{entry:x} is outside guest RAM [0x{GUEST_RAM_START:x}, 0x{end:x})")
    return entry, mailbox


def write_vm_config(output: Path, kernel: Path, entry: int) -> Path:
    """Write the VM description consumed by the host initramfs bundle."""
    # `zephyr.bin` is the flat image; keep the historical RAM, DTB and entry
    # layout unchanged. The path stays relative so the whole output directory
    # can be moved or archived as one resource bundle.
    relative_kernel = kernel.relative_to(output)
    firmware = 'phys_cpu_sets = [1, 2]\n' if explicit_enabled() else ''
    dtb = 'dtb_path = "guest/zephyr/zephyr.dtb"\n' if explicit_enabled() else ''
    config = output / "vm.toml"
    config.write_text(
        f"""[base]
id = {VM_ID}
name = "{VM_NAME}"
guest_type = "virtualized"
cpu_num = {VM_CPU_NUM}
phys_cpu_ids = [0, 1]
{firmware}\
[kernel]
entry_point = 0x{entry:x}
kernel_path = "{relative_kernel.as_posix()}"
kernel_load_addr = 0x{GUEST_RAM_START:x}
dtb_load_addr = 0x{DTB_LOAD_ADDR:x}
{dtb}\
memory_regions = [[0x{GUEST_RAM_START:x}, 0x{GUEST_RAM_SIZE:08x}, 0x7, 0]]
[devices]
passthrough = []
disabled = []
"""
    )
    return config


def append_boot_failure_regions(fixture: Path, elf: Path) -> None:
    """Declare bounded read-only diagnostic ranges from the actual Guest ELF."""
    enabled = os.environ.get("VIRQ_BOOT_FAILURE_MEMORY", "0")
    if enabled not in ("0", "1"):
        raise ValueError("VIRQ_BOOT_FAILURE_MEMORY must be 0 or 1")
    if enabled == "0":
        return
    from elftools.elf.elffile import ELFFile

    config = elf.with_name(".config").read_text()
    stack_size = int(re.search(r"^CONFIG_ISR_STACK_SIZE=(\d+)$", config, re.M).group(1))
    with elf.open("rb") as stream:
        symbols = ELFFile(stream).get_section_by_name(".symtab")
        def symbol(name):
            matches = symbols.get_symbol_by_name(name)
            if not matches or len(matches) != 1:
                raise ValueError("missing or ambiguous diagnostic symbol: "+name)
            return matches[0]
        stack = symbol("z_interrupt_stacks")
        if stack_size > int(stack["st_size"]):
            raise ValueError("ISR stack range exceeds ELF symbol")
        data_start = int(symbol("__data_start")["st_value"])
        data_end = int(symbol("__data_region_end")["st_value"])
        regions = [("irq_stack_cpu0", int(stack["st_value"]), stack_size),
                   ("initialized_data", data_start, (data_end-data_start+15)//16*16)]
    for name, start, size in regions:
        if not (0 < size <= 4096 and size % 16 == 0
                and GUEST_RAM_START <= start < start+size <= GUEST_RAM_START+GUEST_RAM_SIZE):
            raise ValueError("invalid boot failure range: "+name)
    with fixture.open("a") as stream:
        for name, start, size in regions:
            stream.write(f'\n[[boot_failure_regions]]\nname = "{name}"\naddress = {start}\nsize = {size}\n')


def write_test_resources(output: Path, entry: int, mailbox: int) -> Path:
    """Write the initramfs fixture read by the `vcpu_runtime` axtest target."""
    linux_cpu = linux_host_cpu()
    recording = os.environ.get("VIRQ_RECORDING", "on")
    if recording not in ("on", "off"):
        raise ValueError("VIRQ_RECORDING must be on or off")
    scenario = os.environ.get("VIRQ_HOST_LOAD", "baseline")
    period_us, task_rounds = periodic_settings()
    if scenario not in ("baseline", "cpu_same_core", "cpu_continuous", "memory_cross_core", "linux_cpu", "linux_memory"):
        raise ValueError(f"unsupported VIRQ_HOST_LOAD: {scenario}")
    source_kind = os.environ.get("VIRQ_SOURCE", "software")
    if source_kind not in ("software", "physical_timer_ppi", "pl031_spi"):
        raise ValueError(f"unsupported VIRQ_SOURCE: {source_kind}")
    service_placement = os.environ.get("VIRQ_SERVICE_PLACEMENT", "unrestricted")
    if service_placement not in ("unrestricted", "cpu0", "cpu1", "cpu2"):
        raise ValueError(f"unsupported VIRQ_SERVICE_PLACEMENT: {service_placement}")
    irq_context = os.environ.get("VIRQ_IRQ_CONTEXT", "current_el")
    if irq_context not in ("current_el", "guest_running"):
        raise ValueError(f"unsupported VIRQ_IRQ_CONTEXT: {irq_context}")
    if irq_context == "guest_running" and (service_placement != "cpu2" or source_kind != "physical_timer_ppi" or scenario not in ("baseline", "memory_cross_core")):
        raise ValueError("guest_running requires baseline or memory_cross_core, physical_timer_ppi and cpu2 services")
    if scenario in ("linux_cpu", "linux_memory") and (source_kind not in ("pl031_spi", "physical_timer_ppi") or service_placement != "cpu0" or irq_context != "current_el"):
        raise ValueError("Linux load requires current_el, physical source and cpu0 services")
    irq_service = os.environ.get("VIRQ_IRQ_SERVICE", "off")
    if irq_service not in ("off", "inherit", "bounded"):
        raise ValueError(f"unsupported VIRQ_IRQ_SERVICE: {irq_service}")
    irq_service_rounds = int(os.environ.get("VIRQ_IRQ_SERVICE_ROUNDS", "8"))
    irq_service_window_us = int(os.environ.get("VIRQ_IRQ_SERVICE_WINDOW_US", "1000"))
    if not 1 <= irq_service_rounds <= 256 or not 100 <= irq_service_window_us <= 100000:
        raise ValueError("IRQ service dispatch limit out of range")
    witness = os.environ.get("VIRQ_INVERSION_WITNESS", "0")
    if witness not in ("0", "1"):
        raise ValueError("VIRQ_INVERSION_WITNESS must be 0 or 1")
    inversion_witness = witness == "1"
    if inversion_witness and (scenario != "baseline" or source_kind != "physical_timer_ppi" or irq_context != "current_el" or service_placement != "cpu0"):
        raise ValueError("inversion witness requires baseline/current_el/PPI/CPU0 services")
    if period_us and (scenario not in ("linux_cpu", "linux_memory") or source_kind not in ("pl031_spi", "physical_timer_ppi") or irq_context != "current_el" or service_placement != "cpu0" or inversion_witness):
        raise ValueError("periodic fixture requires dual-VM current_el physical source and CPU0 services")
    irq_pressure = os.environ.get("VIRQ_IRQ_PRESSURE", "off")
    period = os.environ.get("VIRQ_IRQ_PRESSURE_PERIOD_US", "2000")
    burst = os.environ.get("VIRQ_IRQ_PRESSURE_BURST", "2")
    if irq_pressure not in ("off", "sgi") or not period.isascii() or not period.isdecimal() or not burst.isascii() or not burst.isdecimal():
        raise ValueError("invalid IRQ pressure selection or integer setting")
    irq_pressure_period_us, irq_pressure_burst = int(period), int(burst)
    if not 100 <= irq_pressure_period_us <= 1000000 or not 1 <= irq_pressure_burst <= 8:
        raise ValueError("IRQ pressure settings out of range")
    if irq_pressure == "sgi" and (scenario not in ("linux_cpu", "linux_memory") or source_kind not in ("pl031_spi", "physical_timer_ppi") or service_placement != "cpu0" or irq_context != "current_el" or inversion_witness or not task_enabled() or task_wait_mode() != "blocked"):
        raise ValueError("SGI pressure requires blocked dual-VM current_el physical source and CPU0 services")
    memory_bytes = int(os.environ.get("VIRQ_MEMORY_BYTES", str(16*1024*1024)))
    if not 1024*1024 <= memory_bytes <= 64*1024*1024 or memory_bytes % 8192:
        raise ValueError(f"unsupported VIRQ_MEMORY_BYTES: {memory_bytes}")
    guest_rtc_unused = False
    if source_kind == "pl031_spi":
        guest_config = (output / "guest/zephyr/.config").read_text()
        guest_rtc_unused = ("# CONFIG_COUNTER is not set" in guest_config
                            and "# CONFIG_RTC is not set" in guest_config)
        if not guest_rtc_unused:
            raise ValueError("pl031_spi requires Guest RTC/counter drivers disabled")
    linux_memory_bytes, linux_memory_every, linux_fences_enabled = 0, 1, False
    if scenario in ("linux_cpu", "linux_memory"):
        spec = importlib.util.spec_from_file_location("linux_load_prepare", Path(__file__).resolve().parent.parent / "linux-load/prepare.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        linux_memory_bytes, linux_memory_every = module.memory_settings()
        linux_fences_enabled = module.fences_enabled()
    elif os.environ.get("VIRQ_LINUX_FENCES", "0") != "0":
        raise ValueError("Linux fences require a Linux peer")
    resources = output / "resources/tests"
    resources.mkdir(parents=True, exist_ok=True)
    fixture = resources / "vcpu-runtime.toml"
    fixture.write_text(
        f"""# Generated by virtualization/axvm/tests/guests/virq/prepare.py.
# `entry` and `mailbox` stay fixed for the pinned guest revision.
samples = {sample_count()}
recording = "{recording}"
task_enabled = {str(task_enabled()).lower()}
task_wait = "{task_wait_mode()}"
task_deadline_ns = {task_deadline_ns()}
task_rounds = {task_rounds}
period_us = {period_us}
entry = 0x{entry:x}
mailbox = 0x{mailbox:x}
scenario = "{scenario}"
source = "{source_kind}"
memory_bytes = {memory_bytes}
linux_memory_bytes = {linux_memory_bytes}
linux_memory_every = {linux_memory_every}
linux_fences_enabled = {str(linux_fences_enabled).lower()}
linux_host_cpu = {linux_cpu}
explicit_dtb_enabled = {str(explicit_enabled()).lower()}
guest_gic_layout = "{gic_layout()}"
service_placement = "{service_placement}"
irq_context = "{irq_context}"
irq_service = "{irq_service}"
irq_pressure = "{irq_pressure}"
irq_pressure_period_us = {irq_pressure_period_us}
irq_pressure_burst = {irq_pressure_burst}
irq_service_rounds = {irq_service_rounds}
irq_service_window_us = {irq_service_window_us}
inversion_witness = {str(inversion_witness).lower()}
guest_rtc_unused = {str(guest_rtc_unused).lower()}
"""
    )
    return fixture


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zephyr-base", type=Path, help="pinned Zephyr checkout (or ZEPHYR_BASE)")
    parser.add_argument("--cross-compile", help="absolute toolchain prefix (or CROSS_COMPILE)")
    parser.add_argument("--output", type=Path, default=None, help="generated resource directory")
    parser.add_argument("--cache-dir", type=Path, default=None, help="Zephyr/toolchain/venv cache")
    parser.add_argument("--jobs", default=str(os.cpu_count() or 4), help="parallel guest build jobs")
    parser.add_argument("--linux-peer", action="store_true", help="require the dual-Guest runtime resource profile")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sample_count()  # Reject invalid scale before toolchain setup or any build.
    linux_host_cpu()
    if args.linux_peer != (os.environ.get("VIRQ_HOST_LOAD", "baseline") in ("linux_cpu", "linux_memory")):
        raise ValueError("Linux load requires matching Linux peer runtime configuration")
    cache = (args.cache_dir or default_cache()).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    python = ensure_python_runtime(cache)
    tools_dir = python_tools_dir(cache)
    for tool in ("cmake", "ninja"):
        if not (tools_dir / tool).is_file():
            raise RuntimeError(f"{tools_dir / tool} is missing from the prepared virtualenv")
    output = (args.output or default_output()).resolve()
    zephyr_base = ensure_zephyr_source(cache, args.zephyr_base.resolve() if args.zephyr_base else None)
    cross_compile = ensure_cross_compile(cache, args.cross_compile)
    report_toolchain(cross_compile)
    elf = build_guest(
        Path(__file__).resolve().parent,
        output / "guest",
        zephyr_base,
        cross_compile,
        tools_dir,
        python,
        args.jobs,
    )
    if explicit_enabled():
        run(["dtc", "-I", "dts", "-O", "dtb", "-o", str(elf.with_suffix(".dtb")),
             str(elf.with_suffix(".dts"))])
    entry, mailbox = inspect_guest(elf)
    config = write_vm_config(output, elf.with_name("zephyr.bin"), entry)
    if os.environ.get("VIRQ_HOST_LOAD", "baseline") in ("linux_cpu", "linux_memory"):
        run([sys.executable, str(Path(__file__).resolve().parent.parent / "linux-load/prepare.py"), "--output", str(output)])
    fixture = write_test_resources(output, entry, mailbox)
    append_boot_failure_regions(fixture, elf)
    print(f"[virq] zephyr={ZEPHYR_REVISION} entry=0x{entry:x} mailbox=0x{mailbox:x}")
    print(f"[virq] vm config {config}")
    print(f"[virq] test resources {fixture}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
