# Kernel runner configuration and GKI download cache

通过仓库设置选择构建机器，并减少自托管 GKI 构建的重复下载。

在 `Settings → Secrets and variables → Actions → Variables` 中创建 **Repository variables**。这些配置不占用 workflow dispatch 参数，App/CLI 无需额外传参。

| 变量 | 用途 | 未配置时 |
| --- | --- | --- |
| `KERNEL_RUNNER` | GKI runner 标签，例如 `abk` 或 `["self-hosted","linux","x64","abk"]` | `ubuntu-latest` |
| `KERNEL_SELF_HOSTED` | `false` 强制 GitHub 托管，`true` 恢复保存的 GKI 标签 | 使用原标签配置 |
| `ONEPLUS_RUNNER` | 独立的 OnePlus/Oplus runner 标签 | `ubuntu-latest` |
| `ONEPLUS_SELF_HOSTED` | OnePlus/Oplus 对应开关 | 使用原标签配置 |
| `KERNEL_LOCAL_CACHE` | GKI 自托管下载缓存；设为 `off` 可关闭 | 自托管启用、GitHub 托管关闭 |
| `KERNEL_LOCAL_CACHE_DIR` | 缓存根目录，必须是工作目录之外的绝对路径 | `~/.cache/abk-downloads` |

单标签直接填文本；多标签使用以 `[` 开头的非空 JSON 字符串数组，不加外层引号或前导空格。一台 runner 必须同时满足全部标签。开关值填写 `true` 或 `false`，不加引号；未保存机器标签时，即使开关为 `true` 也仍使用默认 GitHub runner。离线或没有匹配标签时任务排队，不会自动回退。变量只影响新提交的构建。

## 缓存范围与隔离

下载缓存覆盖 GKI 的 AOSP/Clang/Rust/JDK 源码与预编译资源、GCC、打包工具、AnyKernel3、SUSFS 和公共补丁资源。OnePlus 的 runner 可独立配置。

缓存按仓库 URL、manifest 分支和调用方仓库隔离，放在 Actions 工作目录之外。分支和标签每次查询上游，提交不变则复用 Git 对象；变化时只获取缺少的对象。SUSFS 固定提交支持短/完整 SHA，首次保存分支完整历史，之后从该历史检出指定提交。

每轮构建使用独立源码文件和 Git 元数据，补丁不会写入缓存。仅不可变 Git pack/index 文件可能使用硬链接；跨文件系统时退回复制。缓存更新使用文件锁，网络查询失败会终止，不会静默使用旧分支。GitHub 托管构建继续使用原云端缓存；自托管缓存启用时复用本机 ccache。

首次下载仍需要时间和额外磁盘空间；清理缓存前应等待使用它的构建结束。默认适用于现有 Linux x86_64/Ubuntu 工具链环境。

## English

Set repository Actions Variables to choose runners without adding dispatch inputs or modifying the App/CLI. `KERNEL_RUNNER` and `ONEPLUS_RUNNER` accept a plain label or a non-empty JSON array of labels; unset values use `ubuntu-latest`. Set the corresponding `*_SELF_HOSTED` variable to `false` to force GitHub hosting, or `true` to restore saved labels. Unset toggles preserve existing selection. Offline self-hosted runners queue jobs rather than falling back.

The persistent download cache applies to GKI AOSP manifests, toolchains, SUSFS, AnyKernel3 and common patch repositories. Set `KERNEL_LOCAL_CACHE=off` to opt out, or provide an absolute `KERNEL_LOCAL_CACHE_DIR` outside the workspace. Each build receives independent source files and Git metadata; only immutable Git packs may be hard-linked. Remote refs are checked on every branch build, fixed SUSFS revisions remain pinned, and errors do not silently reuse stale branch data. Cache directories are repository-isolated and locked during updates.
