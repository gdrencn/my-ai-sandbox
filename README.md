# my-ai-sandbox

基于 LXD 的轻量容器管理工具。Python 标准库实现 CLI 和 TUI，没有第三方 Python 依赖。

## 安装最新测试版

在 Ubuntu 的交互式终端运行：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash
```

安装位置：`~/.local/bin/mas`。安装程序自动配置实际安装目录的 PATH，保留已有配置，重复安装不会重复添加。安装后打开新终端，直接运行 `mas`；不需要手动执行 `export`。

普通安装只下载产品和独立安装程序，不下载或安装测试工具。`--test` 才额外下载 `mas-test.pyz`，由测试工具调用同版本安装程序完成安装，再运行完整测试，并安装 `~/.local/bin/mas-test`。

安装脚本自动安装缺失的 Python 3、snapd、最新稳定渠道的 LXD 及其 lxc 客户端，开始时判断是否需要宿主权限，需要时调用系统 `sudo -v` 认证；后续使用系统默认 sudo 行为。全新 LXD 使用原生自动初始化（dir 存储和默认桥接网络）；已有环境不自动升级或覆盖配置。新增 lxd 用户组权限后，安装过程通过一个刷新用户组的用户进程继续运行，日常使用请打开新终端。

宿主支持范围：Ubuntu 22.04 及更新版本（原生系统和 WSL2），Python 3.10+，需要可运行 snapd 的 systemd 环境。WSL 未启用 systemd 时，安装脚本会给出启用及重启提示。云服务器必须允许容器运行所需的内核功能。当前实际验证环境见 [IMPLEMENTED.md](IMPLEMENTED.md)，不能把支持目标视为所有环境已实测。

入口使用公开 GitHub Releases API 查找最高的 `a.b.c` 数字版本（包含 prerelease），并从该版本下载产品、测试工具和 SHA-256 校验清单。它不会使用忽略 prerelease 的 `/releases/latest`。

安装指定版本：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --release v0.1.4
```

## 语言和配置

安装开始前询问语言：`en_us`（英文）或 `zh_cn`（简体中文）。首次默认中文 `zh_cn`，直接回车即可。后续安装以已保存的语言作为默认值。非交互安装可添加 `--language zh_cn` 或 `--language en_us`，例如：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --language zh_cn
```

```bash
mas config
mas config get language
mas config set language zh_cn
mas config set language en_us
```

TUI 按 `c` 打开配置，按 `1` 选择英文、`2` 选择中文，立即生效；`q` 返回。CLI、TUI 和安装程序共享配置，保存于 `$XDG_CONFIG_HOME/my-ai-sandbox/config.json`，默认 `~/.config/my-ai-sandbox/config.json`。查看和修改配置不需要 LXD。

产品文案集中在 `mas/locales/en_us.json` 和 `mas/locales/zh_cn.json`。LXD、sudo、包管理器原生输出和机器可读字段保留原样。宿主 sudo 完全使用系统认证机制，不保存密码、不保活、不修改 sudo 超时或宿主 sudoers。已准备好的测试环境不需要宿主 sudo。

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

TUI：方向键选择；`n` 创建、`s` 启动、`t` 停止、`a` 停止全部受管理容器、`e` 进入、`d` 删除、`i` 信息、`m` 导入、`x` 导出、`r` 刷新、`c` 配置、`q` 退出。

## 一行安装并自动测试

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --test
```

指定版本及结果目录：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --test --release v0.1.4 --output ./mas-results
```

已安装环境可直接运行 `mas-test`。测试工具与产品版本配套，测试使用独立 LXD project 和 `test-<唯一随机码>` 容器，通过真实 lxc 操作和伪终端测试 CLI/TUI；只清理本次创建的资源。原有容器不参与 `stop --all` 测试。语言测试使用临时配置，不修改用户偏好。英文界面测试的原始输出保留在详细日志中；面向用户的说明、阶段名称和总结始终使用选择的语言，外部程序的原始警告和错误不翻译。

交互终端内，正常进度在同一行刷新并显示等待时长，环节结束后清除；每个环节保留一行成功总结。警告、错误和失败详情保留，故意触发的错误标记为“预期错误”。非交互环境不输出刷新控制符，只保留总结及非正常输出。最终显示通过、失败、未执行数量，总耗时、清理结果和报告路径。

结果包含 JSON 报告、被测产品哈希、完整 CLI stdout/stderr、原生操作输出、终端交互记录、每秒等待记录和清理失败信息。默认保存在当前目录的 `test-results/<时间>/`；显式指定的输出目录必须尚不存在，避免覆盖旧结果。测试失败时后续未执行项标为 `not_run`，不会冒充通过。安装的 LXD、基础存储网络和 LXD 的共享镜像缓存会保留。

测试需要下载镜像及临时磁盘空间。备份文件是临时测试产物，测试结束时删除；报告及日志保留。

## 开发与发布

从 `0.1.3` 起统一使用 `a.b.c`：主版本 `a` 当前固定为 `0`，仅用户明确允许时才能改为 `1`；`b` 为阶段号，目前为 `1`；`c` 为提交批次号，每批递增一次，同一批中的多个 Git commit 不重复递增。不再使用 `-test.x` 后缀，GitHub prerelease 属性单独保留。


```bash
python3 -m unittest discover -v
python3 -m mas.testing
python3 scripts/build.py
python3 dist/mas.pyz --version
```

`dist/mas.pyz` 为产品，不包含安装模块、测试代码或测试专用文案；`dist/mas-install.pyz` 为独立安装程序；`dist/mas-test.pyz` 为独立测试工具。三个文件版本一致。测试工具通过安装程序完成安装，安装程序不负责启动测试。仅使用标准库 zipapp 打包，适用于已具备受支持 Python 运行时的架构。

发布前核验 [REQUIREMENTS.md](REQUIREMENTS.md) 并更新 [IMPLEMENTED.md](IMPLEMENTED.md)。GitHub prerelease 保留版本资产、安装脚本、校验清单及测试报告。第一版没有 GPU 或模型工具自动安装功能。

`install.sh` 由 `scripts/install.template.sh` 和语言文案生成；修改后运行 `python3 scripts/build.py`，避免手工维护重复提示文案。

`0.1.4` 起采用三个独立文件的分发方式。指定更早的数字版本时，固定入口复用该历史版本原有的安装实现和打包方式，不改写已发布文件。
