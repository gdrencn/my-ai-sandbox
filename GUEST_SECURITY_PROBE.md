# 容器内安全边界测试脚本

此脚本用于从容器 root 的权限视角，尝试访问当前 mas 隔离策略不应提供的宿主资源。它是独立诊断工具，不属于当前 mas-test 的 26 个自动化测试环节。

## 下载与运行

在新机器的容器终端内运行这一条命令即可，需要 curl、Python 3.10+；以普通用户执行时还需要系统 sudo：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security.sh | bash
```

入口下载完整的 `test/guest_security_probe.py` 到本次私有临时目录，再运行该文件；结束后清理下载文件。它不安装 mas、不运行 mas-test，也不安装软件包。容器 root 直接运行；普通用户通过系统 `sudo` 执行，认证按系统原有方式处理。mas 的 sandbox 用户已有免密 sudo。Python 脚本本身不处理提权，且不依赖 mas 或第三方 Python 包。

必须使用容器 root 才能检查最强的容器内权限；以 sandbox 普通身份测试不足以覆盖 root 工作负载。脚本检查 LXC 运行标识，拒绝在普通宿主执行探测；这个检查用于防止误运行，不是不可伪造的身份认证。

终端逐项显示检查标识、尝试的方法、实际结果和观察证据。设备/内核控制入口遇到权限拒绝时，会显示是 `mknod` 还是 `open` 阶段被拒绝，以及原始 errno；最后显示各状态计数和报告位置。

默认在当前目录创建名称唯一、权限为 `0600` 的 JSON 报告。也可以指定文件名；已有文件或符号链接均不覆盖：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security.sh | bash -s -- --report guest-security-report.json --gpu on
```

报告保存在运行命令时的当前目录，不在下载临时目录中；容器 root 所有的 `0600` 报告可以用 `sudo cat guest-security-report.json` 查看。终端结果无需再次打开报告即可阅读。想保留脚本文件供离线重复执行，可以单独下载同一份实现：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/guest_security_probe.py -o guest_security_probe.py
sudo python3 guest_security_probe.py
```

`--gpu on` 表示预期 GPU 开启；`off` 表示预期关闭；默认 `unknown` 仅记录设备，不判定开关是否正确。应根据当前容器的配置选择，不能在没有 GPU 的宿主上默认要求 `on`。每项设备/内核控制入口的子进程默认超时 3 秒，`--timeout` 可以设置为 1–10 秒。

## 检查与尝试

| 检查 | 实际动作 | 结果含义 |
| --- | --- | --- |
| UID/GID | 读取 `/proc/self/uid_map`、`gid_map` | 映射到宿主 UID/GID 0 判为 FAIL；非零 root 映射通过。独立的用户 ID 范围仍需宿主配置核验。 |
| namespace | 记录 user、pid、mnt、net、ipc、uts 标识 | 有宿主参照才比较；与宿主相同判为 FAIL，无参照则 SKIP。 |
| seccomp | 读取 `/proc/self/status` | 必须实际处于过滤模式 2；不单凭配置项推断。不会枚举或反编译过滤规则。 |
| AppArmor / capabilities | 读取实际运行时属性与能力位 | INFO/REVIEW；不将当前 namespace 的能力位视为宿主权限，不将未启用 AppArmor 算成已生效。 |
| 基础接口 | 读取 `/dev/null`、`/dev/zero`，观察 `/proc`、`/sys` | 正常容器接口可以使用，不能将它们的存在视为越界。 |
| GPU 映射 | 读取 mountinfo 与 `/dev` 设备名称 | WSL GPU 库/驱动子目录映射必须只读；整个驱动父目录挂载判为 FAIL；按显式 GPU 开关预期检查设备存在。这里不重复已有 CUDA 计算测试。 |
| 文件系统来源 | 读取 mountinfo | 典型 Windows 文件系统或宿主 home 来源判为 REVIEW，等待确认来源；不盲目认定每个同名目录属于宿主。 |
| 管理 socket | 检查路径；若存在，尝试 Unix socket 连接并立即关闭 | 不发送管理请求。能连接判为 REVIEW，必须区分宿主服务和容器自己安装的服务；缺失/权限拒绝有明确记录。 |
| devlxd | 检查 `/dev/lxd/sock` | 仅记录，这是实例接口，不等于宿主 LXD 管理 socket。 |
| Windows / WSL 入口 | 检查 Windows 路径、WSLInterop、`/init` 和 WSL_INTEROP 变量 | 路径特征存在判为 REVIEW；不执行 Windows 命令。环境变量只记录，不单独认定存在通道。 |
| 宿主唯一标记 | 使用可选参照，尝试直接路径与 `/proc/1/root`、`/proc/self/root` 路径读取 | SHA-256 与宿主非敏感唯一标记一致才判为明确 FAIL；可见但内容不符判为 REVIEW；不保存文件内容。 |
| 未授权设备 | 在本次私有临时目录内尝试创建并只读打开设备节点 | 对 host memory（char 1:1）、kernel log（char 1:11）、KVM（char 10:232）、常规磁盘（block 8:0）逐项检查。创建/打开遭权限拒绝为 PASS；对象不存在或内核不支持为 SKIP；能够打开为 FAIL。 |
| 内核控制入口 | 尝试以写方式打开，随后立即关闭 | 不写任何字节。只读/权限拒绝为 PASS；成功打开为 REVIEW，因为真正写入还可能有额外权限检查。 |
| 网络 | 输出独立的范围说明 | 不扫描网络、不连接宿主 TCP 服务、不尝试网络登录；这些仍属于另议的策略。 |

管理 socket 路径清单：

- `/var/snap/lxd/common/lxd/unix.socket`
- `/var/lib/lxd/unix.socket`
- `/run/lxd/unix.socket`
- `/run/docker.sock`
- `/run/containerd/containerd.sock`
- `/run/podman/podman.sock`
- `/run/libvirt/libvirt-sock`

内核控制入口清单：

- `/proc/sysrq-trigger`
- `/proc/sys/kernel/modprobe`
- `/proc/sys/kernel/kexec_load_disabled`
- `/proc/sys/vm/drop_caches`
- `/sys/power/state`

Windows/WSL 路径清单：`/mnt/c/Windows`、`/mnt/c/Users`、`/proc/sys/fs/binfmt_misc/WSLInterop`、`/init`。其他文件系统映射通过 mountinfo 检查；该固定清单不声称发现所有可能的 Windows 入口。

## 可选宿主参照

容器自己只能观察自己的 namespace。想要直接证实与宿主不同，可以提供从宿主生成的非敏感 JSON。六个 namespace 值应分别来自宿主 `/proc/self/ns/<名称>` 的符号链接内容，下面的数值仅为格式示例，不能直接用于真实测试：

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
  "canaries": []
}
```

将这个普通 JSON 文件复制到容器后运行：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security.sh | bash -s -- --host-reference host-reference.json
```

`canaries` 可选。每项为 `{"path": "/绝对路径/唯一非敏感标记", "sha256": "64位小写SHA256"}`。最多 16 项，文件应不超过 64 KiB，路径不得包含上级跳转或控制字符。标记必须由用户明确允许在宿主创建、记录散列并保持存在；不要拿真实密码、SSH 私钥或其他凭据充当标记，也不要把标记所在的宿主目录挂载给容器。只复制参照 JSON，测试目标仍是标记不应被容器读到。

宿主参照是否可信，取决于提供它的宿主侧步骤；仅凭容器内运行脚本不能认证参照，也不能核验宿主 LXD Project/Profile 的完整配置。

## 状态与退出码

- PASS：该具体检查符合预期，有对应观察或拒绝证据。
- FAIL：违反明确预期，例如宿主 root 映射、相同宿主 namespace、匹配的宿主标记或可打开的未授权设备。
- REVIEW：需要确认来源或继续验证，不能算通过，也不能直接称为逃逸。
- SKIP：没有参照、对象/能力不存在，尚未验证对应边界。
- INFO：记录背景或已明确不在本次判断范围的状态。
- ERROR：探测异常、超时或执行条件不满足，不能当作权限拒绝。

退出码 `0` 表示未发现明确 FAIL/ERROR，仍可能有 REVIEW/SKIP；`1` 表示出现 FAIL；`2` 表示存在 ERROR、输入/执行条件问题或报告写入失败。下载/系统 sudo 失败时，一键入口保留该命令的非零退出码；用户中断通常为 `130`，TERM 结束为 `143`。JSON 保留每项 `check`、`method`、`status`、`message`、`evidence`，以及计数、原始错误、实际 AppArmor 属性和结果限制。拒绝已有报告文件，不用覆盖或重试掩盖失败。

## 验证范围与依据

脚本不加载/卸载内核模块、不 remount、不修改 sysctl/cgroup、不读写设备内容、不执行 ioctl、不变更宿主服务，也不扫描凭据。除本次临时探测节点、报告文件外不写入文件。全部设备/控制入口测试由有超时的独立子进程执行。

LXD 容器与宿主共享内核，运行时会提供必要的基础接口；本脚本检查配置造成的可见性和访问边界，不执行已知 CVE 利用，也不证明未知上游漏洞不存在。[LXD 安全模型](https://canonical.com/lxd/docs/latest/explanation/security/)、[容器运行环境](https://canonical.com/lxd/docs/latest/container-environment/)、[Linux 设备编号](https://docs.kernel.org/admin-guide/devices.html)

当前 WSL + LXD 6.9 + mas 0.2.11 的临时容器验证，使用真实宿主 namespace 和唯一标记：GPU 开启时 36 项结果（32 PASS、4 INFO），关闭时 34 项结果（30 PASS、4 INFO），均没有 FAIL、REVIEW、SKIP、ERROR。四种设备节点均在 mknod 阶段被拒绝，五种内核控制入口拒绝写方式打开；六种 namespace 与宿主不同，宿主标记不可见。AppArmor 原始结果仍是 enabled=N、profile=`kernel\u0000`，不宣称其已提供约束。

默认调用也已在该临时容器内验证：没有宿主参照时，六种 namespace 对比和宿主标记检查明确标为 7 项 SKIP，而不是通过；GPU 预期 unknown 只作 INFO。该次结果为 22 PASS、7 SKIP、5 INFO，无 FAIL/REVIEW/ERROR。

20 项独立回归检查验证错误分类、允许访问的 FAIL 分支、来源不明的 REVIEW 分支、超时、普通宿主/非 root 拒绝、报告不覆盖、方法与证据展示，以及一键入口的参数传递、退出码、下载失败、旧 Python 拒绝和临时文件清理。临时容器内另行验证了 root 直接执行、sandbox 通过系统 sudo 执行同一入口，以及报告保留在当前目录。发布后还在另一个新建临时容器中，以 sandbox 身份通过真实 GitHub 下载执行公开一键命令：GPU 开启、无宿主参照时为 24 PASS、7 SKIP、5 INFO，无 FAIL/REVIEW/ERROR。两份公开文件与已验证源码逐字节一致；报告正常保留，下载文件及临时 Project/容器已回收。证据：[GUEST_SECURITY_PROBE_REPORT.json](validation/GUEST_SECURITY_PROBE_REPORT.json)。这些检查没有改变已发布 mas 0.2.11 的程序、安装包或 mas-test 测试数量。
