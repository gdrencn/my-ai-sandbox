# 0.2.25 developer handoff

从 [START_HERE.md](START_HERE.md) 开始，包含新 Codex 的阅读顺序和可直接粘贴的续接提示词。

本目录提供 [交接压缩包](my-ai-sandbox-0.2.25.tar.gz)、外部 [SHA256SUMS](SHA256SUMS) 和 [MANIFEST.json](MANIFEST.json)。请一起下载这三个文件，再按 START_HERE 的步骤校验和恢复。包内是一个自包含 Git bundle、恢复脚本、接手指南、精确基准清单和内部校验和。源码、全部当前/历史文档、测试及已提交 validation 在离线 Git 克隆中还原；main、release 和所有已有标签的完整可达历史也保留。

仅封装指定已提交 Git refs，不包含安装后的 ~/.local/bin、个人/全局配置、凭据、LXD 数据或未提交临时文件。公开 GitHub 发布目录及所有资产 URL/摘要保存在 [RELEASES.json](RELEASES.json)，二进制发布附件不重复封装；源码重建核对当前三个 zipapp 的准确字节。

## 冻结与更新

先提交已审查的源码/文档基准，再生成包。后续 archive/receipt 上传提交不在该包快照中，避免包包含自身；MANIFEST 的基准提交是事实入口，而不是要求它等于未来 GitHub main。原 stable/test 标签、资产及 release 分支保持不变。包中不携带机器的 .git/config/hooks/凭据；恢复后 origin 是公开 HTTPS 仓库，写权限由新环境配置。

构建工具只需 Python 标准库和 Git，输出必须是不存在的新目录，基准必须是已提交内容：

```bash
python3 scripts/build_handoff.py --commit HEAD --output /absolute/path/new-handoff-output
```

工具读取基准内的 START_HERE、RESTORE 和 RELEASES 目录，并封装该 main 基准、release、全部标签，不依赖工作区未提交内容。它拒绝包含先前 handoff 压缩包的可达历史；后续需要完整新包时，先讨论归档分发路径/历史策略，不能静默变成缺少历史的增量包或无限嵌套。

冻结 main 基准为 `a01fefee8a8a86e90786054076d7a085a0b3d721`，包含 335 个 tracked 文件和 main 的 91 条提交；release 保持两条提交，43 个原标签完整保留。包大小为 3,544,375 字节，内外清单记录准确 SHA-256。

本地恢复验证已通过完整历史、所有标签/分支、Git fsck、现有目标拒绝、路径含空格、内部/外部损坏拒绝、三份 zipapp 重建一致和 449 项项目外打包单元测试。GitHub 公开下载后的校验、新目录离线恢复和再次重建也全部通过，旧 43 个 Releases/资产/标签、release 分支和 latest stable 保持不变；具体证据见 [IMPLEMENTED.md](../IMPLEMENTED.md) 与 [公开核验记录](../validation/HANDOFF_0_2_25_PUBLIC_REVIEW.json)。该批不改版本、不新增产品发布，也不声称新的完整 LXD 实机测量。

格式依据：[Git bundle](https://git-scm.com/docs/git-bundle)。使用说明见 START_HERE；构建、测试和发布规则见 [DEVELOPMENT.md](../docs/DEVELOPMENT.md)。
