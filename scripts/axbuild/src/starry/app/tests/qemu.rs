use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    process::Command,
};

use tempfile::tempdir;

use super::{
    app_qemu_test_case, load_qemu_app_case_fields, prepare_qemu_app_case, resolve_qemu_config,
};
use crate::{
    starry::app::{
        StarryAppQemuCase, discover_apps,
        test_support::{write_case_file, write_test_image_config},
    },
    test::case::HostHttpServerConfig,
};

#[test]
fn qemu_config_selection_prefers_exact_arch_config() {
    let root = tempdir().unwrap();
    write_case_file(
        root.path(),
        "codex-cli",
        "qemu-x86_64-codex-help.toml",
        "args = []\n",
    );
    let exact = write_case_file(root.path(), "codex-cli", "qemu-x86_64.toml", "args = []\n");
    let app = discover_apps(root.path())
        .unwrap()
        .into_iter()
        .find(|app| app.name == "codex-cli")
        .unwrap();

    let selected = resolve_qemu_config(&app, Some("x86_64"), None)
        .unwrap()
        .unwrap();

    assert_eq!(selected, exact);
}

#[tokio::test]
async fn qemu_case_uses_starry_default_arch_without_an_arch_argument() {
    let root = tempdir().unwrap();
    write_test_image_config(root.path());
    let rootfs_path = root
        .path()
        .join(".tgos-images/rootfs-riscv64-alpine.img/rootfs-riscv64-alpine.img");
    fs::create_dir_all(rootfs_path.parent().unwrap()).unwrap();
    fs::write(&rootfs_path, b"rootfs").unwrap();
    write_case_file(
        root.path(),
        "qemu/apt",
        "qemu-riscv64.toml",
        r#"args = [
  "-drive",
  "id=disk0,if=none,format=raw,file=${workspace}/.tgos-images/rootfs-riscv64-alpine.img/rootfs-riscv64-alpine.img",
]
uefi = false
to_bin = true
success_regex = []
fail_regex = []
"#,
    );
    let app = discover_apps(root.path())
        .unwrap()
        .into_iter()
        .find(|app| app.name == "qemu/apt")
        .unwrap();

    let case = prepare_qemu_app_case(root.path(), &app, None, None)
        .await
        .unwrap();

    assert_eq!(case.arch, crate::context::DEFAULT_STARRY_ARCH);
}

#[test]
fn qemu_config_selection_rejects_variant_only_default() {
    let root = tempdir().unwrap();
    write_case_file(
        root.path(),
        "codex-cli",
        "qemu-x86_64-codex-help.toml",
        "args = []\n",
    );
    let app = discover_apps(root.path())
        .unwrap()
        .into_iter()
        .find(|app| app.name == "codex-cli")
        .unwrap();

    let err = resolve_qemu_config(&app, Some("x86_64"), None)
        .unwrap_err()
        .to_string();

    assert!(err.contains("qemu-x86_64.toml"));
}

#[test]
fn qemu_config_selection_uses_explicit_variant_config() {
    let root = tempdir().unwrap();
    let explicit = write_case_file(
        root.path(),
        "codex-cli",
        "qemu-x86_64-codex-syscall-hunt.toml",
        "args = []\n",
    );
    write_case_file(
        root.path(),
        "codex-cli",
        "qemu-x86_64-codex-help.toml",
        "args = []\n",
    );
    let app = discover_apps(root.path())
        .unwrap()
        .into_iter()
        .find(|app| app.name == "codex-cli")
        .unwrap();

    let selected = resolve_qemu_config(
        &app,
        Some("x86_64"),
        Some(Path::new("qemu-x86_64-codex-syscall-hunt.toml")),
    )
    .unwrap()
    .unwrap();

    assert_eq!(selected, explicit);
}

#[test]
fn qemu_case_fields_load_grouped_commands_and_subcases() {
    let root = tempdir().unwrap();
    write_case_file(
        root.path(),
        "qemu/sqlite",
        "qemu-x86_64.toml",
        "args = []\nuefi = false\nto_bin = true\nsuccess_regex = []\nfail_regex = \
         []\ntest_commands = [\"/usr/bin/app-sqlite\", \"/usr/bin/app-sqlite-deep\"]\n",
    );
    write_case_file(
        root.path(),
        "qemu/sqlite/app-sqlite/c",
        "CMakeLists.txt",
        "cmake_minimum_required(VERSION 3.20)\n",
    );
    write_case_file(
        root.path(),
        "qemu/sqlite/app-sqlite-deep/c",
        "CMakeLists.txt",
        "cmake_minimum_required(VERSION 3.20)\n",
    );
    let app = discover_apps(root.path())
        .unwrap()
        .into_iter()
        .find(|app| app.name == "qemu/sqlite")
        .unwrap();
    let qemu_config = resolve_qemu_config(&app, Some("x86_64"), None).unwrap();

    let fields =
        load_qemu_app_case_fields(root.path(), &app, qemu_config.as_deref().unwrap()).unwrap();

    assert_eq!(
        fields.test_case.test_commands,
        vec!["/usr/bin/app-sqlite", "/usr/bin/app-sqlite-deep"]
    );
    assert_eq!(fields.test_case.subcases.len(), 2);
}

#[test]
fn qemu_case_fields_load_configured_managed_rootfs() {
    let root = tempdir().unwrap();
    write_test_image_config(root.path());
    let rootfs_path = root
        .path()
        .join(".tgos-images/rootfs-aarch64-debian.img/rootfs-aarch64-debian.img");
    write_case_file(
        root.path(),
        "qemu/apt",
        "qemu-aarch64.toml",
        r#"args = [
  "-drive",
  "id=disk0,if=none,format=raw,file=${workspace}/.tgos-images/rootfs-aarch64-debian.img/rootfs-aarch64-debian.img",
]
uefi = false
to_bin = true
success_regex = []
fail_regex = []
"#,
    );
    let app = discover_apps(root.path())
        .unwrap()
        .into_iter()
        .find(|app| app.name == "qemu/apt")
        .unwrap();
    let qemu_config = resolve_qemu_config(&app, Some("aarch64"), None).unwrap();

    let fields =
        load_qemu_app_case_fields(root.path(), &app, qemu_config.as_deref().unwrap()).unwrap();

    assert_eq!(fields.rootfs_path, Some(rootfs_path));
    assert!(fields.snapshot);
}

#[test]
fn qemu_case_fields_load_snapshot_disable() {
    let root = tempdir().unwrap();
    write_case_file(
        root.path(),
        "macos-selfbuild",
        "qemu-aarch64.toml",
        r#"args = []
uefi = false
to_bin = true
snapshot = false
success_regex = []
fail_regex = []
"#,
    );
    let app = discover_apps(root.path())
        .unwrap()
        .into_iter()
        .find(|app| app.name == "macos-selfbuild")
        .unwrap();
    let qemu_config = resolve_qemu_config(&app, Some("aarch64"), None).unwrap();

    let fields =
        load_qemu_app_case_fields(root.path(), &app, qemu_config.as_deref().unwrap()).unwrap();

    assert!(!fields.snapshot);
}

#[test]
fn qemu_x86_and_loongarch_apps_use_the_uefi_boot_contract() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let app_configs = [
        "qemu/apk-add-fs-equivalence/qemu-x86_64.toml",
        "qemu/apk-curl/qemu-loongarch64.toml",
        "qemu/apk-curl/qemu-x86_64.toml",
        "qemu/apk-net-equivalence/qemu-x86_64.toml",
        "qemu/busybox/qemu-loongarch64.toml",
        "qemu/busybox/qemu-x86_64.toml",
        "qemu/coreutils/qemu-loongarch64.toml",
        "qemu/coreutils/qemu-x86_64.toml",
        "qemu/dhcp/qemu-loongarch64.toml",
        "qemu/dhcp/qemu-x86_64.toml",
        "qemu/dual-net/qemu-loongarch64.toml",
        "qemu/dual-net/qemu-x86_64.toml",
        "qemu/findutils/qemu-loongarch64.toml",
        "qemu/findutils/qemu-x86_64.toml",
        "qemu/grep/qemu-loongarch64.toml",
        "qemu/grep/qemu-x86_64.toml",
        "qemu/inotifywait/qemu-x86_64.toml",
        "qemu/lua/qemu-x86_64.toml",
        "qemu/memtrack-backtrace/qemu-loongarch64.toml",
        "qemu/memtrack-backtrace/qemu-x86_64.toml",
        "qemu/nvme/nvme-rootfs-rw-20m/qemu-loongarch64.toml",
        "qemu/nvme/nvme-rootfs-rw-20m/qemu-x86_64.toml",
        "qemu/procps/qemu-loongarch64.toml",
        "qemu/procps/qemu-x86_64.toml",
        "qemu/python-hello/qemu-loongarch64.toml",
        "qemu/python-hello/qemu-x86_64.toml",
        "qemu/rust-hello/qemu-loongarch64.toml",
        "qemu/rust-hello/qemu-x86_64.toml",
        "qemu/sqlite/qemu-loongarch64.toml",
        "qemu/sqlite/qemu-x86_64.toml",
        "qemu/syscall-test/qemu-loongarch64.toml",
        "qemu/syscall-test/qemu-x86_64.toml",
        "qemu/util-linux/qemu-loongarch64.toml",
        "qemu/util-linux/qemu-x86_64.toml",
    ];

    for relative_path in app_configs {
        let config_path = repo.join("apps/starry").join(relative_path);
        let config: toml::Value =
            toml::from_str(&fs::read_to_string(&config_path).unwrap()).unwrap();

        assert_eq!(
            config.get("uefi").and_then(toml::Value::as_bool),
            Some(true),
            "{} must use the dynamic UEFI handoff",
            config_path.display()
        );
        assert_eq!(
            config.get("to_bin").and_then(toml::Value::as_bool),
            Some(true),
            "{} must build the UEFI-loadable binary image",
            config_path.display()
        );
    }
}

#[test]
fn every_x86_and_loongarch_app_config_uses_the_uefi_boot_contract() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let mut config_paths = Vec::new();
    collect_x86_and_loongarch_qemu_configs(&repo.join("apps/starry"), &mut config_paths);

    assert!(!config_paths.is_empty());
    for config_path in config_paths {
        let config: toml::Value =
            toml::from_str(&fs::read_to_string(&config_path).unwrap()).unwrap();
        assert_eq!(
            config.get("uefi").and_then(toml::Value::as_bool),
            Some(true),
            "{} must use the dynamic UEFI handoff",
            config_path.display()
        );
        assert_eq!(
            config.get("to_bin").and_then(toml::Value::as_bool),
            Some(true),
            "{} must build the UEFI-loadable binary image",
            config_path.display()
        );
    }
}

#[test]
fn managed_app_rootfs_references_use_registered_base_filesystems() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let mut config_paths = Vec::new();
    collect_qemu_configs(&repo.join("apps/starry"), &mut config_paths);

    for config_path in config_paths {
        let config: toml::Value =
            toml::from_str(&fs::read_to_string(&config_path).unwrap()).unwrap();
        let Some(args) = config.get("args").and_then(toml::Value::as_array) else {
            continue;
        };
        for arg in args.iter().filter_map(toml::Value::as_str) {
            let Some(rootfs_reference) = arg.split(',').find(|part| part.contains("rootfs-"))
            else {
                continue;
            };
            let image_name = rootfs_reference
                .rsplit('/')
                .next()
                .unwrap_or(rootfs_reference);
            let image_name = image_name.strip_prefix("file=").unwrap_or(image_name);
            assert!(
                ["-alpine.img", "-busybox.img", "-debian.img"]
                    .iter()
                    .any(|suffix| image_name.ends_with(suffix)),
                "{} selects derived rootfs `{image_name}`; select a registered base filesystem",
                config_path.display()
            );
        }
    }
}

#[test]
fn loongarch_memtrack_has_enough_memory_and_rejects_allocator_abort() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let config_path = repo.join("apps/starry/qemu/memtrack-backtrace/qemu-loongarch64.toml");
    let config: toml::Value = toml::from_str(&fs::read_to_string(&config_path).unwrap()).unwrap();
    let args = config
        .get("args")
        .and_then(toml::Value::as_array)
        .unwrap()
        .iter()
        .map(|arg| arg.as_str().unwrap())
        .collect::<Vec<_>>();
    let memory = args
        .windows(2)
        .find_map(|args| (args[0] == "-m").then_some(args[1]));
    let fail_regex = config
        .get("fail_regex")
        .and_then(toml::Value::as_array)
        .unwrap()
        .iter()
        .map(|regex| regex.as_str().unwrap())
        .collect::<Vec<_>>();

    assert_eq!(memory, Some("512M"));
    assert!(
        fail_regex
            .iter()
            .any(|regex| regex.contains("memory allocation of"))
    );
}

#[test]
fn loongarch_uefi_app_configs_do_not_use_128m() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let mut config_paths = Vec::new();
    collect_x86_and_loongarch_qemu_configs(&repo.join("apps/starry"), &mut config_paths);

    for config_path in config_paths.into_iter().filter(|path| {
        path.file_name().and_then(|name| name.to_str()) == Some("qemu-loongarch64.toml")
    }) {
        let config: toml::Value =
            toml::from_str(&fs::read_to_string(&config_path).unwrap()).unwrap();
        let args = config
            .get("args")
            .and_then(toml::Value::as_array)
            .unwrap()
            .iter()
            .map(|arg| arg.as_str().unwrap())
            .collect::<Vec<_>>();
        let memory = args
            .windows(2)
            .find_map(|args| (args[0] == "-m").then_some(args[1]));

        assert_ne!(
            memory,
            Some("128M"),
            "{} cannot boot the dynamic UEFI image with 128 MiB",
            config_path.display()
        );
    }
}

fn collect_x86_and_loongarch_qemu_configs(directory: &Path, config_paths: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(directory).unwrap() {
        let entry = entry.unwrap();
        let path = entry.path();
        if path.is_dir() {
            collect_x86_and_loongarch_qemu_configs(&path, config_paths);
        } else if matches!(
            path.file_name().and_then(|name| name.to_str()),
            Some("qemu-x86_64.toml" | "qemu-loongarch64.toml")
        ) {
            config_paths.push(path);
        }
    }
}

fn collect_qemu_configs(directory: &Path, config_paths: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(directory).unwrap() {
        let entry = entry.unwrap();
        let path = entry.path();
        if path.is_dir() {
            collect_qemu_configs(&path, config_paths);
        } else if path
            .file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| name.starts_with("qemu-") && name.ends_with(".toml"))
        {
            config_paths.push(path);
        }
    }
}

#[test]
fn selfhost_x86_app_preserves_the_persistent_build_contract() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let app_dir = repo.join("apps/starry/selfhost/selfhost-full-kernel");
    let config_path = app_dir.join("qemu-x86_64.toml");
    let config: toml::Value = toml::from_str(&fs::read_to_string(&config_path).unwrap()).unwrap();

    assert_eq!(
        config.get("snapshot").and_then(toml::Value::as_bool),
        Some(false),
        "{} must persist the guest-built kernel",
        config_path.display()
    );
    assert_eq!(
        config.get("shell_init_cmd").and_then(toml::Value::as_str),
        Some("/bin/sh /opt/starry-selfhost-run.sh"),
        "{} must use the staged non-interactive guest runner",
        config_path.display()
    );
    let qemu_args = config
        .get("args")
        .and_then(toml::Value::as_array)
        .expect("selfhost qemu args must be an array");
    let qemu_args = qemu_args
        .iter()
        .map(|arg| arg.as_str().expect("QEMU arguments must be strings"))
        .collect::<Vec<_>>();
    assert!(
        qemu_args.contains(&"-no-shutdown")
            && qemu_args.windows(2).any(|args| args == ["-smp", "4"])
            && qemu_args.windows(2).any(|args| args == ["-m", "16G"])
            && qemu_args
                .windows(2)
                .any(|args| args == ["-netdev", "user,id=net0"])
            && qemu_args
                .windows(2)
                .any(|args| args == ["-device", "virtio-net-pci,netdev=net0"]),
        "{} must wait for an explicit success or failure marker before QEMU exits",
        config_path.display()
    );
    assert!(
        fs::read_to_string(&config_path)
            .unwrap()
            .contains("rootfs-x86_64-alpine.img"),
        "{} must select a registered base rootfs; persistence belongs to the runner copy",
        config_path.display()
    );

    let prebuild_path = app_dir.join("prebuild.sh");
    let prebuild = fs::read_to_string(&prebuild_path).unwrap();
    assert!(
        prebuild.contains("tgoskits-src.tar")
            && prebuild.contains("starry-selfhost-run.sh")
            && prebuild.contains("starry-selfhost-reboot-guard.sh")
            && prebuild.contains("cargo xtask image resize")
            && prebuild.contains("SELFHOST_ROOTFS_SIZE_MIB:-32768")
            && prebuild.contains("stage_guest_resolver")
            && prebuild.contains("/run/systemd/resolve/resolv.conf")
            && prebuild.contains("sha256sum --check --status")
            && prebuild.contains("--prefix=\"$toolchain_dir\"")
            && prebuild.contains(".starry-selfhost-toolchain-version"),
        "{} must stage source, the guest runner, the reboot guard, and a usable resolver into a \
         32 GiB rootfs, and must install verified Rust components into a versioned toolchain \
         archive",
        prebuild_path.display()
    );

    let guest_runner_path = app_dir.join("guest-selfbuild.sh");
    let guest_runner = fs::read_to_string(&guest_runner_path).unwrap();
    assert!(
        guest_runner.contains("x86_64-unknown-linux-musl")
            && guest_runner.contains("TOOLCHAIN=\"nightly-2026-07-15\"")
            && guest_runner.contains("RUSTUP_TOOLCHAIN=\"starry-selfhost-")
            && guest_runner.contains("--default-toolchain none")
            && guest_runner.contains("export RUSTUP_TOOLCHAIN")
            && guest_runner.contains("rustc -vV")
            && guest_runner.contains("cargo-binutils --version 0.4.0 --locked")
            && guest_runner.contains("ksym --version 0.6.0 --locked")
            && guest_runner.contains("tg-xtask")
            && guest_runner.contains("SELF_COMPILE_SUCCESS")
            && !guest_runner.contains("SELFHOST_RUST_TOOLCHAIN")
            && !guest_runner.contains("x86_64-unknown-linux-gnu")
            && !guest_runner.contains("export CARGO_TARGET_DIR")
            && guest_runner.contains("SELFHOST_TARGET_DIR:-/opt/starry-selfhost-target")
            && guest_runner.contains("ln -s \"$TARGET_DIR\" \"$SOURCE_DIR/target\"")
            && guest_runner.contains("SELFHOST_CARGO_BUILD_JOBS:-2")
            && guest_runner
                .contains("$SOURCE_DIR/target/x86_64-unknown-linux-musl/release/starryos"),
        "{} must build the canonical x86_64 path with a native musl host toolchain",
        guest_runner_path.display()
    );
}

#[test]
fn mysql_prebuild_preserves_the_runner_owned_debian_copy() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let script_path = repo.join("apps/starry/mysql/prebuild.sh");
    let script = fs::read_to_string(&script_path).unwrap();
    let prepare = script
        .split("prepare_mysql_rootfs_image() {")
        .nth(1)
        .and_then(|body| body.split("resize_rootfs_if_needed() {").next())
        .expect("mysql prebuild must define rootfs preparation before resizing");

    assert!(
        prepare.contains("if [[ -f \"$rootfs\" ]]; then")
            && prepare.find("if [[ -f \"$rootfs\" ]]").unwrap()
                < prepare.find("rm -f \"$rootfs\"").unwrap(),
        "{} must preserve the private Debian base image prepared by the app runner",
        script_path.display()
    );
}

#[test]
fn selfhost_reboot_guard_reports_the_interrupted_phase() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let guard =
        repo.join("apps/starry/selfhost/selfhost-full-kernel/guest-selfbuild-reboot-guard.sh");
    let root = tempdir().unwrap();
    let state = root.path().join("state");
    let bin_dir = root.path().join("bin");
    let poweroff = bin_dir.join("poweroff");
    let poweroff_marker = root.path().join("poweroff-called");
    fs::create_dir(&bin_dir).unwrap();
    fs::write(
        &poweroff,
        "#!/bin/sh\nprintf 'called\\n' >\"$POWER_OFF_MARKER\"\n",
    )
    .unwrap();
    fs::set_permissions(&poweroff, fs::Permissions::from_mode(0o755)).unwrap();
    fs::write(&state, "running test-run kernel\n").unwrap();

    let output = Command::new("/bin/sh")
        .arg(&guard)
        .env("SELFHOST_STATE_FILE", &state)
        .env("POWER_OFF_MARKER", &poweroff_marker)
        .env("PATH", &bin_dir)
        .output()
        .unwrap();

    assert!(!output.status.success());
    assert!(
        String::from_utf8_lossy(&output.stdout)
            .contains("SELF_COMPILE_FAILED: unexpected guest reboot during kernel")
    );
    assert_eq!(fs::read_to_string(&poweroff_marker).unwrap(), "called\n");

    fs::write(&state, "ready test-run prebuild\n").unwrap();
    fs::remove_file(&poweroff_marker).unwrap();
    let output = Command::new("/bin/sh")
        .arg(&guard)
        .env("SELFHOST_STATE_FILE", &state)
        .env("POWER_OFF_MARKER", &poweroff_marker)
        .env("PATH", &bin_dir)
        .output()
        .unwrap();

    assert!(output.status.success());
    assert!(!String::from_utf8_lossy(&output.stdout).contains("SELF_COMPILE_FAILED"));
    assert!(!poweroff_marker.exists());
}

#[test]
fn app_qemu_test_case_preserves_host_symbolize_success_regex() {
    let case_dir = PathBuf::from("/tmp/apps/starry/memtrack-backtrace");
    let qemu_config_path = case_dir.join("qemu-x86_64.toml");
    let case = StarryAppQemuCase {
        name: "memtrack-backtrace".to_string(),
        arch: "x86_64".to_string(),
        target: "x86_64-unknown-none".to_string(),
        build_config_path: None,
        qemu_config_path: Some(qemu_config_path.clone()),
        rootfs_path: PathBuf::from("/tmp/rootfs.img"),
        rootfs_copy_to_remove: None,
        rootfs_run_dir_to_remove: None,
        snapshot: true,
        test_commands: Vec::new(),
        host_symbolize_success_regex: vec!["symbolized".to_string()],
        host_http_server: Some(HostHttpServerConfig {
            bind: "127.0.0.1".to_string(),
            port: 18382,
            body: "fixture".to_string(),
            body_size: None,
            body_byte: b'X',
            dir: None,
        }),
        subcases: Vec::new(),
    };

    let test_case = app_qemu_test_case(&case, case_dir.clone()).unwrap();

    assert_eq!(test_case.case_dir, case_dir);
    assert_eq!(test_case.qemu_config_path, qemu_config_path);
    assert_eq!(test_case.host_symbolize_success_regex, vec!["symbolized"]);
    assert_eq!(
        test_case
            .host_http_server
            .as_ref()
            .map(|config| (config.bind.as_str(), config.port)),
        Some(("127.0.0.1", 18382))
    );
}

#[test]
fn ebpf_prebuilds_install_selected_rust_musl_target() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let ebpf_dir = repo.join("apps/starry/ebpf");
    let mut checked = 0;

    for entry in fs::read_dir(&ebpf_dir).unwrap() {
        let prebuild_path = entry.unwrap().path().join("prebuild.sh");
        if !prebuild_path.is_file() {
            continue;
        }

        let content = fs::read_to_string(&prebuild_path).unwrap();
        if !content.contains(r#"cargo build --release --target "$musl_target""#) {
            continue;
        }

        checked += 1;
        assert!(
            content.contains("rustup show active-toolchain")
                && content
                    .contains(r#"rustup target add --toolchain "$rust_toolchain" "$musl_target""#)
                && content.contains(r#"export RUSTUP_TOOLCHAIN="$rust_toolchain""#)
                && content.contains(r#"host_tools_dir="${STARRY_WORKSPACE:-$app_dir}/tmp/axbuild/starry-host-tools""#)
                && content.contains("apk add --no-cache bpf-linker")
                && content.contains("cargo install bpf-linker --version 0.10.3 --locked --root"),
            "{} must install the selected Rust musl target before nested cargo build",
            prebuild_path.display()
        );
    }

    assert!(checked > 0, "expected to check at least one eBPF prebuild");
}

#[test]
fn ebpf_build_scripts_use_selected_rustup_toolchain() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let ebpf_dir = repo.join("apps/starry/ebpf");
    let mut checked = 0;

    for entry in fs::read_dir(&ebpf_dir).unwrap() {
        let app_dir = entry.unwrap().path();
        let app_name = app_dir.file_name().unwrap().to_string_lossy();
        let build_rs = app_dir.join(app_name.as_ref()).join("build.rs");
        if !build_rs.is_file() {
            continue;
        }

        checked += 1;
        let content = fs::read_to_string(&build_rs).unwrap();
        assert!(
            content.contains(r#"std::env::var("RUSTUP_TOOLCHAIN")"#)
                && content.contains("Toolchain::Custom")
                && !content.contains("build_ebpf([ebpf_package], Toolchain::default())"),
            "{} must build eBPF with the selected rustup toolchain, not implicit nightly",
            build_rs.display()
        );
    }

    assert!(checked > 0, "expected to check at least one eBPF build.rs");
}

#[test]
fn claw_code_prebuild_injects_only_the_runner_owned_rootfs_copy() {
    let root = tempdir().unwrap();
    let workspace = root.path();
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let script = repo.join("apps/starry/claw-code/prebuild.sh");

    let cache = workspace.join("cache");
    let bin = cache.join("claw");
    fs::create_dir_all(&cache).unwrap();
    fs::write(&bin, b"fake claw").unwrap();

    let tools = workspace.join("tools");
    fs::create_dir_all(&tools).unwrap();
    let debugfs = tools.join("debugfs");
    fs::write(
        &debugfs,
        "#!/usr/bin/env bash\nif [ \"$1\" = \"-w\" ]; then test -f \"$2\"; fi\nexit 0\n",
    )
    .unwrap();
    fs::set_permissions(&debugfs, fs::Permissions::from_mode(0o755)).unwrap();

    let default_rootfs = workspace.join("rootfs-x86_64-alpine.img");
    let app_rootfs = workspace.join("run/rootfs.img");
    fs::create_dir_all(app_rootfs.parent().unwrap()).unwrap();
    fs::write(&default_rootfs, b"base rootfs").unwrap();
    fs::copy(&default_rootfs, &app_rootfs).unwrap();

    let path = format!("{}:{}", tools.display(), std::env::var("PATH").unwrap());
    let status = Command::new("bash")
        .arg(&script)
        .current_dir(repo.join("apps/starry/claw-code"))
        .env("CLAW_CACHE_DIR", &cache)
        .env("STARRY_WORKSPACE", workspace)
        .env("STARRY_ROOTFS", &app_rootfs)
        .env("STARRY_OVERLAY_DIR", workspace.join("overlay"))
        .env("PATH", path)
        .status()
        .unwrap();

    assert!(status.success());
    assert!(app_rootfs.is_file());
    assert_eq!(fs::read(&app_rootfs).unwrap(), b"base rootfs");
    assert_eq!(fs::read(default_rootfs).unwrap(), b"base rootfs");
}

#[test]
fn syscall_count_qemu_configs_stop_after_pass_marker() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let config_dir = repo.join("apps/starry/ebpf/syscall_count");

    for arch in ["x86_64", "aarch64", "riscv64", "loongarch64"] {
        let config_path = config_dir.join(format!("qemu-{arch}.toml"));
        let content = fs::read_to_string(&config_path).unwrap();
        let config: toml::Value = toml::from_str(&content).unwrap();
        let success_regex = config
            .get("success_regex")
            .and_then(toml::Value::as_array)
            .unwrap();
        assert!(
            success_regex
                .iter()
                .filter_map(toml::Value::as_str)
                .any(|regex| regex.contains("SYSCALL_COUNT_PASS")),
            "{} must stop QEMU after syscall_count reports a captured syscall",
            config_path.display()
        );
    }
}

#[test]
fn codex_cli_qemu_config_uses_injected_smoke_script() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let config_path = repo.join("apps/starry/codex-cli/qemu-x86_64.toml");
    let content = fs::read_to_string(&config_path).unwrap();
    let config: toml::Value = toml::from_str(&content).unwrap();

    let shell_init_cmd = config
        .get("shell_init_cmd")
        .and_then(toml::Value::as_str)
        .unwrap_or_default();
    assert_eq!(shell_init_cmd, "/usr/bin/codex-offline-smoke.sh");
    assert!(
        !shell_init_cmd.contains("STARRY_CODEX_STAGE_G_CODEX_HELP_PASSED")
            && !shell_init_cmd.contains("STARRY_CODEX_STAGE_G_LOGIN_STATUS_OK"),
        "{} must not inject the long smoke script through the interactive shell",
        config_path.display()
    );

    let prebuild_path = repo.join("apps/starry/codex-cli/prebuild.sh");
    let prebuild = fs::read_to_string(&prebuild_path).unwrap();
    assert!(
        prebuild.contains("/usr/bin/codex-offline-smoke.sh")
            && prebuild.contains("STARRY_CODEX_STAGE_G_CODEX_HELP_PASSED"),
        "{} must inject the offline smoke script into the rootfs overlay",
        prebuild_path.display()
    );
}

#[test]
fn llvm22_build_configs_use_current_starryos_features() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let config_dir = repo.join("apps/starry/llvm22");

    for name in [
        "build-aarch64-unknown-none-softfloat.toml",
        "build-loongarch64-unknown-none-softfloat.toml",
        "build-riscv64gc-unknown-none-elf.toml",
    ] {
        let config_path = config_dir.join(name);
        let content = fs::read_to_string(&config_path).unwrap();
        assert!(
            !content.contains("ax-feat/"),
            "{} must not request removed ax-feat package features",
            config_path.display()
        );
        assert!(
            content.contains("\"ax-runtime/display\""),
            "{} must enable display support through ax-runtime",
            config_path.display()
        );
        assert!(
            content.contains("\"ax-runtime/rtc\""),
            "{} must enable RTC support through ax-runtime",
            config_path.display()
        );
    }
}

#[test]
fn glibc_dynamic_smoke_prebuild_installs_selected_gnu_cross_compiler() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let prebuild_path = repo.join("apps/starry/glibc-dynamic-smoke/prebuild.sh");
    let content = fs::read_to_string(&prebuild_path).unwrap();

    assert!(
        content.contains("gcc-aarch64-linux-gnu")
            && content.contains("gcc-riscv64-linux-gnu")
            && content.contains("gcc-x86-64-linux-gnu")
            && content.contains("libc6-dev-arm64-cross")
            && content.contains("libc6-dev-riscv64-cross")
            && content.contains("#include <stdio.h>")
            && content.contains("apt-get install -y --no-install-recommends"),
        "{} must install the selected host GNU cross compiler when it is missing",
        prebuild_path.display()
    );
}

#[test]
fn apk_package_prebuilds_use_guest_apk_from_staging_root() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();

    for app in ["ffmpeg", "mosquitto"] {
        let prebuild_path = repo.join(format!("apps/starry/{app}/prebuild.sh"));
        let content = fs::read_to_string(&prebuild_path).unwrap();

        assert!(
            !content.contains("apk-tools") && !content.contains("command -v apk"),
            "{} must not require host apk-tools; Ubuntu CI does not provide it",
            prebuild_path.display()
        );
        assert!(
            content.contains("/sbin/apk")
                && content.contains("--force-no-chroot")
                && content.contains("--scripts=no"),
            "{} must install Alpine packages with the target rootfs apk",
            prebuild_path.display()
        );
    }
}

#[test]
fn apk_prebuilds_do_not_poison_qemu_with_guest_library_path() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();

    for app in ["ffmpeg", "ffplay", "mosquitto"] {
        let prebuild_path = repo.join(format!("apps/starry/{app}/prebuild.sh"));
        let content = fs::read_to_string(&prebuild_path).unwrap();

        assert!(
            content.contains("env -u LD_LIBRARY_PATH")
                && !content.contains("LD_LIBRARY_PATH=\"$staging_root"),
            "{} must not expose target-rootfs libraries through host LD_LIBRARY_PATH when running \
             qemu-user",
            prebuild_path.display()
        );
    }
}

#[test]
fn go_lang_grpc_cancel_stream_uses_blocking_cancel_handler() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let source_path = repo.join("apps/starry/go-lang/go/framework_grpc.go");
    let content = fs::read_to_string(&source_path).unwrap();

    assert!(
        content.contains("serverStreamHook func")
            && content.contains("<-stream.Context().Done()")
            && content.contains("status.FromContextError(stream.Context().Err()).Err()"),
        "{} must make the cancel stream case block until client cancellation",
        source_path.display()
    );
}

#[test]
fn ffplay_prebuild_exposes_weston_private_libraries() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let prebuild_path = repo.join("apps/starry/ffplay/prebuild.sh");
    let content = fs::read_to_string(&prebuild_path).unwrap();

    assert!(
        content.contains("for dir in lib usr/lib usr/local/lib usr/libexec")
            && content.contains("ld-musl-${arch}.path")
            && content.contains("append_musl_search_path /usr/libexec")
            && content.contains("append_musl_search_path /usr/lib/weston"),
        "{} must copy and expose Weston private library directories so Alpine libexec_weston.so.0 \
         is loadable",
        prebuild_path.display()
    );
}

#[test]
fn media_prebuilds_run_apk_with_the_staged_musl_loader() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    for app in ["ffmpeg", "mosquitto"] {
        let prebuild_path = repo.join("apps/starry").join(app).join("prebuild.sh");
        let content = fs::read_to_string(&prebuild_path).unwrap();

        assert!(
            content.contains("guest_loader=\"$staging_root/lib/ld-musl-${arch}.so.1\"")
                && content.contains("--library-path")
                && content.contains("$staging_root/lib:$staging_root/usr/lib"),
            "{} must run guest apk through its staged musl loader so host libraries cannot leak in",
            prebuild_path.display()
        );
    }
}

#[test]
fn top_app_provisions_procps_before_guest_boot() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let app_dir = repo.join("apps/starry/top");
    let guest_test = fs::read_to_string(app_dir.join("top-test.sh")).unwrap();
    let prebuild = fs::read_to_string(app_dir.join("c/prebuild.sh")).unwrap_or_default();
    let cmake = fs::read_to_string(app_dir.join("c/CMakeLists.txt")).unwrap_or_default();

    assert!(
        !guest_test.contains("apk add")
            && prebuild.contains("apk add procps")
            && cmake.contains("top-test.sh")
            && cmake.contains("PROCPS_TOP"),
        "{} must install procps into the private staging root instead of using guest network",
        app_dir.display()
    );
}

#[test]
fn claw_code_qemu_config_exits_after_smoke_check() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("axbuild manifest should live under scripts/axbuild")
        .to_path_buf();
    let config_path = repo.join("apps/starry/claw-code/qemu-x86_64.toml");
    let content = fs::read_to_string(&config_path).unwrap();
    let config: toml::Value = toml::from_str(&content).unwrap();

    let args = config.get("args").and_then(toml::Value::as_array).unwrap();
    assert!(
        args.iter().filter_map(toml::Value::as_str).any(|arg| {
            arg.contains("rootfs-x86_64-alpine.img") && !arg.contains("rootfs-x86_64-claw-code.img")
        }),
        "{} must select a fixed managed base rootfs; the runner owns the private derived copy",
        config_path.display()
    );

    let timeout = config
        .get("timeout")
        .and_then(toml::Value::as_integer)
        .unwrap_or_default();
    assert!(
        timeout > 0,
        "{} must not disable QEMU timeout in CI smoke runs",
        config_path.display()
    );

    let success_regex = config
        .get("success_regex")
        .and_then(toml::Value::as_array)
        .unwrap();
    assert!(
        success_regex
            .iter()
            .filter_map(toml::Value::as_str)
            .any(|regex| regex.contains("STARRY_CLAW_READY")),
        "{} must stop QEMU after the claw smoke marker",
        config_path.display()
    );

    let shell_init_cmd = config
        .get("shell_init_cmd")
        .and_then(toml::Value::as_str)
        .unwrap_or_default();
    assert!(
        shell_init_cmd.contains("test -x /usr/bin/claw"),
        "{} must verify that /usr/bin/claw was injected as an executable",
        config_path.display()
    );
    assert!(
        !shell_init_cmd.contains("STARRY_CLAW_READY")
            && !shell_init_cmd.contains("STARRY_CLAW_MISSING"),
        "{} must not echo full claw smoke markers as shell input",
        config_path.display()
    );
}
