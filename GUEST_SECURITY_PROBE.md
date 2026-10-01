# 容器内安全边界测试脚本

此脚本从容器 root 的权限视角，检查未经批准的宿主资源访问路径。它可以独立下载运行；0.2.12 的自动化测试也打包并执行同一份源码，不维护另一套重复探测实现。

## 下载与运行

在容器终端内运行：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security.sh | bash
```

需要 curl、Python 3.10+；普通用户还需要系统 sudo。入口下载脚本到私有临时目录，运行后清理下载文件，不安装 mas、软件包或 Python 依赖。容器 root 直接执行；其他用户通过系统 sudo 执行。Python 脚本不处理提权，主入口和子探测入口均检查 root 身份与 LXC 运行标识。该检查防止误运行，不是不可伪造的身份认证。

结果逐项显示检查标识、方法、状态和观察证据。默认在运行命令时的当前目录生成唯一的、权限 0600 的 JSON 报告；root 所有的报告可通过 sudo cat 查看。已有文件和符号链接均不覆盖。可以指定参数：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security.sh | bash -s -- --report guest-security-report.json --gpu on
```

`--gpu on` / `off` 核对设备开关预期；默认 `unknown` 仅记录。设备、内核入口、管理 socket、devlxd 和宿主标记的每个独立子探测默认最多 3 秒，`--timeout` 可设为 1–10 秒。超时属于 ERROR，不能当作访问被拒绝。普通文本观察限制为 1,048,576 字符，设备、进程、动态 socket 和 binfmt_misc 清单限制为 512 项。设备目录递归深度最多 3；数量或深度导致未完整检查时如实记录 SKIP。

离线执行可下载同一源码：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/guest_security_probe.py -o guest_security_probe.py
sudo python3 guest_security_probe.py
```

## 检查与尝试

| 检查 | 实际动作 | 结果含义 |
| --- | --- | --- |
| UID/GID | 读取 uid_map、gid_map | 容器 root 必须映射到外层非零身份；不凭此推断全部 LXD identity 配置。 |
| namespace | 比较 user、pid、mnt、net、ipc、uts 标识 | 有可信宿主参照时不同为 PASS、相同为 FAIL；没有参照为 SKIP。 |
| 可见进程 | 读取各 PID 的 root 与 user/mnt/pid namespace | 与宿主参照相同为 FAIL；无参照、无法完整核验或达到上限为 SKIP；不读取进程内存、环境或凭据。 |
| seccomp | 读取当前进程 Seccomp | 模式 2 为 PASS；不枚举或反编译过滤规则。 |
| AppArmor / capabilities | 记录实际属性和能力位 | INFO；不把容器 namespace 内能力位视为宿主权限，不把 AppArmor 未启用本身称为越界。 |
| 基础接口 | 读取 null、zero 各 1 字节，观察 proc/sys | 正常容器接口不属于未授权宿主访问。 |
| 设备清单 | 按类型和 major:minor 枚举 /dev | 基础设备与 GPU 节点单独记录；未知节点为 REVIEW。watchdog、USB、PCI 节点不主动打开。被权限保护的目录记录拒绝证据。 |
| GPU | 检查实际字符设备及 mountinfo | 按显式开关预期核对；WSL 库与单个驱动目录必须只读；整个驱动父目录映射为 FAIL。容器自行创建的嵌套挂载不冒充宿主驱动映射。 |
| 文件系统来源 | 检查 mountinfo 的类型、挂载根、挂载点 | 典型 Windows 或宿主 home 特征为 REVIEW，需要宿主配置/唯一标记确认来源。 |
| 特殊内核文件系统 | 记录下列特殊路径的挂载与可见性 | INFO；目录可见不证明可以读写宿主，也不执行写入。 |
| 管理 socket | 固定路径与动态路径连接后立即关闭 | 不发送管理请求。可信宿主 device/inode 匹配为 FAIL；SO_PEERCRED 的 PID、mount、user namespace 全部属于当前容器时为 INFO；来源无法确认为 REVIEW；缺失或权限拒绝为 PASS。 |
| devlxd | 对实例接口执行下列只读 GET | 基本接口和 user/cloud-init 键清单为 INFO，不读取键值；受限制入口返回 401/403 为 PASS，200 为 FAIL，404 为 SKIP，其他异常为 ERROR。 |
| Windows / WSL | 固定路径、环境变量、binfmt_misc 解释器注册 | 发现入口特征为 REVIEW；不执行 Windows 二进制文件或解释器。 |
| 宿主唯一标记 | 有界读取直接路径和可见进程 root 下的别名 | 与宿主非敏感唯一标记 SHA-256 一致为 FAIL；不同内容或非普通文件为 REVIEW；不可见/不可读为 PASS；达到清单上限为 SKIP。会检查符号链接路径，不保存内容。 |
| 未授权设备 | 私有临时目录 mknod，再只读 open/close | 创建或打开遭权限拒绝为 PASS；内核无对应对象/能力为 SKIP；成功打开为 FAIL。不会读取设备、写入或调用 ioctl。 |
| 内核控制入口 | 写模式 open/close | 不使用 O_CREAT/O_TRUNC、不写任何字节。权限/只读拒绝为 PASS；打开成功为 REVIEW，真实写入仍可能受额外检查。 |
| 内核读取入口 | 只读 open/close | 不读取内存或日志内容。拒绝为 PASS、能力缺失为 SKIP、可打开为 REVIEW。 |
| 网络 | 说明独立讨论的范围 | 不扫描网络、不连接宿主 TCP 服务、不尝试登录。 |

一项观察失败会记录 ERROR 并继续检查其他入口，避免因为前面的读取失败而漏掉后续设备或控制入口。

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

写模式 open/close 的 17 个内核控制入口：

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
- `/proc/sys/fs/binfmt_misc/register`
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

此外，从 `/proc/net/unix` 发现名称包含 lxd、docker、containerd、podman、libvirt、virtqemud、snapd、systemd/private、bus 的文件路径，并检查 `/run/user/<UID>/docker.sock`、`podman/podman.sock`、`bus`。去重后有界执行；不连接抽象 socket。宿主参照中的额外 socket 路径也会检查。

devlxd 的 5 个只读 GET：

- `/1.0`：记录接口可用性；若广告了受禁止的 storage 驱动则 FAIL。
- `/1.0/config`：核对只列出 user/cloud-init 配置键名，不读取对应值。
- `/1.0/config/security.privileged`：核对非 user 配置不可读取。
- `/1.0/storage-pools/mas-probe-unowned/volumes/custom`：核对禁用 volume 管理后的拒绝。
- `/1.0/images/<64 个零>/export`：核对未启用 image export 时的拒绝。

最后两项的 404 只能说明指定对象不可用，不能证明功能被策略禁用；因此标为 SKIP。在当前 LXD 6.9 中，这些策略拒绝发生在目标对象查找之前，实际返回 403。

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

## 可选宿主参照

独立运行无法自行认证宿主 namespace、文件或 socket 来源。可以复制可信宿主步骤生成的非敏感参照 JSON；六个 namespace 值应来自实际宿主 `/proc/self/ns/<名称>`，下例数值仅表示格式：

```json
{
  "schema": 1,
  "namespaces": {
    "user": "user:[4026531837]",
    "pid": "pid:[4026531836]",
    "mnt": "mnt:[4026531840]",
    "net": "net:[4026531992]",
    "ipc": "ipc:[4026531839]",
    "uts": "uts:[4026531838]"
  },
  "canaries": [],
  "sockets": []
}
```

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security.sh | bash -s -- --host-reference host-reference.json
```

`canaries` 可选，最多 16 项，每项为 `{"path":"/绝对路径/唯一标记","sha256":"64 位小写 SHA-256"}`。标记须为明确允许创建的非敏感、唯一、最多 64 KiB 的普通文件。不要使用密码、私钥或实际凭据，也不要把标记目录映射给容器。只复制参照 JSON；标记本身留在宿主。

`sockets` 可选，最多 64 项，每项为 `{"path":"/run/宿主管理.sock","device":123,"inode":456}`；数值应来自宿主对实际 socket 的 stat，不能照抄示例。容器内连接到相同文件对象，包括路径别名，才形成明确来源证据。没有此参照时，可见服务会核对 peer namespace，但来源不明仍保持 REVIEW。

可信宿主参照不能由容器自己生成来代替。当前 mas-test 在隔离的临时测试容器中生成真实宿主 namespace、唯一标记和可用宿主 socket 身份；独立下载运行并不自动得到这些参照。

## 状态、退出码和覆盖限制

- PASS：该具体检查符合预期，具有观察或拒绝证据。
- FAIL：明确预期被违反，如宿主 root 映射、相同宿主 namespace、匹配的宿主标记/socket、可打开的禁止设备。
- REVIEW：来源或进一步权限仍需核对，既不算通过，也不直接称为逃逸。
- SKIP：缺少参照、对象/能力不存在、清单达到上限或无法完整验证。
- INFO：背景、容器内服务或明确允许的接口状态。
- ERROR：探测异常、超时或执行条件问题，不能当作权限拒绝。

退出码 0 表示没有 FAIL/ERROR，仍可能有 REVIEW/SKIP；1 表示存在 FAIL；2 表示 ERROR、输入/执行条件或报告写入问题。中断保留已完成检查和错误记录，返回 130。下载/sudo 失败保留原退出码。

JSON 保留每项 check、method、status、message、evidence，以及计数、原始错误、覆盖限制。终端转义控制字符，报告保留原始结构化证据。文件名、路径名或 socket 名称本身不能认证宿主来源。常见路径和有界清单不能证明任意未知别名不可访问。

脚本不执行上游漏洞利用、内核模块加载/卸载、remount、sysctl/cgroup 修改、设备读写/ioctl、宿主服务修改、凭据读取或资源耗尽。允许写入的只有本次容器临时探测目录/节点和报告文件。网络策略、资源配额、未知上游漏洞、宿主 LXD Project/Profile 的完整配置均不由独立脚本证明。

## 自动化测试复用与依据

独立探测源码与一键入口仅打包进入 mas-test，不进入产品或安装包。`tests/test_guest_security_probe.py` 检查拒绝/允许/来源不明/错误/超时分支、每项失败隔离、符号链接、socket 来源、清单截断、报告不覆盖、控制字符和下载入口。旧 `scripts/test_guest_security_probe.py` 仅转发到同一组测试。

mas-test 的运行时隔离环节执行完整探测，GPU 环节在关闭后再执行同一探测，复用已有硬件状态，未新增重复 GPU discovery。主报告保存源码 SHA-256、可信参照、每份 guest JSON 与精确 GPU 预期。容器内的正向样本与符号链接样本确认检测器能够发现匹配标记；它们明确标为测试用容器文件，不冒充真实宿主越界。失败时也尝试取回 JSON，再传播原错误；清理仅限本次拥有的文件和测试资源。

依据：[LXD 安全模型](https://canonical.com/lxd/docs/latest/explanation/security/)、[容器运行环境](https://canonical.com/lxd/docs/latest/container-environment/)、[实例 devlxd 源码](https://github.com/canonical/lxd/blob/main/lxd/devlxd.go)、[Linux 设备编号](https://docs.kernel.org/admin-guide/devices.html)、[Unix socket peer credentials](https://man7.org/linux/man-pages/man7/unix.7.html)。

0.2.11 的初始脚本及公开下载验证属于历史证据，保留在 `validation/GUEST_SECURITY_PROBE_REPORT.json`；0.2.12 的本轮完整结果记录在 IMPLEMENTED.md 和版本化主测试报告中。

本轮本地 frozen 包通过 331 项单元测试、26 个实机环节（632.9 秒）。有可信参照时，GPU 开启结果为 59 PASS、16 INFO、1 SKIP；关闭为 57 PASS、16 INFO、1 SKIP，均无 FAIL/REVIEW/ERROR。唯一 SKIP 为不存在的 binfmt_misc/register；AppArmor 仍为未启用，未作其他宣称。详见 validation/V0_2_12_LOCAL_REPORT.json。
