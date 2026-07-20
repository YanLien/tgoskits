---
sidebar_position: 5
sidebar_label: "应用运行"
---

# StarryOS 应用运行

`cargo xtask starry app` 管理 `apps/starry/` 目录下发现的可运行应用。压力测试、K230、visual 等重型用例已从 `test-suit/starryos/` 迁移到 `apps/starry/`，通过 `app` 子命令显式运行，避免污染常规测试套件。

## 子命令

```text
cargo xtask starry app <subcommand> [options]
```

| 子命令 | 说明 |
|--------|------|
| `app list` | 列出 `apps/starry/` 下发现的可运行应用 |
| `app qemu` | 构建并在 QEMU 中运行 `apps/starry/` 下的应用 |
| `app board` | 在远程板卡上运行应用 |

## 应用发现

`discover_apps(workspace_root)` 扫描 `apps/starry/` 目录，递归收集所有应用 case。每个应用目录通过文件特征自动推断类型（`infer_app_kind`）：

| 类型 | 触发条件 | 配置文件 |
|------|----------|----------|
| QEMU | 含 `qemu-*.toml`，无 `init.sh` + `board-*.toml` | `qemu-{arch}.toml`、可选 `build-*.toml`、`prebuild.sh` |
| Board | 含 `init.sh` + `board-*.toml`，无 `qemu-*.toml` | `init.sh`、`board-*.toml`、`build-*.toml` |
| QEMU（fallback） | 仅含 `prebuild.sh` | `prebuild.sh` |

一个应用目录不能同时含 `qemu-*` 和 `board-*` 配置（`infer_app_kind` 会报错要求拆分）。

### 应用忽略

`apps/.ignore` 文件（每行一个应用名，`#` 开头为注释）可排除特定应用。匹配规则支持裸名（`my-app`）、`starry/my-app`、`apps/starry/my-app` 三种前缀形式。

### 能力要求

每个应用可在 `requires` 文件中声明所需能力（每行一个）。`app qemu` 和 `app board` 通过 `--cap <CAP>` 声明当前可用的能力，缺失所需能力的应用会被过滤。例如一个需要 OrangePi-5-Plus 板卡的应用声明 `board:OrangePi-5-Plus`，只有运行时传入 `--cap board:OrangePi-5-Plus` 才会被选中。

## app list

```bash
cargo xtask starry app list [--kind qemu|board]
```

列出 `apps/starry/` 下发现的应用。`--kind qemu|board` 按类型过滤。输出包含应用名、类型、所需能力。

## app qemu

```bash
cargo xtask starry app qemu [options]
```

| 参数 | 说明 |
|------|------|
| `--all` | 运行所有匹配（经能力过滤后的）QEMU 应用 |
| `-t/--test-case <CASE>` | 选择 `apps/starry/<CASE>` 单个应用 |
| `--cap <CAP>`（可重复） | 声明可用能力，如 `--cap board:OrangePi-5-Plus` |
| `--arch <ARCH>` | 覆盖架构 |
| `--qemu-config <PATH>` | 覆盖 QEMU 配置 |
| `--debug` | debug 构建 |

`--all` 与 `-t` 互斥。每个选中的应用使用其目录内的 `qemu-{arch}.toml` 和 `build-*.toml` 配置，复用 StarryOS 测试的资产准备流程（rootfs 注入、ELF 依赖同步、Grouped runner 生成）。

### QEMU rootfs 隔离

应用运行不会直接修改共享的 managed rootfs。默认的 `snapshot = true` 流程会先通过
reflink（不支持时退化为普通复制）创建本次运行的私有 rootfs，再执行 `prebuild.sh` 和
overlay 注入；QEMU 退出后删除运行副本和临时目录。QEMU 的 snapshot 继续负责隔离
guest 启动后的块设备写入。

声明 `snapshot = false` 的应用需要跨运行保留 guest 写入。未显式指定独立 rootfs 时，
runner 使用：

```text
target/<target>/starry-app/<case>/persistent/rootfs.img
```

显式指定的非默认 rootfs 仍被视为该应用自己的持久镜像。默认 managed rootfs 即使被
配置文件引用，也不会作为持久写入目标。

QEMU 配置中的 rootfs 名称只表示基础文件系统来源。runner 按该固定 managed image
名称从镜像注册表准备文件系统，再基于它创建私有副本并执行 `prebuild.sh`；应用不得在
配置中使用 `rootfs-<arch>-<app>.img` 之类的派生输出名。

## app board

```bash
cargo xtask starry app board -t <CASE> [options]
```

| 参数 | 说明 |
|------|------|
| `-t/--test-case <CASE>`（必需） | 选择 `apps/starry/<CASE>` 板端应用 |
| `--board-config <PATH>` | 板卡配置路径 |
| `-b/--board-type <TYPE>` | 板卡类型 |
| `--server <HOST>` `--port <PORT>` | ostool-server 地址 |
| `--debug` | debug 构建 |

每个板端应用目录包含 `init.sh` 启动脚本（定义板卡上执行的命令）以及自动发现的 `board-*.toml` 和 `build-*.toml` 配置文件，无需手动指定所有配置路径。

## 用法示例

```bash
# 列出所有应用
cargo starry app list

# 只看 QEMU 应用
cargo starry app list --kind qemu

# 运行所有匹配的 QEMU 应用（带能力过滤）
cargo starry app qemu --all --cap board:OrangePi-5-Plus

# 运行单个应用
cargo starry app qemu -t dual-net

# 在 x86_64 QEMU 来宾中自编译 StarryOS
cargo starry app qemu -t selfhost/selfhost-full-kernel --arch x86_64

# 板端应用
cargo starry app board -t my-board-app -b OrangePi-5-Plus
```

自编译应用需要独立的持久化 rootfs、KVM 和较长运行时间，完整环境与验证边界见
[StarryOS 自编译](./self-compilation)。
