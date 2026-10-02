# Build runner configuration

## 内核构建 / Kernel builds

在仓库的 `Settings → Secrets and variables → Actions → Variables` 中配置以下 **Repository variables**，以后切换机器或托管方式只需修改变量。不要创建同名 Secret 或 Environment variable。

Configure these **repository variables** under `Settings → Secrets and variables → Actions → Variables`. Switch machines or hosting by editing the variable, without changing workflows or the App. Do not use secrets or environment-level variables for runner selection.

| 变量 / Variable | 作用范围 / Scope | 未设置或为空 / Unset or empty |
| --- | --- | --- |
| `KERNEL_RUNNER` | 所有调用 `build.yml` 的 GKI 构建：自定义参数、自定义源码、各 Android 版本、全功能矩阵 / All GKI callers of `build.yml`: custom parameters, custom sources, Android version workflows and the feature matrix | `ubuntu-latest` |
| `ONEPLUS_RUNNER` | 调用 `oneplus-build.yml` 的 OnePlus/Oplus 内核构建 / OnePlus/Oplus kernel builds calling `oneplus-build.yml` | `ubuntu-latest` |
| `APP_RUNNER` | APK 构建，保持原有的单标签格式 / APK builds, retaining the existing single-label format | `ubuntu-latest` |

`KERNEL_RUNNER` 和 `ONEPLUS_RUNNER` 相互独立，也不继承 `APP_RUNNER`。预检查和产物整理等独立任务仍使用各自原有的 runner。GitHub Actions 页面、App、CLI 发起的构建只要调用相应工作流，都会使用这项设置，无需新增构建参数。

`KERNEL_RUNNER` and `ONEPLUS_RUNNER` are independent and do not inherit `APP_RUNNER`. Separate preflight and artifact-processing jobs retain their existing runners. Builds launched through Actions, the App or CLI use the setting when they call the corresponding workflow; no extra dispatch input is needed.

### 内核变量的取值 / Kernel variable values

| 变量值 / Value | 行为 / Behavior |
| --- | --- |
| 不设置、删除变量 / Unset or delete | GitHub-hosted `ubuntu-latest` |
| `ubuntu-24.04` | 指定 GitHub 托管镜像 / Pin a GitHub-hosted image |
| `abk` | 使用具有该标签的 runner / Use a runner with this label |
| `["self-hosted","abk"]` | 同时匹配两个标签，保持本 Fork 原来的 GKI 调度方式 / Match both labels, preserving this fork's previous GKI routing |
| `["self-hosted","linux","x64","abk"]` | 同时匹配全部标签 / Match all listed labels |

单个标签直接填写，不加引号；多个标签使用非空 JSON 字符串数组，以 `[` 开头，标签用双引号包围，不要在数组外再加引号或前导空格。所有标签必须由同一台 runner 同时满足；这不是按顺序尝试的候选机器列表。选择可运行现有构建脚本的 Linux x86_64 / Ubuntu 环境。

Enter a single label without quotes. For multiple labels, use a non-empty JSON array of strings starting with `[`, with double-quoted labels and no outer quotes or leading whitespace. One runner must match every label; the array is not a fallback list. Choose a Linux x86_64 / Ubuntu environment compatible with the existing build scripts.

### 从固定自托管配置迁移 / Migrate from hardcoded self-hosting

在合并 runner 配置改动前，将仓库变量 `KERNEL_RUNNER` 设为 `["self-hosted","abk"]`，即可继续使用原来的 GKI runner。`ONEPLUS_RUNNER` 不设置则维持 GitHub 托管。以后要切回 GitHub，只需把相应变量改为 `ubuntu-latest` 或删除变量；要换机器，则改为新机器的标签。

Before merging the runner configuration change, set `KERNEL_RUNNER` to `["self-hosted","abk"]` to retain the existing GKI runner. Leave `ONEPLUS_RUNNER` unset to retain GitHub hosting for OnePlus. To switch back to GitHub, set the corresponding variable to `ubuntu-latest` or delete it; to switch machines, change the labels.

匹配的自托管 runner 离线或标签不匹配时，任务会排队，不会自动切回 GitHub。修改变量后请新建一次构建；已有任务不会迁移。自托管构建会跳过自动删除 Chrome APT 源的逻辑，但仍需具备原有依赖安装步骤所需的 sudo 权限。

If no matching self-hosted runner is online, jobs queue rather than falling back to GitHub. Start a new build after changing variables; existing jobs are not migrated. Self-hosted builds skip automatic Chrome APT source deletion but still require sudo for the existing dependency installation steps.

## APK 自托管环境 / APK self-hosted setup

ABK 管理器（APK）的两个工作流——`build-abk-app.yml` 和 `build-abk-app-dev.yml`——通过仓库变量 `APP_RUNNER` 选择运行环境。未设置或为空时使用 GitHub 托管的 `ubuntu-latest`；设置后，该值会直接作为 `runs-on`（例如 `self-hosted` 或自定义标签 `abk-builder`）。Fork 默认无需任何配置即可正常工作。

The two ABK manager (APK) workflows — `build-abk-app.yml` and `build-abk-app-dev.yml` — pick their runner via the repository variable `APP_RUNNER`. When unset or empty, both run on the GitHub-hosted `ubuntu-latest`; when set, the value is passed straight through to `runs-on` (e.g. `self-hosted` or a custom label like `abk-builder`). A fresh fork works out of the box with no configuration.

---

## 中文

### 何时需要自托管 Runner

仅在你想要更快的构建、复用本地缓存或避免消耗 GitHub Actions 免费额度时再考虑。否则保留 `APP_RUNNER` 为空即可。

### 系统要求

Linux x86_64（推荐 Ubuntu 24.04 LTS），≥ 16 GB RAM，≥ 80 GB 可用磁盘。

### 安装步骤

1. 系统依赖：

   ```bash
   sudo apt update
   sudo apt install -y build-essential git curl unzip jq python3 python3-pip ca-certificates
   ```

2. JDK 21（Temurin）：

   ```bash
   wget -qO- https://packages.adoptium.net/artifactory/api/gpg/key/public \
     | sudo gpg --dearmor -o /usr/share/keyrings/adoptium.gpg
   echo "deb [signed-by=/usr/share/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(. /etc/os-release && echo $VERSION_CODENAME) main" \
     | sudo tee /etc/apt/sources.list.d/adoptium.list
   sudo apt update && sudo apt install -y temurin-21-jdk
   ```

3. Android SDK 与所需包（命令行工具自行安装并配置 `ANDROID_HOME` / `PATH`）：

   ```bash
   yes | sdkmanager --licenses
   sdkmanager "platforms;android-37.0" "build-tools;37.0.0" "cmake;3.22.1" "ndk;28.2.13676358"
   ```

4. Rust 与目标平台：

   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
   source "$HOME/.cargo/env"
   rustup target add aarch64-linux-android armv7-linux-androideabi x86_64-linux-android \
                     aarch64-unknown-linux-musl x86_64-unknown-linux-musl
   ```

5. 注册 Runner：在仓库的 `Settings → Actions → Runners → New self-hosted runner` 中按页面给出的 `download` 与 `config` 命令操作，然后 `./run.sh` 启动。完整流程参考 [GitHub 官方文档](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/adding-self-hosted-runners)。

6. 在仓库的 `Settings → Secrets and variables → Actions → Variables` 创建变量 `APP_RUNNER`，值为 `self-hosted` 或你为 runner 设置的标签。

7. 在 Actions 页面手动触发 `Build ABK App`，确认任务被你的 runner 接收。

---

## English

### When you need a self-hosted runner

Only when you want faster builds, want to reuse local caches, or want to avoid burning GitHub Actions minutes. Otherwise leave `APP_RUNNER` empty.

### System requirements

Linux x86_64 (Ubuntu 24.04 LTS recommended), ≥ 16 GB RAM, ≥ 80 GB free disk.

### Setup

1. System packages:

   ```bash
   sudo apt update
   sudo apt install -y build-essential git curl unzip jq python3 python3-pip ca-certificates
   ```

2. JDK 21 (Temurin):

   ```bash
   wget -qO- https://packages.adoptium.net/artifactory/api/gpg/key/public \
     | sudo gpg --dearmor -o /usr/share/keyrings/adoptium.gpg
   echo "deb [signed-by=/usr/share/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(. /etc/os-release && echo $VERSION_CODENAME) main" \
     | sudo tee /etc/apt/sources.list.d/adoptium.list
   sudo apt update && sudo apt install -y temurin-21-jdk
   ```

3. Android SDK + required packages (install the command-line tools yourself and export `ANDROID_HOME` / `PATH`):

   ```bash
   yes | sdkmanager --licenses
   sdkmanager "platforms;android-37.0" "build-tools;37.0.0" "cmake;3.22.1" "ndk;28.2.13676358"
   ```

4. Rust + targets:

   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
   source "$HOME/.cargo/env"
   rustup target add aarch64-linux-android armv7-linux-androideabi x86_64-linux-android \
                     aarch64-unknown-linux-musl x86_64-unknown-linux-musl
   ```

5. Register the runner: in the repo, `Settings → Actions → Runners → New self-hosted runner` gives you `download` and `config` commands; follow them, then start with `./run.sh`. Full walkthrough: [GitHub docs](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/adding-self-hosted-runners).

6. In the repo, create `APP_RUNNER` under `Settings → Secrets and variables → Actions → Variables`. Value: `self-hosted` or the custom label you assigned to your runner.

7. Manually trigger `Build ABK App` from the Actions tab and confirm your runner picks up the job.
