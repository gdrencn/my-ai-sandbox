# 新 Codex 接手入口

你接手的是 my-ai-sandbox：基于 LXD、Python 标准库、CLI 与内联终端菜单共用操作的项目。当前产品版本 **0.2.25**，test v0.2.25 与用户验收的 stable/0.2.25 产品/安装包完全一致；stable 为 GitHub latest。

## 先恢复，再阅读

如果已经克隆 GitHub 主分支，直接从下一节开始。如果收到交接压缩包：

```bash
sha256sum -c SHA256SUMS
tar -xzf my-ai-sandbox-0.2.25.tar.gz
bash my-ai-sandbox-handoff-0.2.25/RESTORE.sh ./my-ai-sandbox
cd my-ai-sandbox
```

外部 SHA256SUMS/MANIFEST.json 与压缩包放在同一目录。恢复脚本核对内部校验和，离线克隆 Git bundle，恢复 main、release 和全部标签，把 origin 设置成公开 GitHub URL；已有目标（包括空目录或符号链接）一律拒绝。它不安装软件、不登录、不运行 mas、不修改 LXD。只需 Bash、Git、tar、sha256sum；构建和测试另需 Python 3.10+。

压缩包的 MANIFEST.json 记录冻结 main 提交、release/test/stable/tag 身份、Git 历史范围和资产哈希。后续上传压缩包及验证报告的提交不在这个冻结快照内，避免自包含；它们不改变产品。联网后可 `git fetch origin` 查看较新的文档/收尾提交，再自行比较，不能把包内状态误当最新远端状态。

## 必须阅读

1. [AGENTS.md](../AGENTS.md)：中文沟通、先讨论后执行、需求先行、核验后更新文档；已有明确授权不要重复请求。
2. [REQUIREMENTS.md](../REQUIREMENTS.md)：当前已批准契约、当前交接整理范围及完整待确认表。
3. [IMPLEMENTED.md](../IMPLEMENTED.md)：完成范围、版本/提交/资产身份和实测证据。
4. [docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md)、[docs/DECISIONS.md](../docs/DECISIONS.md)：模块职责、构建/测试/发布流程、已确定的选择。
5. [docs/CLI_TUI_GUIDELINES.md](../docs/CLI_TUI_GUIDELINES.md)、[CORE_BEHAVIOR.md](../CORE_BEHAVIOR.md)、[TEST_COVERAGE.md](../TEST_COVERAGE.md)：共享交互、完成/失败边界和验证限制。

菜单、安全和用户操作分别见 MENU_REVIEW.md、GUEST_SECURITY_PROBE.md、README.md；完整索引见 [docs/README.md](../docs/README.md)。历史批准和 46 个原始实施阶段在 docs/history，不能用已过时的方案覆盖当前文档。

## 接手时要知道

- 当前 About/version 功能及 stable 晋升已验收。冻结本地/公开 test/公开 stable 均通过 449 项单元、28 个测试阶段、一次 76 项安全挑战并完成清理；详细报告均在 validation。不要自动重跑半小时实机测试或把交接整理当新增产品发布。
- main 维护开发/测试/文档；release 仅在稳定发布时前进，现有稳定代码只有两条提交、34 个 tracked 文件。test/stable 标签、旧 Releases/资产不得重写。
- 按职责修改共享 Manager、政策、GPU、网络、挂载或 UI 模块；先修组件，保留 UUID/ETag/原生错误和清理范围。生成 Shell 入口通过共享模板构建。
- CPU/内存/进程、磁盘配额、流量/登录/端口策略、基本 devlxd/AppArmor、终端后重启再进入，以及新增 GPU/平台验证需要讨论。当前 NIC on/off 已实现；Node.js/npm 来自 Ubuntu APT，不是旧官方 LTS 安装器。
- 实测是 Ubuntu 26.04 WSL、LXD 6.9、NVIDIA、x86_64；用户另有新宿主安装、窗口缩放和 About 验收。原生 Ubuntu/cloud、ARM64、其他 GPU/存储后端没有新增实测。
- 历史报告中的 /home/gordon 和临时路径是原执行地点。源码、文档、测试、报告及 Git 历史在包内；Python/Git/宿主 LXD、凭据、用户配置、容器镜像/数据及 GitHub Releases 二进制附件本身不在包内。三个 zipapp 可从恢复源码重建为相同字节；附件 URL/哈希在 RELEASES.json。

## 给全新 Codex 的续接提示词

```text
这是 my-ai-sandbox 的交接 bundle。请核对外部与内部 SHA-256 清单，并恢复到一个不存在的新目录；这一步已授权，不要安装软件或运行容器操作。
然后阅读项目 AGENTS.md、handoff/START_HERE.md、REQUIREMENTS.md、IMPLEMENTED.md、docs/DEVELOPMENT.md、docs/DECISIONS.md 和 docs/CLI_TUI_GUIDELINES.md。
请用中文说明：当前 0.2.25 stable/test 状态、已完成范围、main/release/tag 身份、验证证据与未验证平台，以及仍待确认的事项。
先讨论下一项需求和验收标准，等我明确授权后开发；不要自行实现待确认事项、重写已有发布，或把旧历史方案当当前要求。
新工作要先更新项目 REQUIREMENTS.md，按需求修改共享模块，验证后更新 IMPLEMENTED.md 和受影响文档。不要依赖旧会话、全局 Codex 文件或 /home/gordon 临时目录。
```

如果已有仓库，可以把第一句换为：“请以这个仓库为接手起点，先核对 Git 状态和交接 MANIFEST，再按阅读顺序汇报现状。”
