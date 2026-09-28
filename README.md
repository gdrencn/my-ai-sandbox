# my-ai-sandbox

基于 LXD 的轻量容器管理工具。Python 标准库实现 CLI 和 TUI，没有第三方 Python 依赖。

## 安装最新 test 版

在 Ubuntu 的交互式终端运行：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash
```

安装位置：`~/.local/bin/mas` 和 `~/.local/bin/mas-test`。若该目录不在 PATH：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

安装脚本自动安装缺失的 Python 3、snapd、最新稳定渠道的 LXD 及其 lxc 客户端，必要时提示 sudo 密码。全新 LXD 使用原生自动初始化（dir 存储和默认桥接网络）；已有环境不自动升级或覆盖配置。新增 lxd 用户组权限后，安装过程通过一个刷新用户组的用户进程继续运行，日常使用请打开新终端。

宿主支持范围：Ubuntu 22.04 及更新版本（原生系统和 WSL2），Python 3.10+，需要可运行 snapd 的 systemd 环境。WSL 未启用 systemd 时，安装脚本会给出启用及重启提示。云服务器必须允许容器运行所需的内核功能。当前实际验证环境见 [IMPLEMENTED.md](IMPLEMENTED.md)，不能把支持目标视为所有环境已实测。

入口使用公开 GitHub Releases API 查找最新 test prerelease，并从该版本下载产品、测试工具和 SHA-256 校验清单。它不会使用忽略 prerelease 的 `/releases/latest`。

安装指定版本：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --release v0.1.0-test.2
```

## 使用

```bash
mas                                    # 打开 TUI
mas new demo                           # 默认匹配宿主 Ubuntu 版本
mas new other --image ubuntu:24.04      # 指定镜像
mas list
mas info demo
mas start demo
mas enter demo
mas stop demo
mas stop --all                         # 仅停止 mas 管理的容器
mas export demo demo.tar.gz
mas delete demo                        # 默认 N，输入 y 确认
mas import restored demo.tar.gz
```

- 创建后容器保持停止。WSL 的默认镜像版本取自 WSL 内部的 Ubuntu；对应镜像不可用时明确报错，不降级。
- 启动的后置处理准备默认用户 `sandbox`，允许其免密 sudo。进入容器使用 sandbox 的登录 shell；root 账户不设空密码。
- `enter` 必要时调用共享启动功能。终端内 `exit` 后询问是否停止，默认 N。
- 删除和导出要求容器已停止。CLI 和 TUI 删除都要确认；导出文件存在时询问是否覆盖，默认 N。导入要求目标名称不存在。
- 仅管理本地 LXD 默认 project 内标记为 `user.mas.managed=true` 的容器；不接管原生 lxc 创建的其他容器。该标记用于管理范围区分，不是对拥有 LXD 管理权限的用户的安全隔离。
- 每秒探测一次，默认每个底层操作最多等待 10 分钟。可使用 `mas --timeout 1800 start demo` 延长，最小 300 秒。明确失败立即返回，成功必须同时满足原生命令完成和目标状态。
- 本版不配置 GPU、目录共享或自定义端口映射。容器使用标准默认 profile，宿主网络配置必须允许外网访问。

**备份是恢复用途，并非克隆模板。** LXD 导出会保留网卡 MAC。源容器与导入副本同时存在时，LXD 可能拒绝启动副本。恢复前先处理原容器；mas 不静默改写备份中的网络身份。

TUI：方向键选择；`n` 创建、`s` 启动、`t` 停止、`a` 停止全部受管理容器、`e` 进入、`d` 删除、`i` 信息、`m` 导入、`x` 导出、`r` 刷新、`q` 退出。

## 一行安装并自动测试

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --test
```

指定版本及结果目录：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --test --release v0.1.0-test.2 --output ./mas-results
```

已安装环境可直接运行 `mas-test`。测试工具与产品版本配套，测试使用独立 LXD project 和 `test-<唯一随机码>` 容器，通过真实 lxc 操作和伪终端测试 CLI/TUI；只清理本次创建的资源。原有容器不参与 `stop --all` 测试。

结果包含 JSON 报告、被测产品哈希、CLI 日志、终端交互记录、等待时长和清理失败信息。默认保存在当前目录的 `test-results/<时间>/`；显式指定的输出目录必须尚不存在，避免覆盖旧结果。测试失败时后续未执行项标为 `not_run`，不会冒充通过。安装的 LXD、基础存储网络和 LXD 的共享镜像缓存会保留。

测试需要下载镜像及临时磁盘空间。备份文件是临时测试产物，测试结束时删除；报告及日志保留。

## 开发与发布

```bash
python3 -m unittest discover -v
python3 -m mas.testing
python3 scripts/build.py
python3 dist/mas.pyz --version
```

`dist/mas.pyz` 为产品，`dist/mas-test.pyz` 为包含相同产品代码及测试的独立工具。仅使用标准库 zipapp 打包，适用于已具备受支持 Python 运行时的架构。

发布前核验 [REQUIREMENTS.md](REQUIREMENTS.md) 并更新 [IMPLEMENTED.md](IMPLEMENTED.md)。GitHub test prerelease 保留版本资产、安装脚本、校验清单及测试报告。第一版没有 GPU 或模型工具自动安装功能。
