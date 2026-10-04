# my-ai-sandbox — stable 0.2.24

基于 LXD 的容器管理工具，Python 标准库实现 CLI 和终端文本菜单。

## 安装稳定版

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/release/install.sh | bash
```

安装链从 release 分支读取共享引导源码，从 GitHub latest 选择 stable 发布并校验产品和独立安装程序。普通安装不下载、安装或覆盖测试工具。安装位置为 ~/.local/bin/mas；安装程序配置 PATH，安装后打开新终端运行 mas。

宿主目标为 Ubuntu 22.04+（原生系统或 WSL2）、Python 3.10+，需要启用 systemd 的 snapd/LXD 环境。安装程序准备缺失的 Python、snapd、稳定渠道 LXD、lxc 和 SSHFS，并仅在新环境执行 LXD 初始化；已有配置和运行中的容器保留。新加入 LXD 管理组后，请打开新终端。

产品和安装程序与已验收的 [v0.2.24 test 发布](https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.2.24) 字节一致，版本仍为 0.2.24。稳定发布标签为 stable/0.2.24，附件只有 mas.pyz、mas-install.pyz 和 SHA256SUMS。

实测包括 Ubuntu 26.04 WSL、LXD 6.9、NVIDIA x86_64；用户补充验证了 SSHFS/LXD 安装初始化、完整功能与安全检查和实际终端缩放。原生 Ubuntu/cloud、ARM64、其他 GPU/存储后端没有新增实测，内核漏洞和完整网络访问策略不由这些检查保证。

## 构建

release 分支只保留稳定产品、安装源码、共享构建文件和产品文档，没有自动化测试程序、测试入口或验证记录。构建只使用 Python 标准库：

```bash
python3 scripts/build.py --stable
```

输出到 dist：mas.pyz、mas-install.pyz、SHA256SUMS。重复构建可重现已发布的产品和安装包；共享模板生成的根 install.sh 固定读取 release 源码并默认选择 stable。

稳定版的自动化验证入口在开发分支，由它调用 release 安装链并取得与 stable 数字版本一致的 test 工具；稳定分支和稳定附件不包含测试工具。发布记录和验证结果见 [开发分支已实现文档](https://github.com/gdrencn/my-ai-sandbox/blob/main/IMPLEMENTED.md)。

## 语言和配置

安装开始前询问语言：`en_us`（英文）或 `zh_cn`（简体中文）。首次默认中文 `zh_cn`，直接回车即可。后续安装以已保存的语言作为默认值。非交互安装可添加 `--language zh_cn` 或 `--language en_us`，例如：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/release/install.sh | bash -s -- --language zh_cn
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
mas restart demo                       # stop → start
mas restart demo -e                    # stop → enter；也支持 --enter
mas export demo demo.tar.gz
mas delete demo                        # 菜单默认选“否”，可选择“是”确认
mas import restored demo.tar.gz
```

- `new` 按创建、标准启动、初始化安装与验证、标准停止的顺序执行；全部完成后才报告成功，容器保持停止。首次创建需要下载软件，原地滚动显示实际 cloud-init/APT 下载、解包和配置输出；正常输出完成后清除，保留耗时、警告和错误。重定向输出不包含临时滚动行或终端控制码。初始化失败保留容器和原始诊断，仍尝试标准停止；停止失败单独报告。WSL 的默认镜像版本取自 WSL 内部的 Ubuntu；对应镜像不可用时明确报错，不降级。
- 启动功能内部准备默认用户 `sandbox`，允许其免密 sudo；用户准备成功后，mas 启动功能才算完成。进入容器使用 sandbox 的登录 shell；root 账户不设空密码。
- `restart` 顺序调用标准 `stop → start`；`restart -e/--enter` 调用 `stop → enter`，由 enter 完成启动准备。停止失败时不继续。`start` 不增加参数；重启默认不进入终端。
- `enter` 调用共享启动功能。终端结束后提供“停止容器”“重启容器”“返回 mas”“退出 mas”，默认退出，Esc/← 也退出。停止或重启复用标准功能，输出后回宿主终端；返回 mas 打开该容器菜单，不经过操作结果页。非零终端退出码仍报告，不据此猜测 exit/reboot/shutdown；选择返回菜单后，最终 mas 退出状态仍保留失败。CLI `enter --yes/--no` 保持明确停止/退出的兼容行为，`restart --enter` 同样支持；非交互输入默认退出。
- 删除和导出要求容器已停止。CLI 和 终端文本菜单 删除都要确认；导出文件存在时询问是否覆盖，默认选“否”。导入要求目标名称不存在。
- 0.2.11 起仅管理本地 LXD `mas` Project 内标记为 `user.mas.managed=true` 的容器；不接管原生 lxc 创建的其他容器。该标记用于管理范围区分，不是对拥有 LXD 管理权限的用户的安全隔离。
- 每秒探测一次，默认每个底层操作最多等待 10 分钟。可使用 `mas --timeout 1800 start demo` 延长，最小 300 秒。明确失败立即返回，成功必须同时满足原生命令完成和目标状态。
- 本稳定版包含 GPU 接入和每个容器的网络开关，不增加端口映射或流量规则。

**备份是恢复用途，并非克隆模板。** LXD 导出会保留网卡 MAC。源容器与导入副本同时存在时，LXD 可能拒绝启动副本。恢复前先处理原容器；mas 不静默改写备份中的网络身份。

直接运行 `mas` 显示一级菜单“容器列表”“新建容器”“导入容器”“迁移旧版本容器”“mas 选项”“退出”。“停止全部容器”位于容器列表末尾、返回之前，仅在 mas 管理的容器超过一个且未全部处于 LXD 的 `Stopped` 状态时显示；CLI `stop --all` 的行为保持不变。选中容器后显示信息、启动、进入终端、停止、重启、导出、删除、文件系统、硬件选项和返回；文件系统内提供挂载查询、挂载和卸载。信息页先显示名称、状态、GPU 配置与网络状态，可选择“查看完整配置”；CLI `mas info` 仍输出完整 JSON。菜单每项独立一行、左对齐，↑/↓ 循环移动，Enter/→ 确定。Esc/← 在主菜单退出、子菜单返回、单选或多选决策中取消；终端结束菜单的 Esc/← 为退出。文本输入的左右键用于移动光标。

菜单直接显示在当前终端位置，不切换全屏、不清屏。标题和说明保留在历史中，只刷新活动选项；放大/恢复时在原活动区重绘，保留焦点、勾选项和输入位置，短窗口不会丢失输入说明。极窄缩放可能让终端把旧活动行移入历史，组件保留这些历史，只清理仍在当前显示区的活动内容。导航页面标题显示一次，操作先以空行和标题明确进入，等待进度原地刷新，最终结果和诊断保留。普通操作的结果、错误或取消后停留在“操作结果／返回”，主动返回才恢复上级菜单及原选中项。文件系统子菜单也保留选中项；容器终端按上文四选项直接到达所选目的地。

容器内原生 `reboot`/`shutdown` 不经过 mas 的启动准备或文件系统协调。LXD 固定配置仍保留，但未释放的文件挂载连接可能阻碍原生重启；本版不拦截这些命令，也不修正其原生终端换行。需要 mas 标准流程时使用 `mas restart TARGET`。

所有输入提示明确说明要输入的内容和空值含义；标题、输入、结果和返回页之间统一空行。多列选择按显示宽度用空格左对齐；需要状态列时整列统一显示。卸载菜单直接列出容器路径，不重复输出表格；有异常条目时全部条目显示状态。

CLI 的语言和确认提示使用同一套菜单。自动化调用可以使用 `mas delete demo --yes`、`mas export demo backup.tar.gz --yes`；`--no` 明确拒绝。`mas enter demo --yes` 表示终端退出后停止容器，`--no` 表示保持运行。没有交互终端且未指定确认参数时默认拒绝；不再使用管道输入 `y` 确认。

## 新容器开发环境（0.2.20 起）

`new` 在首次启动中使用 Ubuntu 原生 cloud-init 和 APT 准备常用应用开发环境。完整预装清单如下：

| 用途 | 软件包 |
| --- | --- |
| 基础权限与网络、SSH 客户端 | sudo、ca-certificates、curl、wget、openssh-client |
| 版本管理 | git |
| Node.js/npm | nodejs、npm |
| Python | python3、python3-venv、python3-pip、python3-dev |
| 编译基础 | build-essential、pkg-config |
| 常用命令与 Shell 检查 | ripgrep、jq、patch、file、shellcheck |
| 压缩与归档 | tar、gzip、xz-utils、zip、unzip、zstd |

0.2.21 起，完整的 25 个预装软件包均来自 Ubuntu APT，包括 `nodejs` 和 `npm`，提供 `node`、`npm`、`npx`。版本随所选 Ubuntu 镜像及其仓库确定，用户可按需自行安装 Node.js 官方 LTS 或版本管理器。已有容器的软件保持现状，升级 mas 不替换已有 Node.js 安装。Python 使用 Ubuntu 标准软件包；项目依赖可使用 `python3 -m venv .venv` 后安装。SSH 客户端提供 `ssh`、`scp`、`sftp`。

准备成功后撤下本次 cloud-init 安装配置，软件和版本记录保存在容器 `/var/lib/mas/development.json`。后续 start、restart、enter、备份导入不会重复安装这些开发软件，也不会补回用户卸载的软件。新容器卸载 sudo 后，启动会提示缺少必需能力，由用户自行安装恢复；旧容器和未初始化的导入容器沿用原有用户准备行为。已有容器不会自动补装这份清单。

0.2.22 的安装进度使用一行临时显示最新原生输出，随新日志及时更新；长行按终端宽度截断，正常输出在结束时清除。完成结果保留耗时，警告和错误保留原文。容器状态检查仍独立进行，不靠滚动输出判断安装完成；自动化测试保留完整原始日志。

Codex、Ollama、herdr、模型文件和 LLM 框架由用户自行安装。GPU 接入保持原有功能，不加入 GPU 编译工具。

## 容器网络开关（0.2.21 起）

硬件选项提供“GPU”和“网络”；没有可用 GPU 的宿主仍可设置网络。网络默认开启，修改前要求停止所选容器。

```bash
mas hardware demo                 # 查看 GPU 和网络
mas hardware demo gpu             # 单独查看 GPU
mas hardware demo network         # 查看网络状态
mas stop demo
mas hardware demo network off
mas start demo                    # 断网后仍可启动和进入
mas enter demo
mas mountfs demo                  # 通过宿主 LXD SFTP/SSHFS 访问，不依赖容器网卡
mas stop demo
mas hardware demo network on
```

关闭通过容器本地 `eth0` 的 `type=none` 配置屏蔽原网卡，IPv4/IPv6 外部连接随之移除，内部回环通信保留。开启恢复批准的网卡定义和 MAC。网络状态随重启及备份恢复保留；共享网桥、Profile、其他容器和容器防火墙不受修改。发现设备、记录、身份或并发配置冲突时拒绝操作。此开关控制 LXD 提供的网卡，容器内 root 仍可创建自身 namespace 内的接口；不是宿主网络 ACL。

网络关闭后，标准启动、进入终端、宿主侧文件挂载和安全挑战使用现有 LXD 管理通道。调整网络或 GPU 后，可从宿主重新运行 `test/security.sh`，挑战会核对当前开关预期；硬件修改本身不自动运行完整挑战。

## 固定隔离配置与旧容器迁移（0.2.11 起）

安装程序创建专用的 `mas` Project，以及其中的 `mas` 和 `default` Profile。配置固定，不提供通用设置入口。容器使用非特权、独立 UID/GID 映射和 LXD 标准 namespace/seccomp；不启用 nesting、raw 配置、BPF 委派或宿主身份例外。容器内 root 和 sandbox 的免密 sudo 保留。网络默认连接已有的 LXD managed bridge，可关闭该容器的网卡；不增加流量或登录规则。

GPU 是明确授权的资源例外。WSL NVIDIA 映射 `/dev/dxg`、只读运行库和经过官方探测选择的驱动目录；Project 仅允许对应目录前缀。GPU 开关仍位于容器硬件选项。程序核验完整的 expanded 配置和设备，拒绝额外宿主目录、任意字符设备、额外存储卷、管理 socket、Windows 挂载及被改写的 GPU 映射；类别级的 Project 允许值不代表任意硬件已获授权。具体配置见 [完整配置需求](https://github.com/gdrencn/my-ai-sandbox/blob/main/REQUIREMENTS.md#39-fixed-isolation-policy-and-effective-configuration-verification--v0211)。

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

当前实测 WSL 内核未启用 AppArmor；报告保存原生运行时属性，并明确记录 AppArmor 约束未获验证。本批没有修改宿主内核配置。原生 Ubuntu、其他 GPU/存储后端和上游漏洞修复不属于当前 WSL 验证结果。CPU、内存和进程限制、额外网络策略、完全关闭 devlxd、宿主 AppArmor 配置及磁盘配额仍待后续讨论。

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
