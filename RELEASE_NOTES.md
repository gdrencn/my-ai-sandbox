# 0.1.4

- 安装程序自动配置实际安装目录的 PATH，保留已有配置并避免重复添加。安装后重新打开终端即可运行 `mas`，无需手动 export。
- 产品、安装程序、测试工具分别发布为 `mas.pyz`、`mas-install.pyz`、`mas-test.pyz`。普通安装不下载或安装测试工具；`--test` 才额外下载测试工具，由它调用配套安装程序后测试。产品中不包含安装模块、测试代码或测试专用文案。
- 首次默认中文 `zh_cn`，已有语言配置继续生效。自己的安装、测试阶段、进度和总结文案使用所选语言；命令、标识符和原生外部输出保持原样。英文界面测试的原始记录保存在日志中。
- 正常测试进度在终端同一行刷新，环节结束后清除；每个环节保留成功总结。警告、错误和失败详情保留，故意触发的错误标记为“预期错误”。非交互输出无刷新控制符。
- 测试结束输出通过、失败、未执行数量、总耗时、清理结果和报告路径。完整原生输出、终端记录和逐秒等待数据仍保留在日志中。

普通安装：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash
```

安装并自动测试：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --test
```

宿主 sudo 继续使用系统默认认证，不保存密码或保活。当前 WSL 环境的验证结果随 `WSL_REPORT.json` 发布；原生 Ubuntu 和其他架构未实测。用户提供的 0.1.3 日志已验证缺失 LXD 时的自动安装及完整测试流程。
