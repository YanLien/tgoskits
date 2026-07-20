use std::{fs, process::Command};

use sha2::{Digest, Sha256};
use tempfile::tempdir;

use super::{
    ensure_source_rootfs, prepare_qemu_app_rootfs_from_base, select_persistent_rootfs_path,
};
use crate::{
    image::{
        config::ImageConfig,
        registry::{ImageEntry, ImageRegistry},
        storage::REGISTRY_FILENAME,
    },
    starry::app::{StarryAppCase, StarryAppKind},
    support::download::test_support,
};

#[test]
fn app_prebuild_does_not_modify_the_shared_rootfs() {
    let workspace = tempdir().unwrap();
    let case_dir = workspace.path().join("apps/starry/demo");
    let prebuild_path = case_dir.join("prebuild.sh");
    let shared_rootfs = workspace.path().join("shared-rootfs.img");
    fs::create_dir_all(&case_dir).unwrap();
    fs::write(
        &prebuild_path,
        "#!/bin/sh\nmkdir -p \"$STARRY_OVERLAY_DIR/etc\"\nprintf isolated \
         >\"$STARRY_OVERLAY_DIR/etc/app-marker\"\n",
    )
    .unwrap();
    let rootfs_file = fs::File::create(&shared_rootfs).unwrap();
    rootfs_file.set_len(8 * 1024 * 1024).unwrap();
    let status = Command::new("mke2fs")
        .args(["-q", "-t", "ext4", "-F"])
        .arg(&shared_rootfs)
        .status()
        .unwrap();
    assert!(status.success());
    let shared_before = fs::read(&shared_rootfs).unwrap();
    let app = StarryAppCase {
        name: "demo".to_string(),
        kind: StarryAppKind::Qemu,
        case_dir,
        prebuild_path: Some(prebuild_path),
        requires: Vec::new(),
    };

    let prepared = prepare_qemu_app_rootfs_from_base(
        workspace.path(),
        &app,
        "x86_64",
        "x86_64-unknown-none",
        &shared_rootfs,
    )
    .unwrap();

    assert_ne!(prepared.path, shared_rootfs);
    assert_eq!(
        prepared.copy_to_remove.as_deref(),
        Some(prepared.path.as_path())
    );
    assert!(prepared.run_dir_to_remove.is_some());
    assert_eq!(fs::read(&shared_rootfs).unwrap(), shared_before);
}

#[test]
fn persistent_app_does_not_reuse_the_default_managed_rootfs() {
    let workspace = tempdir().unwrap();
    let default_rootfs = workspace.path().join("images/rootfs-x86_64-alpine.img");

    let persistent = select_persistent_rootfs_path(
        workspace.path(),
        "x86_64-unknown-none",
        "selfbuild",
        Some(&default_rootfs),
        &default_rootfs,
    );

    assert_eq!(
        persistent,
        workspace
            .path()
            .join("target/x86_64-unknown-none/starry-app/selfbuild/persistent/rootfs.img")
    );
}

#[tokio::test]
async fn missing_configured_managed_rootfs_is_downloaded_instead_of_default() {
    let workspace = tempdir().unwrap();
    let image_name = "rootfs-riscv64-debian.img";
    let archive = make_rootfs_archive(image_name, b"debian rootfs");
    let sha256 = format!("{:x}", Sha256::digest(&archive));
    let archive_url =
        test_support::register_bytes(format!("{image_name}.tar.xz").as_str(), archive);
    let local_storage = workspace.path().join(".tgos-images");
    let config = ImageConfig {
        local_storage: local_storage.clone(),
        registry: "https://example.com/registry.toml".to_string(),
        auto_sync: false,
        auto_sync_threshold: 60,
    };
    ImageConfig::write_config(workspace.path(), &config).unwrap();
    fs::create_dir_all(&local_storage).unwrap();
    fs::write(
        local_storage.join(REGISTRY_FILENAME),
        toml::to_string(&ImageRegistry {
            images: vec![ImageEntry {
                name: image_name.to_string(),
                version: "0.0.1".to_string(),
                released_at: Some("2025-01-01T00:00:00Z".parse().unwrap()),
                description: "Debian rootfs".to_string(),
                sha256,
                arch: "riscv64".to_string(),
                url: archive_url.url().to_string(),
            }],
        })
        .unwrap(),
    )
    .unwrap();
    let configured_rootfs = local_storage.join(image_name).join(image_name);

    let selected = ensure_source_rootfs(
        workspace.path(),
        "riscv64",
        Some(configured_rootfs.as_path()),
    )
    .await
    .unwrap();

    assert_eq!(selected, configured_rootfs);
    assert_eq!(fs::read(selected).unwrap(), b"debian rootfs");
    assert_eq!(archive_url.request_count(), 1);
}

fn make_rootfs_archive(image_name: &str, contents: &[u8]) -> Vec<u8> {
    let encoder = xz2::write::XzEncoder::new(Vec::new(), 6);
    let mut builder = tar::Builder::new(encoder);
    let mut header = tar::Header::new_gnu();
    header.set_path(image_name).unwrap();
    header.set_size(contents.len() as u64);
    header.set_mode(0o644);
    header.set_cksum();
    builder.append(&header, contents).unwrap();
    builder.into_inner().unwrap().finish().unwrap()
}
