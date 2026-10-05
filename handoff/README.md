# 0.2.25 developer handoff

从 [START_HERE.md](START_HERE.md) 开始，包含新 Codex 的阅读顺序和可直接粘贴的续接提示词。

本目录提供 [交接压缩包](my-ai-sandbox-0.2.25.tar.gz)、外部 [SHA256SUMS](SHA256SUMS) 和 [MANIFEST.json](MANIFEST.json)。请一起下载这三个文件，再按 START_HERE 的步骤校验和恢复。包内是一个自包含 Git bundle、恢复脚本、接手指南、精确基准清单和内部校验和。源码、全部当前/历史文档、测试及已提交 validation 在离线 Git 克隆中还原；main、release 和所有已有标签的完整可达历史也保留。

仅封装指定已提交 Git refs，不包含安装后的 ~/.local/bin、个人/全局配置、凭据、LXD 数据或未提交临时文件。三份项目规范是 [AGENTS.md](../AGENTS.md)、[CODE_PRINCIPLE.md](../docs/CODE_PRINCIPLE.md) 和 [CLI_TUI_GUIDELINES.md](../docs/CLI_TUI_GUIDELINES.md)；两份开发规范保留用户原文，由项目 AGENTS.md 明确引用，恢复时不写入 `~/.codex`。公开 GitHub 发布目录及所有资产 URL/摘要保存在 [RELEASES.json](RELEASES.json)，二进制发布附件不重复封装；源码重建核对当前三个 zipapp 的准确字节。

## 冻结与更新

先提交已审查的源码/文档基准，再生成包。后续本次 archive/receipt 上传提交不在该包快照中，避免本次包包含自身；压缩包顶层 MANIFEST 的基准提交是事实入口，而不是要求它等于未来 GitHub main。完整历史保留已经提交的上一代压缩包，恢复仓库 handoff/ 内的旧包/清单因此仍属于上一代，不能代替本次压缩包顶层清单。原 stable/test 标签、资产及 release 分支保持不变。包中不携带机器的 .git/config/hooks/凭据；恢复后 origin 是公开 HTTPS 仓库，写权限由新环境配置。

构建工具只需 Python 标准库和 Git，输出必须是不存在的新目录，基准必须是已提交内容：

```bash
python3 scripts/build_handoff.py --commit HEAD --include-prior-archives --output /absolute/path/new-handoff-output
```

工具读取基准内的 START_HERE、RESTORE 和 RELEASES 目录，并封装该 main 基准、release、全部标签，不依赖工作区未提交内容。默认仍拒绝包含先前 handoff 二进制包的历史。此次项目规范补齐采用显式 --include-prior-archives，保留完整已发布历史，并在 prior_handoff_archives 列出旧包的路径、Git blob、SHA-256 和大小，不删除或过滤历史。本次新包在冻结之后才上传。重复完整历史打包会随旧包累计增大；以后改变分发或历史策略仍须先讨论，不能静默改成增量包或重写已有历史。

本次规范补齐后的精确冻结提交、文件/提交数量、包大小和 SHA-256 以 [MANIFEST.json](MANIFEST.json) 为准。第一代包冻结于 `a01fefee8a8a86e90786054076d7a085a0b3d721`，包含 335 个 tracked 文件、91 条 main 提交，大小 3,544,375 字节，SHA-256 为 `825307da4320e4b94fcfa9a03f65ac8b787a516ae894a2678104b96ea926d41f`；其历史身份和原核验记录保留在 Git 与 IMPLEMENTED.md 阶段 47。release 仍为两条提交，43 个原标签保持不变。

第一代包的本地/公开离线恢复、完整历史、拒绝/损坏检查、重建和 449 项打包单元测试已通过；其 [公开核验记录](../validation/HANDOFF_0_2_25_PUBLIC_REVIEW.json) 保留不改。本次三份项目规范补齐及重新打包的独立核验结果另记在 [IMPLEMENTED.md](../IMPLEMENTED.md)，在验证完成后记录，不沿用第一代的包哈希作为本次结果。该批不改产品版本、不新增产品发布，也不声称新的完整 LXD 实机测量。

格式依据：[Git bundle](https://git-scm.com/docs/git-bundle)。使用说明见 START_HERE；构建、测试和发布规则见 [DEVELOPMENT.md](../docs/DEVELOPMENT.md)。
