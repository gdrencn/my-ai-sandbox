# 自动化容器安全挑战

v0.2.18 将容器内检查和需要宿主参照的检查合为一个完整模块，由宿主自动化测试调用。公开入口统一为 `test/test.sh`，不再提供单独的容器或宿主挑战下载入口。本版本已发布，实际公开入口已完成验证。

## 使用入口

在管理 LXD 的 Linux/WSL 宿主运行：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/test.sh | bash
```

这个固定命令安装当前已发布测试版并运行配套自动化测试；v0.2.18 已将完整挑战纳入同一流程。无需手动进入容器，不再输入现有容器名。测试工具创建本次拥有的专用 Project 和临时容器，通过标准 mas 功能管理启停与收尾，不使用用户已有容器作为挑战对象。

源代码和冻结包验证可从项目运行 `python3 scripts/build.py`，然后在项目外运行配套包：

```bash
python3 /absolute/path/to/mas-test.pyz --product /absolute/path/to/mas.pyz --output /absolute/path/to/new-results
```

宿主需要 Python 3.10+、lxc、正常的 LXD 访问权限和同版本产品/测试工具。容器通过 LXD exec 以 root 运行内部探测，需要 Python 3.10+，无需安装 mas、lxc 或挑战专用软件。环境标识检查防止内部程序误在普通宿主执行，不是身份认证。依赖安装测试仍是完整自动化测试的另一个环节。

## 完整流程

1. 宿主读取当次 user/pid/mnt/net/ipc/uts namespace、boot ID、管理 socket 的 device/inode 和 binfmt_misc 挂载及注册摘要。
2. 创建唯一非敏感宿主标记，目录 0755、文件 0644。只传递路径和 SHA-256；宿主标记内容不进入容器。标记不能只靠宿主目录读取权限保护。
3. 将当前测试包中的两份原样 Python 源码和参照送入此次创建的容器临时目录，并传入明确的 GPU on/off 预期。
4. 调用一次完整容器挑战。共享设备、接口、socket、devlxd、Windows/WSL 检查与 namespace、进程来源、标记、binfmt_misc 检查在同一流程完成。固定、发现及参照中的 socket 路径去重后逐项探测，使用同一份宿主参照。
5. 取回完整 JSON，把每项方法、观察和通过/失败结果输出在宿主。必需检查缺项或重复、GPU 预期不符、结构无效或汇总/退出码不一致均使验证失败。原生命令失败也先尝试取回报告，再清理并保留原错误。
6. 清理本次容器临时目录，核对宿主标记、boot ID 和 binfmt_misc 注册规则保持不变。清理或后置核验失败不能报告整体通过。宿主临时标记和参照目录随后回收。

GPU 开启的完整挑战位于“安全挑战”环节；GPU 关闭后的完整挑战位于执行开关的“资源接入”环节。无 GPU 的机器运行明确 off 预期的基础完整挑战，不声称验证了硬件计算。自动化测试另用容器内自有标记文件和符号链接确认摘要匹配检测有效；这两个正向样本不是宿主越界，原始结果保存在报告中。

输出目录保存 `boundary-N.log` 和 `boundary-N.json`，主 `report.json` 的 `guest_boundary` 保存源码哈希、GPU 预期、当次参照、容器报告、完整合并报告和正向样本证据。日志显示全部检查详情，不添加颜色控制符；交互终端上的勾或叉使用绿色或红色。所有报告及详细日志留在宿主输出目录。

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
