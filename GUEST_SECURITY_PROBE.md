# 容器与宿主侧安全挑战

两个入口分别执行能够独立判定的测试，复用同一套探测基础函数。容器入口不要求宿主参照；宿主侧入口自动准备参照并验证现有运行容器。它们不安装软件、不改变 LXD 配置、不启动或停止容器。

## 容器内固定命令

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security.sh | bash
```

命令不变。需要 curl、Python 3.10+，普通用户还需要系统 sudo；以容器 root 执行挑战。入口下载到私有临时目录并在完成或中断后清理，报告保留在当前目录，权限 0600。已有报告和符号链接不覆盖。主入口及子进程拒绝在普通宿主上运行；环境标识检查防止误执行，不是身份认证。

可选参数：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security.sh | bash -s -- --report guest-report.json --gpu on
```

`--gpu on/off` 核对显式设备预期；不指定时只记录设备。`--timeout` 为每个主动探测设置 1–10 秒的期限，默认 3 秒。这个入口不接受 `--host-reference`，不列出缺少宿主参照的 namespace、进程来源和宿主标记测试。

## 宿主侧固定命令

在管理 LXD 的 Linux/WSL 宿主运行：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security-host.sh | bash
```

默认查询 `mas` Project 的运行中容器，显示名称，然后从 `/dev/tty` 输入要挑战的容器名。这是名称输入，不是选择菜单。需要宿主 Python 3.10+、curl、lxc 及正常的 LXD 访问权限，不使用宿主 sudo。目标必须已经运行；没有运行容器或 LXD 查询失败均明确失败，不代为启动。

指定目标，适用于非交互执行：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security-host.sh | bash -s -- demo
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security-host.sh | bash -s -- demo --project mas --report host-report.json
```

宿主每次采集六种 namespace、boot ID、管理 socket 的 device/inode 和 binfmt_misc 挂载及注册摘要。创建一个唯一的非敏感标记，标记目录 0755、文件 0644；其保护不能只依靠宿主目录的读取权限。只传递文件路径和 SHA-256，标记内容始终留在宿主。通过 LXD 的 file push 和 exec 运行挑战，取回 JSON，再检查宿主标记、启动身份和 binfmt_misc 规则未改变。挑战失败也尝试取回报告；清理只处理此次创建的临时目录。原生挑战失败与报告/清理失败均保留。

目标容器需要 Python 3.10+，无需安装 mas、lxc 或测试专用包；LXD exec 直接以容器 root 运行。报告默认保存在宿主当前目录。容器临时脚本、参照、报告和宿主临时标记在结束后清理。

## 检查范围

| 检查 | 入口 | 实际动作与判定 |
| --- | --- | --- |
| UID/GID | 容器 | 读取映射，核对容器 root 的外层身份非零。 |
| seccomp | 容器 | 读取实际模式，要求过滤模式 2。 |
| 基础接口 | 容器 | 读取 null/zero 各 1 字节并观察 proc/sys。 |
| 设备清单 | 容器 | 枚举类型及 major:minor；基础/GPU 设备单列，未知来源或清单截断使验证失败，不贸然打开危险设备。 |
| GPU 只读映射 | 容器 | WSL 运行库与单个驱动目录必须只读，整个驱动父目录映射失败。 |
| 挂载来源 | 容器 | 检查 mountinfo；未能确认来源的宿主/Windows 映射特征使验证失败，不据特征本身宣称已经逃逸。 |
| 管理 socket | 两者 | 连接后立即关闭，不发送请求。缺失/权限拒绝或服务进程属于容器 namespace 为通过；宿主身份匹配失败，无法核验来源也使验证失败。 |
| devlxd | 容器 | 基本实例接口保持兼容；检查配置键清单、不开放卷管理、受限 GET 的权限拒绝。401/403 通过；404 不能证明禁用，权限验证失败。实例接口整体不存在时只验证入口未暴露。 |
| Windows/WSL 入口 | 容器 | 检查路径、环境变量、可见解释器注册；不执行 Windows 命令。入口特征异常使验证失败。 |
| 未授权设备 | 容器 | 私有目录 mknod 后只读 open/close；拒绝通过，可打开失败。其他错误不得冒充权限拒绝。 |
| 内核控制与读取入口 | 容器 | 有界 open/close，不读内存/日志、不写任何字节；拒绝通过，可打开使验证失败。缺失只通过“当前路径未暴露”断言，不声称测试了写入权限。 |
| 六种 namespace | 宿主侧 | 比较 user/pid/mnt/net/ipc/uts；与宿主不同通过，共用失败。 |
| 可见进程与 root 路径 | 宿主侧 | 核对各 PID 的 user/mnt/pid namespace，检查宿主进程暴露；无法完整核验或截断失败。 |
| 宿主唯一标记 | 宿主侧 | 尝试直接路径及可见进程 root 下的别名，比较摘要；不可读/不可见通过，匹配失败，同名异物或不完整清单使验证失败。 |
| binfmt_misc | 宿主侧 | 核对全部现有挂载来源，并在独立临时 user/mount namespace 内尝试建立入口；不登记解释器、不执行 Windows 程序。 |

AppArmor、capabilities、特殊内核文件系统可见性、未指定开关的 GPU 清单和网络范围属于环境记录，保存在 `observations`，不计入通过/失败数量。当前政策不要求启用宿主 AppArmor。网络扫描、连接宿主 TCP 服务及网络登录仍不测试。

## 精确路径与设备清单

主动设备探测：

- `host-memory`：char `1:1`
- `kernel-memory`：char `1:2`
- `io-ports`：char `1:4`
- `kernel-log`：char `1:11`
- `kvm`：char `10:232`
- `host-disk`：block `8:0`
- `host-nvme`：block `259:0`
- `host-loop`：block `7:0`

写模式 open/close 的 16 个内核控制入口：

- `/proc/sysrq-trigger`
- `/proc/sys/kernel/modprobe`
- `/proc/sys/kernel/kexec_load_disabled`
- `/proc/sys/vm/drop_caches`
- `/proc/sys/kernel/core_pattern`
- `/proc/sys/kernel/hotplug`
- `/proc/sys/kernel/modules_disabled`
- `/proc/sys/kernel/sysrq`
- `/proc/sys/kernel/panic`
- `/proc/sys/kernel/panic_on_oops`
- `/proc/sys/kernel/unprivileged_bpf_disabled`
- `/proc/sys/kernel/perf_event_paranoid`
- `/proc/sys/kernel/yama/ptrace_scope`
- `/sys/power/state`
- `/sys/power/disk`
- `/sys/kernel/uevent_helper`

只读 open/close 的内核入口：

- `/proc/kcore`
- `/proc/kmsg`

14 个固定管理 socket：

- `/var/snap/lxd/common/lxd/unix.socket`
- `/var/lib/lxd/unix.socket`
- `/run/lxd/unix.socket`
- `/run/lxd.socket`
- `/run/docker.sock`
- `/var/run/docker.sock`
- `/run/containerd/containerd.sock`
- `/run/podman/podman.sock`
- `/run/libvirt/libvirt-sock`
- `/run/libvirt/virtqemud-sock`
- `/run/dbus/system_bus_socket`
- `/run/systemd/private`
- `/run/snapd.socket`
- `/run/snapd-snap.socket`

此外，从 `/proc/net/unix` 发现名称包含 lxd、docker、containerd、podman、libvirt、virtqemud、snapd、systemd/private、bus 的文件路径，并检查 `/run/user/<UID>/docker.sock`、`podman/podman.sock`、`bus`。去重后有界执行；不连接抽象 socket。宿主侧入口另外检查当次参照中的宿主 socket 路径。

devlxd 的 5 个只读 GET：

- `/1.0`：核对不开放卷管理能力；若广告了 storage 驱动则失败。
- `/1.0/config`：核对只列出 user/cloud-init 配置键名，不读取对应值。
- `/1.0/config/security.privileged`：核对非 user 配置不可读取。
- `/1.0/storage-pools/mas-probe-unowned/volumes/custom`：核对禁用 volume 管理后的拒绝。
- `/1.0/images/<64 个零>/export`：核对未启用 image export 时的拒绝。

最后两项的 404 只能说明指定对象不可用，不能证明功能被策略禁用；因此该权限验证失败，而不声称已经确认越界。在当前 LXD 6.9 中，这些策略拒绝发生在目标对象查找之前，实际返回 403。

Windows/WSL 固定路径：

- `/mnt/c/Windows`
- `/mnt/c/Users`
- `/mnt/d/Windows`
- `/mnt/d/Users`
- `/mnt/wsl`
- `/mnt/wslg`
- `/run/WSL`
- `/init`
- `/proc/sys/fs/binfmt_misc/WSLInterop`

同时记录 WSL_INTEROP 和 binfmt_misc 注册的解释器；其他 Windows 文件系统别名通过 mountinfo 与唯一标记补充核验。

特殊内核路径，仅作可见性/挂载记录：

- `/sys/kernel/debug`
- `/sys/kernel/security`
- `/sys/fs/pstore`
- `/sys/firmware/efi/efivars`
- `/sys/fs/bpf`

## binfmt_misc 专项

从 mountinfo 找到所有 binfmt_misc 挂载点。宿主实例的 device/inode 相同意味着暴露了宿主实例，测试失败；不同身份不能单独证明是容器实例。对现有入口只尝试写模式 open/close，不写规则：拒绝或接口未提供通过；可以打开且来源未核验时验证失败。

独立子进程首先建立新 user/mount namespace，并将传播方式设为 private，再在此次拥有的容器临时目录尝试挂载。建立入口遭 EPERM/EACCES/EROFS 拒绝通过；内核不支持时只通过能力不可用断言。挂载成功必须属于新 user namespace，并与宿主实例身份不同；这是允许的容器自身能力。成功后 detach，子进程退出时其 mount namespace 一并结束。detach 失败不是通过，也不递归删除仍挂载的内核文件系统；宿主执行器随后清理底层临时目录。

宿主只读采集注册项名称、解释器路径、flags 和内容摘要，并核对挑战前后未改变。记录不能替代实际执行权限测试；本程序不运行宿主解释器或 Windows 二进制。

## 结果与退出码

JSON schema 为 2。`checks` 中每项只有 PASS/FAIL（通过/失败），保留 check、method、message、evidence；纯记录置于 observations。失败项的 failure_kind 区分 boundary（断言违反）、verification（证据不完整或来源未核验）、execution（探测/执行错误），不会把无法确认的来源冒充已经确认越界。

- 0：列出的所有测试通过。
- 1：有测试断言或证据完整性验证失败。
- 2：存在执行错误，或输入、报告写入、报告取回、清理失败。
- 130：中断，保留已经取得的证据。

下载和系统 sudo 失败保留原退出码。每项观察失败仍继续检查其他入口。终端转义控制字符，报告保留结构化原始证据；不覆盖已有报告。

文本读取上限为 1 MiB；设备、进程、动态 socket、binfmt_misc 清单上限为 512 项，设备递归深度为 3。截断不算通过。宿主标记最多读取 64 KiB，不保存内容。结果只针对列出的入口和当次观察，不能证明任意未知别名不可访问或不存在上游漏洞。

## 自动化测试与边界

两份 Python 源码和两个下载入口仅打包进 mas-test，不进入产品或安装程序。自动化测试在 GPU 开、关状态分别运行容器挑战和同一宿主执行器，保存两份源码哈希、宿主参照、各自报告和合并的覆盖证据。容器内的正向标记及符号链接样本验证匹配检测，明确标为测试文件，不当作真实宿主越界。

不加载内核模块、不改 sysctl/cgroup、不读物理内存/磁盘、不执行设备 ioctl、不读取凭据、不修改宿主服务、不耗尽资源。唯一新增挂载是上述隔离子进程的临时 binfmt_misc；不挂载宿主路径。LXD Project/Profile 的完整配置审计仍由 mas 和宿主自动化测试负责。历史版本的 REVIEW/SKIP/INFO/ERROR 报告保留为历史证据，不适用于新版入口。

依据：[LXD 安全模型](https://canonical.com/lxd/docs/latest/explanation/security/)、[Linux binfmt_misc 文档](https://docs.kernel.org/6.12/admin-guide/binfmt-misc.html)、[Linux 6.12 按 user namespace 分离的 binfmt_misc 实现](https://github.com/torvalds/linux/blob/v6.12/fs/binfmt_misc.c)、[Linux 设备编号](https://docs.kernel.org/admin-guide/devices.html)、[Unix socket peer credentials](https://man7.org/linux/man-pages/man7/unix.7.html)。
