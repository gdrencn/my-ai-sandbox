# 0.2.25 developer handoff

从 [START_HERE.md](START_HERE.md) 开始，包含新 Codex 的阅读顺序和可直接粘贴的续接提示词。

本目录将发布 `my-ai-sandbox-0.2.25.tar.gz`、外部 `SHA256SUMS` 和 `MANIFEST.json`。包内是一个自包含 Git bundle、恢复脚本、接手指南、精确基准清单和内部校验和。源码、全部当前/历史文档、测试及已提交 validation 在离线 Git 克隆中还原；main、release 和所有已有标签的完整可达历史也保留。

仅封装指定已提交 Git refs，不包含安装后的 ~/.local/bin、个人/全局配置、凭据、LXD 数据或未提交临时文件。公开 GitHub 发布目录及所有资产 URL/摘要保存在 [RELEASES.json](RELEASES.json)，二进制发布附件不重复封装；源码重建核对当前三个 zipapp 的准确字节。

## 冻结与更新

先提交已审查的源码/文档基准，再生成包。后续 archive/receipt 上传提交不在该包快照中，避免包包含自身；MANIFEST 的基准提交是事实入口，而不是要求它等于未来 GitHub main。原 stable/test 标签、资产及 release 分支保持不变。包中不携带机器的 .git/config/hooks/凭据；恢复后 origin 是公开 HTTPS 仓库，写权限由新环境配置。

构建工具只需 Python 标准库和 Git，输出必须是不存在的新目录，基准必须是已提交内容：

```bash
python3 scripts/build_handoff.py --commit HEAD --output /absolute/path/new-handoff-output
```

工具读取基准内的 START_HERE、RESTORE 和 RELEASES 目录，并封装该 main 基准、release、全部标签，不依赖工作区未提交内容。它拒绝包含先前 handoff 压缩包的可达历史；后续需要完整新包时，先讨论归档分发路径/历史策略，不能静默变成缺少历史的增量包或无限嵌套。

恢复验证包含完整历史、所有标签/分支、Git fsck、现有目标拒绝、路径含空格、内部/外部损坏拒绝、三份 zipapp 重建一致、449 项项目外打包单元测试，以及 GitHub 下载后的重复校验/恢复。具体结果核验后记录在 IMPLEMENTED.md；该批不改版本、不新增产品发布，也不重复声称新的完整 LXD 实机测量。

格式依据：[Git bundle](https://git-scm.com/docs/git-bundle)。使用说明见 START_HERE；构建、测试和发布规则见 [DEVELOPMENT.md](../docs/DEVELOPMENT.md)。
