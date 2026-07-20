use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};

use anyhow::{Context, bail};

use super::{super::rootfs, types::StarryAppCase};
use crate::{
    rootfs::inject,
    support::process::ProcessExt,
    test::case::{case_asset_layout, copy_rootfs_image, reset_dir},
};

#[derive(Debug)]
pub(super) struct PreparedAppRootfs {
    pub(super) path: PathBuf,
    pub(super) copy_to_remove: Option<PathBuf>,
    pub(super) run_dir_to_remove: Option<PathBuf>,
}

pub(super) async fn prepare_qemu_app_rootfs(
    workspace_root: &Path,
    app: &StarryAppCase,
    arch: &str,
    target: &str,
    configured_rootfs: Option<&Path>,
    snapshot: bool,
) -> anyhow::Result<PreparedAppRootfs> {
    let source_rootfs = ensure_source_rootfs(workspace_root, arch, configured_rootfs).await?;

    if snapshot {
        return prepare_qemu_app_rootfs_from_base(
            workspace_root,
            app,
            arch,
            target,
            &source_rootfs,
        );
    }

    let default_rootfs = crate::image::storage::default_rootfs_path(workspace_root, arch)?;
    let persistent_rootfs = select_persistent_rootfs_path(
        workspace_root,
        target,
        &app.name,
        configured_rootfs,
        &default_rootfs,
    );
    prepare_persistent_qemu_app_rootfs(
        workspace_root,
        app,
        arch,
        target,
        &source_rootfs,
        &persistent_rootfs,
    )
}

async fn ensure_source_rootfs(
    workspace_root: &Path,
    arch: &str,
    configured_rootfs: Option<&Path>,
) -> anyhow::Result<PathBuf> {
    if let Some(configured_rootfs) = configured_rootfs {
        crate::image::storage::ensure_optional_managed_rootfs(
            workspace_root,
            arch,
            Some(configured_rootfs),
        )
        .await?;
        if configured_rootfs.is_file() {
            return Ok(configured_rootfs.to_path_buf());
        }
        bail!(
            "configured rootfs was not prepared at {}",
            configured_rootfs.display()
        );
    }

    crate::image::storage::ensure_rootfs_for_arch(workspace_root, arch).await
}

fn prepare_qemu_app_rootfs_from_base(
    workspace_root: &Path,
    app: &StarryAppCase,
    arch: &str,
    target: &str,
    source_rootfs: &Path,
) -> anyhow::Result<PreparedAppRootfs> {
    let layout = app_asset_layout(workspace_root, target, &app.name)?;
    fs::create_dir_all(&layout.run_dir)
        .with_context(|| format!("failed to create {}", layout.run_dir.display()))?;
    if let Err(error) = copy_rootfs_image(source_rootfs, &layout.case_rootfs_copy)
        .and_then(|()| rootfs::ensure_apk_region_in_rootfs(&layout.case_rootfs_copy))
        .and_then(|()| {
            prepare_app_overlay(
                workspace_root,
                app,
                arch,
                &layout.case_rootfs_copy,
                &layout.staging_root,
                &layout.overlay_dir,
            )
        })
    {
        let _ = fs::remove_dir_all(&layout.run_dir);
        return Err(error);
    }

    Ok(PreparedAppRootfs {
        path: layout.case_rootfs_copy.clone(),
        copy_to_remove: Some(layout.case_rootfs_copy),
        run_dir_to_remove: Some(layout.run_dir),
    })
}

fn prepare_persistent_qemu_app_rootfs(
    workspace_root: &Path,
    app: &StarryAppCase,
    arch: &str,
    target: &str,
    source_rootfs: &Path,
    persistent_rootfs: &Path,
) -> anyhow::Result<PreparedAppRootfs> {
    if let Some(parent) = persistent_rootfs.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create {}", parent.display()))?;
    }
    if !persistent_rootfs.is_file() {
        copy_rootfs_image(source_rootfs, persistent_rootfs)?;
    }
    rootfs::ensure_apk_region_in_rootfs(persistent_rootfs)?;

    let run_dir_to_remove = if app.prebuild_path.is_some() {
        let layout = app_asset_layout(workspace_root, target, &app.name)?;
        if let Err(error) = prepare_app_overlay(
            workspace_root,
            app,
            arch,
            persistent_rootfs,
            &layout.staging_root,
            &layout.overlay_dir,
        ) {
            let _ = fs::remove_dir_all(&layout.run_dir);
            return Err(error);
        }
        Some(layout.run_dir)
    } else {
        None
    };

    Ok(PreparedAppRootfs {
        path: persistent_rootfs.to_path_buf(),
        copy_to_remove: None,
        run_dir_to_remove,
    })
}

fn prepare_app_overlay(
    workspace_root: &Path,
    app: &StarryAppCase,
    arch: &str,
    rootfs_path: &Path,
    staging_root: &Path,
    overlay_dir: &Path,
) -> anyhow::Result<()> {
    let Some(prebuild_path) = app.prebuild_path.as_deref() else {
        return Ok(());
    };

    reset_dir(staging_root)?;
    reset_dir(overlay_dir)?;
    let mut command = Command::new("bash");
    command
        .arg(prebuild_path)
        .current_dir(&app.case_dir)
        .env("STARRY_APP_NAME", &app.name)
        .env("STARRY_APP_DIR", &app.case_dir)
        .env("STARRY_WORKSPACE", workspace_root)
        .env("STARRY_ARCH", arch)
        .env("STARRY_ROOTFS", rootfs_path)
        .env("STARRY_STAGING_ROOT", staging_root)
        .env("STARRY_OVERLAY_DIR", overlay_dir);
    command
        .exec()
        .with_context(|| format!("failed to run {}", prebuild_path.display()))?;

    inject::inject_overlay(rootfs_path, overlay_dir)
}

fn app_asset_layout(
    workspace_root: &Path,
    target: &str,
    app_name: &str,
) -> anyhow::Result<crate::test::case::CaseAssetLayout> {
    case_asset_layout(workspace_root, target, &format!("starry-app/{app_name}"))
}

fn persistent_app_rootfs_path(workspace_root: &Path, target: &str, app_name: &str) -> PathBuf {
    workspace_root
        .join("target")
        .join(target)
        .join("starry-app")
        .join(app_name)
        .join("persistent/rootfs.img")
}

fn select_persistent_rootfs_path(
    workspace_root: &Path,
    target: &str,
    app_name: &str,
    configured_rootfs: Option<&Path>,
    default_rootfs: &Path,
) -> PathBuf {
    configured_rootfs
        .filter(|path| *path != default_rootfs)
        .map(Path::to_path_buf)
        .unwrap_or_else(|| persistent_app_rootfs_path(workspace_root, target, app_name))
}

#[cfg(test)]
#[path = "tests/rootfs.rs"]
mod tests;
