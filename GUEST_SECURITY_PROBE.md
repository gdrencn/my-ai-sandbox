# 容器安全挑战

v0.2.20 的自动化测试与独立宿主入口共用 mas/security_testing.py，以及原有 host_security_probe.py、guest_security_probe.py。宿主采集参照并传入容器，内部探针在容器运行，完整结果在宿主输出。security-host.sh 不提供，容器内不提供独立一键入口。

## 使用入口

安装并运行全部自动化测试：

    curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/test.sh | bash

固定顺序为安装、全部 26 个功能环节、新建独立临时容器并标准启动、一次完整安全挑战、统一清理和汇总。GPU-off 只核验设备定义、节点、挂载、驱动和受管运行库文件移除以及 CUDA 不可用。新挑战容器采用默认 GPU 设置；无支持硬件时使用明确 off 预期。

从宿主独立挑战用户指定容器：

    curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security.sh | bash

交互时使用与 mas 相同的容器选择组件；显示容器名和状态，默认选中第一个容器，↑/↓ 移动，Enter/→ 确定，Esc/← 取消。没有可测试容器时提示并正常结束，不请求输入名称，不改变状态。无终端且列表非空时必须提供 TARGET，例如：

    curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security.sh | bash -s -- test --report /home/gordon/security-test.json

独立入口只下载经发布清单校验的测试工具，不安装或覆盖 mas。宿主需要 Python 3.10+、lxc、LXD 访问权限和专用 mas Project 中的托管容器；不采用 lxc 当前 Project。容器需要 Python 3.10+，内部探针通过 LXD exec 以 root 运行，无需安装挑战软件。容器内误运行独立入口会明确报错。

最初停止的容器通过标准 start 启动，最后标准 stop；最初运行的保持运行，若挑战期间停止则通过标准 start 恢复。操作前后核验实例身份，同名替换对象不接受探测或恢复。失败和中断仍进行恢复，原始错误与恢复错误分别保留。启动中断先等待属于该目标及 Project 的已提交 LXD 操作完成，再恢复；原生操作超时或状态无法核验使测试失败。GPU 预期取自标准启动后的配置，兼容没有历史 GPU 记录的原生导入容器。

冻结包可在项目外调用：

    python3 /absolute/path/mas-test.pyz --product /absolute/path/mas.pyz --output /absolute/path/new-results
    python3 /absolute/path/mas-test.pyz --security test --report /absolute/path/security-test.json

## 完整流程

1. 记录初始状态和身份，按需通过标准 start 启动，并读取配置后的 GPU on/off 预期。
2. 宿主采集六种 namespace、boot ID、管理 socket device/inode，以及 binfmt_misc 挂载和注册摘要。
3. 创建唯一非敏感宿主标记，目录 0755、文件 0644；只传路径和 SHA-256，内容不进入容器。
4. 将包内两份原样探针和参照送入容器内本次专用的临时目录，运行一次完整挑战。固定、发现和参照中的 socket 去重检查。
5. 取回 JSON，验证必需检查、唯一 ID、GPU 预期、结构、汇总及退出码，完整输出方法、观察和 PASS/FAIL。原生命令失败也尝试取回报告，保留原错误。
6. 用容器内自有标记与符号链接验证摘要检测有效；这两个正向样本不是宿主越界，结果单独保存。
7. 清理容器临时目录，核对宿主标记、boot ID 和 binfmt_misc 注册规则不变，回收宿主临时数据。
8. 核验身份并通过标准生命周期恢复初始状态，保存结果。清理、报告、恢复及后置核验错误均不能整体通过。

自动化测试保存 boundary-1.json 和 boundary-1.log；主 report.json 的 guest_boundary 只有一份完整挑战，含源码哈希、GPU 预期、宿主参照、容器报告、合并报告和正向样本。独立模式默认在宿主当前目录生成唯一 security-时间-随机码.json 和同名 .log，--report 可指定新路径；已有报告及同名日志不覆盖。成功返回 0，边界或验证失败返回 1，执行/恢复/报告错误返回 2，取消或中断返回 130。

## 检查范围

| 检查 | 执行位置 | 实际动作与判定 |
| --- | --- | --- |
| UID/GID | 容器 | 读取映射，核对容器 root 的外层身份非零。 |
| seccomp | 容器 | 读取实际模式，要求过滤模式 2。 |
| 基础接口 | 容器 | 读取 null/zero 各 1 字节并观察 proc/sys。 |
| 设备清单 | 容器 | 枚举类型及 major:minor；基础/GPU 设备单列，未知来源或清单截断使验证失败，不贸然打开危险设备。 |
| GPU 只读映射 | 容器 | WSL 运行库与单个驱动目录必须只读，整个驱动父目录映射失败。 |
| 挂载来源 | 容器 | 检查 mountinfo；未能确认来源的宿主/Windows 映射特征使验证失败，不据特征本身宣称已经逃逸。 |
| 管理 socket | 容器（宿主参照） | 连接后立即关闭，不发送请求。缺失/权限拒绝或服务进程属于容器 namespace 为通过；宿主身份匹配失败，无法核验来源也使验证失败。 |
| devlxd | 容器 | 基本实例接口保持兼容；检查配置键清单、不开放卷管理、受限 GET 的权限拒绝。401/403 通过；404 不能证明禁用，权限验证失败。实例接口整体不存在时只验证入口未暴露。 |
| Windows/WSL 入口 | 容器 | 检查路径、环境变量、可见解释器注册；不执行 Windows 命令。入口特征异常使验证失败。 |
| 未授权设备 | 容器 | 私有目录 mknod 后只读 open/close；拒绝通过，可打开失败。其他错误不得冒充权限拒绝。 |
| 内核控制与读取入口 | 容器 | 有界 open/close，不读内存/日志、不写任何字节；拒绝通过，可打开使验证失败。缺失只通过“当前路径未暴露”断言，不声称测试了写入权限。 |
| 六种 namespace | 容器（宿主参照） | 比较 user/pid/mnt/net/ipc/uts；与宿主不同通过，共用失败。 |
| 可见进程与 root 路径 | 容器（宿主参照） | 核对各 PID 的 user/mnt/pid namespace，检查宿主进程暴露；无法完整核验或截断失败。 |
| 宿主唯一标记 | 容器（宿主参照） | 尝试直接路径及可见进程 root 下的别名，比较摘要；不可读/不可见通过，匹配失败，同名异物或不完整清单使验证失败。 |
| binfmt_misc | 容器（宿主参照） | 核对全部现有挂载来源，并在独立临时 user/mount namespace 内尝试建立入口；不登记解释器、不执行 Windows 程序。 |

AppArmor、capabilities、特殊内核文件系统可见性、socket 清单、基本 devlxd 可见性和网络范围属于环境记录，保存在 `observations`，不计入通过/失败数量。GPU 明确传入 on/off 预期并作为检查项判定。当前政策不要求启用宿主 AppArmor。网络扫描、连接宿主 TCP 服务及网络登录仍不测试。

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

此外，从 `/proc/net/unix` 发现名称包含 lxd、docker、containerd、podman、libvirt、virtqemud、snapd、systemd/private、bus 的文件路径，并检查 `/run/user/<UID>/docker.sock`、`podman/podman.sock`、`bus`。去重后有界执行；不连接抽象 socket。当次参照中的宿主 socket 路径并入同一去重清单，只检查一次。

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

以下退出码属于内部挑战及其 JSON 报告；完整 `mas-test` 在全部环节与清理成功时返回 0，有失败或中断时返回 1。

JSON schema 为 2。`checks` 中每项只有 PASS/FAIL（通过/失败），保留 check、method、message、evidence；纯记录置于 observations。失败项的 failure_kind 区分 boundary（断言违反）、verification（证据不完整或来源未核验）、execution（探测/执行错误），不会把无法确认的来源冒充已经确认越界。

- 0：列出的所有测试通过。
- 1：有测试断言或证据完整性验证失败。
- 2：存在执行错误，或输入、报告写入、报告取回、清理失败。
- 130：中断，保留已经取得的证据。

内部调用保留原始执行错误；取回报告和收尾核验后再传播。每项观察失败仍继续检查其他入口。终端转义控制字符，报告保留结构化原始证据；不覆盖已有报告。

文本读取上限为 1 MiB；设备、进程、动态 socket、binfmt_misc 清单上限为 512 项，设备递归深度为 3。截断不算通过。宿主标记最多读取 64 KiB，不保存内容。结果只针对列出的入口和当次观察，不能证明任意未知别名不可访问或不存在上游漏洞。

## 自动化测试与边界

两份 Python 源码只打包进 mas-test，不进入产品或安装程序。宿主协调器管理参照准备、完整容器调用、报告取回、宿主状态核验与本次临时目录清理；Suite 只提供目标、GPU 预期、输出回调并使用完整结果。内部探测保留有界子进程及 root/容器环境检查，不提供另一个公开下载入口。

不加载内核模块、不改 sysctl/cgroup、不读物理内存/磁盘、不执行设备 ioctl、不读取凭据、不修改宿主服务、不耗尽资源。唯一新增挂载是上述隔离子进程的临时 binfmt_misc；不挂载宿主路径。LXD Project/Profile 的完整配置审计仍由 mas 和配置自动化测试负责。历史独立入口及 REVIEW/SKIP/INFO/ERROR 报告仅为历史证据。

依据：[LXD 安全模型](https://canonical.com/lxd/docs/latest/explanation/security/)、[Linux binfmt_misc 文档](https://docs.kernel.org/6.12/admin-guide/binfmt-misc.html)、[Linux 6.12 按 user namespace 分离的 binfmt_misc 实现](https://github.com/torvalds/linux/blob/v6.12/fs/binfmt_misc.c)、[Linux 设备编号](https://docs.kernel.org/admin-guide/devices.html)、[Unix socket peer credentials](https://man7.org/linux/man-pages/man7/unix.7.html)。
