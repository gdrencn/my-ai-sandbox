# my-ai-sandbox

基于 LXD 的轻量容器管理工具。Python 标准库实现 CLI 和 终端文本菜单，没有第三方 Python 依赖。

## 安装阶段 1 稳定版（0.1.15）

[Stable 发布](https://github.com/gdrencn/my-ai-sandbox/releases/tag/stable/0.1.15) 已发布；产品和安装程序与 [同版本 test 发布](https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.15) 完全一致。固定入口安装最新 stable：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/stable/install.sh | bash
```

这个命令只下载安装所需文件，不下载测试工具。稳定版附件为产品、独立安装程序和校验清单；Git tag `stable/0.1.15` 仅用于区分发布渠道，程序版本仍为 `0.1.15`。stable 入口从 GitHub latest 解析当前稳定发布；产品版本与发布通道分开。

需要验证稳定版时，使用同版本 test 发布的自动化测试工具：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/test-stable.sh | bash
```

不指定 `--release` 的原有入口仍安装最新测试版，不会因为本次 stable 发布而改变含义。发布前复核通过 162 项单元测试及全部 21 个测试环节，详情见 [审查记录](validation/STABLE_0_1_15_AUDIT.md) 与 [已实现文档](IMPLEMENTED.md)。

## 安装最新测试版

本批 `0.2.11` 已完成固定 Project/Profile 隔离配置、完整设备核验、旧容器显式迁移和临时 Project 备份导入方案。本地通过 287 项单元测试及全部 26 个回归环节；公开发布验证进行中。完整范围和验证记录见 [IMPLEMENTED.md](IMPLEMENTED.md)。

在 Ubuntu 的交互式终端运行：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/install.sh | bash
```

安装位置：`~/.local/bin/mas`。安装程序自动配置实际安装目录的 PATH，保留已有配置，重复安装不会重复添加。安装后打开新终端，直接运行 `mas`；不需要手动执行 `export`。

普通安装只下载产品和独立安装程序，不下载或安装测试工具。`test/test.sh`（或旧入口 `--test`）才额外下载 `mas-test.pyz`，由测试工具调用同版本安装程序完成安装，再运行完整测试，并安装 `~/.local/bin/mas-test`。

安装脚本自动安装缺失的 Python 3、snapd、最新稳定渠道的 LXD 及其 lxc 客户端，以及宿主 SSHFS，先统一检测缺失依赖，需要 APT 时只刷新一次索引并合并安装；不再单独执行 `sudo -v`，由实际提权命令触发系统认证。正常 APT 进度在终端原地刷新，保留环节总结、警告和错误。sudo 自身连接终端，APT 的输出处理管道位于其内部命令中；重定向输出时软件包输入按非交互 EOF 处理，认证仍由系统 sudo 负责。全新 LXD 使用原生自动初始化（dir 存储和默认桥接网络）；已有环境不自动升级或覆盖配置。安装程序通过独立 systemd drop-in 为 LXD 主 socket 指定实际管理组，保持 `0660`，必要时修正现有 socket 属组；不重启正在运行的 LXD 或容器。用户组准备遵循 LXD 配置的管理组（默认 `lxd`），在目标用户身份下确认 LXD 可访问才报告安装成功。新增管理组权限后，安装过程通过一个刷新用户组的用户进程继续运行，日常使用请打开新终端。

宿主支持范围：Ubuntu 22.04 及更新版本（原生系统和 WSL2），Python 3.10+，需要可运行 snapd 的 systemd 环境。WSL 未启用 systemd 时，安装脚本会给出启用及重启提示。云服务器必须允许容器运行所需的内核功能。当前实际验证环境见 [IMPLEMENTED.md](IMPLEMENTED.md)，不能把支持目标视为所有环境已实测。

test 入口使用公开 GitHub Releases API 查找最高的 `a.b.c` 数字版本（包含 prerelease），并从该版本下载产品、测试工具和 SHA-256 校验清单。test 入口不使用 `/releases/latest`；stable 入口使用它选择 stable 产品，stable 测试入口再选择同一数字版本的测试发布，校验产品及安装包一致后执行，缺失或不一致均报错。

安装指定版本：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --release v0.1.15
```

## 固定发布入口

| 入口 | 行为 |
|---|---|
| `stable/install.sh` | 安装最新 stable |
| `test/install.sh` | 安装最新 test，不运行测试 |
| `test/test.sh` | 安装并测试最新 test |
| `test/test-stable.sh` | 安装并测试当前 stable 的同版本产品 |

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/test.sh | bash
```

这些入口由同一个模板生成，仅转发通道和动作到共享安装入口。原 `main/install.sh` 及其 `--test`、`--release` 参数继续兼容。发布附件同时提供 `install-stable.sh`、`install-test.sh`、`test.sh`、`test-stable.sh`，固定入口始终解析当前通道版本。

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

终端文本菜单的主菜单选择“mas 选项”，进入语言菜单后用 ↑/↓ 选择，Enter 确认，立即生效；Esc/← 返回。CLI、终端文本菜单 和安装程序共享配置，保存于 `$XDG_CONFIG_HOME/my-ai-sandbox/config.json`，默认 `~/.config/my-ai-sandbox/config.json`。查看和修改配置不需要 LXD。

产品文案集中在 `mas/locales/en_us.json` 和 `mas/locales/zh_cn.json`。LXD、sudo、包管理器原生输出和机器可读字段保留原样。宿主 sudo 完全使用系统认证机制，不保存密码、不保活、不修改 sudo 超时或宿主 sudoers。已准备好的测试环境不需要宿主 sudo。

## 使用

```bash
mas                                    # 打开 终端文本菜单
mas new demo                           # 默认匹配宿主 Ubuntu 版本
mas new other --image ubuntu:24.04      # 指定镜像
mas list
mas info demo
mas start demo
mas enter demo
mas stop demo
mas stop --all                         # 仅停止 mas 管理的容器
mas export demo demo.tar.gz
mas delete demo                        # 菜单默认选“否”，可选择“是”确认
mas import restored demo.tar.gz
```

- 创建后容器保持停止。WSL 的默认镜像版本取自 WSL 内部的 Ubuntu；对应镜像不可用时明确报错，不降级。
- 启动功能内部准备默认用户 `sandbox`，允许其免密 sudo；用户准备成功后，mas 启动功能才算完成。进入容器使用 sandbox 的登录 shell；root 账户不设空密码。
- `enter` 必要时调用共享启动功能。终端内 `exit` 后询问是否停止，默认选“否”。收尾输出后结束本次 mas，回到宿主终端；菜单进入也不会返回 mas 菜单，收尾失败则报错退出。
- 删除和导出要求容器已停止。CLI 和 终端文本菜单 删除都要确认；导出文件存在时询问是否覆盖，默认选“否”。导入要求目标名称不存在。
- 0.2.11 起仅管理本地 LXD `mas` Project 内标记为 `user.mas.managed=true` 的容器；不接管原生 lxc 创建的其他容器。该标记用于管理范围区分，不是对拥有 LXD 管理权限的用户的安全隔离。
- 每秒探测一次，默认每个底层操作最多等待 10 分钟。可使用 `mas --timeout 1800 start demo` 延长，最小 300 秒。明确失败立即返回，成功必须同时满足原生命令完成和目标状态。
- 阶段 1 稳定版不配置 GPU。0.2.1 测试版新增下述 GPU 模块；网络仍使用原有默认配置，不增加端口映射或网络控制。

**备份是恢复用途，并非克隆模板。** LXD 导出会保留网卡 MAC。源容器与导入副本同时存在时，LXD 可能拒绝启动副本。恢复前先处理原容器；mas 不静默改写备份中的网络身份。

直接运行 `mas` 显示一级菜单“查看容器”“新建容器”“导入容器”“迁移旧容器”“mas 选项”“退出”，不再套一层容器管理入口。“停止全部容器”位于容器列表末尾、返回之前，仅在 mas 管理的容器超过一个且未全部处于 LXD 的 `Stopped` 状态时显示；CLI `stop --all` 的行为保持不变。选中容器后进入信息、启动、进入终端、停止、导出、删除、挂载查询、挂载、卸载菜单。所有菜单每项独立一行、左对齐，↑/↓ 循环移动（首项向上到末项、末项向下到首项），Enter/→ 确定，Esc/← 返回。菜单直接显示在当前终端位置，仅局部刷新当前菜单，不切换全屏、不清屏，历史输出可以向上滚动查看。执行操作时正常等待进度在同一行刷新，最终结果和诊断保留，每个功能先以空行和标题明确进入，结果、错误或取消后停留在“操作结果／返回”，主动返回后才恢复上级菜单及原选中项。容器终端退出按上文规则直接返回宿主；其他操作使用返回页。容器列表保留自己的选择和返回页；容器信息完整输出，进入容器使用正常终端会话。

所有输入提示明确说明要输入的内容和空值含义；标题、输入、结果和返回页之间统一空行。多列选择按显示宽度用空格左对齐；需要状态列时整列统一显示。卸载菜单直接列出容器路径，不重复输出表格；有异常条目时全部条目显示状态。

CLI 的语言和确认提示使用同一套菜单。自动化调用可以使用 `mas delete demo --yes`、`mas export demo backup.tar.gz --yes`；`--no` 明确拒绝。`mas enter demo --yes` 表示终端退出后停止容器，`--no` 表示保持运行。没有交互终端且未指定确认参数时默认拒绝；不再使用管道输入 `y` 确认。

## 固定隔离配置与旧容器迁移（0.2.11 起）

安装程序创建专用的 `mas` Project，以及其中的 `mas` 和 `default` Profile。配置固定，不提供通用设置入口。容器使用非特权、独立 UID/GID 映射和 LXD 标准 namespace/seccomp；不启用 nesting、raw 配置、BPF 委派或宿主身份例外。容器内 root 和 sandbox 的免密 sudo 保留。网卡继续连接已有的 LXD managed bridge，本批不增加流量或登录限制。

GPU 是明确授权的资源例外。WSL NVIDIA 映射 `/dev/dxg`、只读运行库和经过官方探测选择的驱动目录；Project 仅允许对应目录前缀。GPU 开关仍位于容器硬件选项。程序核验完整的 expanded 配置和设备，拒绝额外宿主目录、任意字符设备、额外存储卷、管理 socket、Windows 挂载及被改写的 GPU 映射；类别级的 Project 允许值不代表任意硬件已获授权。具体配置见 [需求文档第 39 节](REQUIREMENTS.md#39-fixed-isolation-policy-and-effective-configuration-verification--v0211)。

旧版容器仍保留在 `default`，升级不自动迁移。选择“迁移旧容器”或执行：

```bash
mas mountedfs demo --legacy
mas unmountfs demo /home/sandbox --legacy  # 若有记录，逐条精确卸载
lxc --project default stop demo           # 若旧容器仍在运行，先停止
mas migrate demo                         # 默认拒绝，确认后迁移
mas migrate demo --yes                    # 已明确同意的自动化操作
```

迁移前检查管理标记、停止状态、没有挂载记录、目标名称可用和配置合规。拒绝或取消时保留源容器；成功时使用 LXD 原生 move，应用固定 Profile 并保留安全的原配置及用户数据。失败由原生 LXD 状态决定；客户端超时不等于后台任务已取消，不增加自定义回滚。

LXD 6.9 的备份导入会携带 volatile 身份元数据，直接导入固定限制的 Project 会被拒绝。因此，`mas import` 先创建一个带归属记录的临时 Project，仅临时放开 lowlevel，原生导入后保持停止、关闭临时 autostart，核验后原生复制到正式 Project。正式限制不放宽，容器文件权限不由 mas 改写，原备份格式不变。成功后清理临时资源，再完成管理标记与最终核验。

导入失败不会删除原备份或已经导入的数据；提示会给出临时 Project 和容器名。可用 `lxc --project PROJECT config show TARGET --expanded`、`lxc --project PROJECT info TARGET` 进行原生检查。修复或回收由用户明确操作；程序不自动启动失败数据，也不静默接管未完成的目标。没有导入数据的空临时 Project 可以自动清理。

当前实测 WSL 内核未启用 AppArmor，报告如实记录为 `unconfined`；本批没有修改宿主内核配置。原生 Ubuntu、其他 GPU/存储后端和上游漏洞修复不属于当前 WSL 验证结果。CPU、内存和进程限制、额外网络策略、完全关闭 devlxd、宿主 AppArmor 配置及磁盘配额仍待后续讨论。

## 容器文件系统挂载（0.1.9 起）

```bash
mas mountfs demo                 # 默认 home → ~/LXDCMFS/demo/home/sandbox
mas mountfs demo /var/log        # → ~/LXDCMFS/demo/var/log
mas mountedfs demo              # 查看精确挂载路径、宿主路径和状态
mas unmountfs demo /var/log
mas unmountfs demo               # 卸载此前默认 home 挂载
mas mountfs demo /               # 根目录 → ~/LXDCMFS/demo
mas unmountfs demo /
```

省略路径时读取 sandbox 用户实际 home；未准备该用户时不会为了挂载而启动容器。显式路径只接受绝对路径，不接受上级跳转、控制字符或符号链接路径。根路径映射是目录组织规则，挂载 home 不会同时挂载整个根目录。

挂载可读写，宿主创建、修改、删除文件直接作用于容器。使用 LXD 原生本地 SFTP 服务和以当前宿主用户运行的 SSHFS，容器不安装 SSH 服务。保留原生权限行为，不改写原文件的 UID/GID、权限或 ACL，不自行增加身份映射。新建文件也遵循原生行为，不保证归 sandbox 所有。挂载内容的符号链接行为遵循宿主 SSHFS 版本默认行为；本功能不是额外安全隔离层。

从 0.1.11 起，新挂载使用 `allow_root`，允许挂载用户与宿主 root 访问，兼容 Windows 经 WSL 的文件访问；不会开放给其他普通宿主用户。安装程序会在需要时启用宿主 `/etc/fuse.conf` 的 `user_allow_other` 配置开关，保留已有设置；实际挂载仍使用 `allow_root`。旧挂载不会自动改变，需要先 `mas unmountfs TARGET [PATH]`，再重新 `mas mountfs TARGET [PATH]`。

只管理当前用户创建的挂载。状态保存在 `$XDG_STATE_HOME/my-ai-sandbox/filesystems`，默认 `~/.local/state/my-ai-sandbox/filesystems`，连接资料仅当前用户可访问。普通 CLI 退出后挂载继续存在。

挂载仍由 `mountfs` / `unmountfs` 显式管理。改变启停状态前，mas 记录当前用户已有的挂载路径，逐个调用共享卸载功能；启停成功后逐个调用共享挂载功能，恢复原路径和默认 home 标记。卸载第一次失败就停止，不进入启停，也不回滚之前的卸载；启停本身失败沿用原来的错误处理，后置挂载自然不执行。恢复挂载失败仍继续其余路径，最后列出需要手动恢复的路径并说明启停已完成。重复启动运行中容器或停止已停止容器不会拆卸挂载。

**删除仍要求先手动卸载。** 同一用户的挂载和启停/删除共用记录锁，基础功能嵌套调用复用同一个锁，在锁内重新检查归属和状态。原生 lxc 操作和其他用户的挂载不受本用户记录锁协调。

目标挂载点已存在时拒绝操作，即使是空目录。可复用本工具记录的公共父目录，但不能遮盖用户目录或其他挂载。允许多个互不包含的路径；拒绝父子重叠。卸载必须精确匹配：挂载 `/` 后，卸载 `/var/log` 会报错，不会替你卸载 `/`。

成功卸载后只回收本工具创建的空目录；失败挂载也按同一规则回收。占用、非空、身份变化或无法确认归属时保留并报错，不递归删除内容。使用 `mountedfs` 查看异常/残留条目，再执行对应 `unmountfs` 清理。WSL 关闭后挂载不保留，残留目录需要按记录清理后再挂载；新记录通过文件系统标识、inode 和属主核验目录；旧版设备号记录若无法核验则保留并报错，不擅自迁移。离线 VHDX 访问不在本功能范围内。

即使容器已被外部删除或替换，`mountedfs` 和明确路径的 `unmountfs` 仍可处理原有宿主记录，不会操作替换后的容器。默认卸载优先使用记录中的原 home。记录损坏或辅助进程身份不符时保留现场并报错。

## 一行安装并自动测试

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --test
```

指定版本及结果目录：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --test --release v0.1.15 --output ./mas-results
```

已安装环境可直接运行 `mas-test`。测试工具与产品版本配套，测试使用独立 LXD project 和 `test-<唯一随机码>` 容器，通过真实 lxc 操作和伪终端测试 CLI/终端文本菜单；只清理本次创建的资源。依赖安装测试会在临时容器内通过系统 sudo 更新 APT 索引并安装 SSHFS，以验证真实提权与终端组合，不改变产品的容器预装行为。原有容器不参与 `stop --all` 测试。语言测试使用临时配置，不修改用户偏好。英文界面测试的原始输出保留在详细日志中；面向用户的说明、阶段名称和总结始终使用选择的语言，外部程序的原始警告和错误不翻译。

交互终端内，正常进度在同一行刷新并显示等待时长，环节结束后清除；每个环节保留一行成功总结。警告、错误和失败详情保留，故意触发的错误标记为“预期错误”。非交互环境不输出刷新控制符，只保留总结及非正常输出。最终显示通过、失败、未执行数量，总耗时、清理结果和报告路径。

结果包含 JSON 报告、被测产品哈希、完整 CLI stdout/stderr、原生操作输出、终端交互记录、每秒等待记录和清理失败信息。默认保存在当前目录的 `test-results/<时间>/`；显式指定的输出目录必须尚不存在，避免覆盖旧结果。测试失败时后续未执行项标为 `not_run`，不会冒充通过。安装的 LXD、基础存储网络和 LXD 的共享镜像缓存会保留。

测试需要下载镜像及临时磁盘空间。备份文件是临时测试产物，测试结束时删除；报告及日志保留。

## 开发与发布

从 `0.1.3` 起统一使用 `a.b.c`：主版本 `a` 当前固定为 `0`，仅用户明确允许时才能改为 `1`；`b` 为阶段号，当前测试开发进入 `2`（阶段 1 稳定版仍为 `0.1.15`）；`c` 为提交批次号，每批递增一次，同一批中的多个 Git commit 不重复递增。不再使用 `-test.x` 后缀，GitHub prerelease 属性单独保留。


```bash
python3 -m unittest discover -v
python3 -m mas.testing
python3 scripts/build.py
python3 dist/mas.pyz --version
```

`dist/mas.pyz` 为产品，不包含安装模块、测试代码或测试专用文案；`dist/mas-install.pyz` 为独立安装程序；`dist/mas-test.pyz` 为独立测试工具。三个文件版本一致。测试工具通过安装程序完成安装，安装程序不负责启动测试。仅使用标准库生成可重复构建的 zipapp，适用于已具备受支持 Python 运行时的架构。

发布验证必须从仓库外的临时工作目录运行打包后的测试工具，使用产品及测试包的绝对路径；不能只在源码目录验证。Python 测试子进程统一使用 `mas.testing.python_command` 显式指定当前测试包来源，不依赖工作目录或 `PYTHONPATH`。

发布前核验 [REQUIREMENTS.md](REQUIREMENTS.md) 并更新 [IMPLEMENTED.md](IMPLEMENTED.md)。GitHub prerelease 保留版本资产、安装脚本、校验清单及测试报告。阶段 1 没有 GPU 接入功能；0.2.1 新增 GPU 模块，不自动安装模型工具。

`install.sh` 由 `scripts/install.template.sh` 和语言文案生成；修改后运行 `python3 scripts/build.py`，避免手工维护重复提示文案。

`0.1.4` 起采用三个独立文件的分发方式。指定更早的数字版本时，固定入口复用该历史版本原有的安装实现和打包方式，不改写已发布文件。


测试覆盖范围与未验证环境见 [TEST_COVERAGE.md](TEST_COVERAGE.md)。基础操作在原生命令前后增加的逻辑见 [CORE_BEHAVIOR.md](CORE_BEHAVIOR.md)。测试报告的 `unit_tests` 字段记录单元测试数量、模块、测试标识和跳过原因；测试组结果仍单独记录。请勿用 Python `-O` 或 `PYTHONOPTIMIZE` 运行测试，它们会禁用断言。


内部按职责区分外部前处理、完整的 mas 功能、外部后处理。启动中的 sandbox 用户准备属于启动内部，成功后才恢复挂载；原生启动成功本身不代表 mas 启动完成。其它基础功能的职责和成功条件见 [CORE_BEHAVIOR.md](CORE_BEHAVIOR.md)。不需要外部处理的功能不增加空阶段。


## GPU 硬件选项（0.2.x test）

选中容器后进入“硬件选项”，第一个选项为 GPU 开关。有受支持的独立显卡时默认开启，可以手动关闭；没有受支持设备时不显示此开关。目前接入实现针对 NVIDIA，已实测 WSL2 + RTX 5090 Laptop GPU；原生 Ubuntu NVIDIA 使用 LXD CDI 路径，尚未实机验证。AMD/Intel 独立显卡尚未实现自动识别和接入。

```bash
mas hardware TARGET             # 查询能力、配置值及资源清单
mas hardware TARGET gpu         # 查询同一 GPU 配置
mas stop TARGET
mas hardware TARGET gpu off     # 关闭并撤销模块提供的资源
mas hardware TARGET gpu on      # 开启
mas start TARGET
```

修改 GPU 配置要求容器已停止，不会自动停止正在运行的任务。显式关闭会跨启停保留。新建容器自动配置默认 GPU；已有或导入的未配置容器在下一次从停止状态启动时应用默认值，已运行的旧容器不会被静默热修改。菜单会标明尚未应用的默认值。

WSL 路径提供 `/dev/dxg`、只读的 `/usr/lib/wsl/lib` 和官方探测选中的当前 NVIDIA 驱动子目录；不映射整个 Windows 驱动目录。WSL DXG 访问不是逐卡隔离。设备清单、驱动目录、配置值和运行库配置文件路径记录在 `user.mas.gpu`。模块管理容器内 `/etc/ld.so.conf.d/mas-gpu.conf`，启动时刷新动态链接库缓存；关闭时删除该文件及设备，下一次启动刷新缓存。检测到资源配置漂移或文件冲突会报错，不覆盖不属于模块的资源。GPU 库路径可供普通 sandbox 用户加载；WSL 的诊断工具可通过 `/usr/lib/wsl/lib/nvidia-smi` 调用。

测试工具会验证开关、菜单、只读资源、关闭后的设备消失、重新开启，以及 sandbox 用户执行真实 CUDA 内核并读回结果。无支持设备的机器明确记录 GPU 计算未执行。此模块不安装 CUDA Toolkit、模型框架或新的宿主驱动。Project/profile 安全基线、CPU/内存/进程限制仍待后续实现。

从 0.2.3 起，WSL 驱动目录由 LXD snap 已附带的 `nvidia-ctk` 以 WSL 模式探测，不扫描全部历史目录。GPU 开启时，每次实际启动前重新查询并复用 GPU 配置函数更新映射，运行期间不自动修改。工具缺失、探测失败或结果无效会报错，不继续使用旧选择。mas 只读取官方工具输出的资源清单，不应用 CDI 文档或执行 hooks，也不额外安装软件包。

0.2.4 使用官方参数关闭本查询不需要的 hooks 生成和 nvsandboxutils 探测；当前实测资源清单不变，单次警告由 5 条减少为 2 条。剩余原生警告继续保留，并在输出前清除临时进度。测试中的直接诊断保存在 `native-diagnostics.log`，CLI/菜单查询诊断进入事件记录。

0.2.6 的 WSL 探测显式设置 `--library-search-path=/usr/lib/wsl/lib`，避免 NVML 误选普通 Linux 驱动库。产品在探测成功并通过资源校验后不显示已知的多个驱动目录提示；自动化测试保留原文，其他诊断不受影响。GPU 模块另管理容器内 `/etc/profile.d/mas-gpu.sh`，新登录 shell 可直接运行 `nvidia-smi`；关闭时清理模块自有文件，不修改宿主或用户 `.bashrc`。实际生效目录通过宿主 CUDA 加载映射与容器配置独立对比验证。
