# 0.1.3

版本统一为 `a.b.c`，本批次为 `0.1.3`；产品与测试工具保持一致，不再使用 `-test.x` 后缀。固定入口按数字版本选择最高的已发布版本，包含 GitHub prerelease。

- 支持 `zh_cn` / `en_us`。安装开始前选择语言，后续安装使用已保存的默认值；可通过 `--language` 明确指定。
- 文案集中保存于语言文件。CLI 支持 `mas config`、`mas config get language` 和 `mas config set language zh_cn|en_us`。TUI 按 `c` 打开配置，`1` / `2` 切换语言并立即生效。
- 安装需要宿主权限时先使用系统 `sudo -v`；后续使用正常 sudo。没有密码处理、自定义认证缓存、保活或宿主 sudoers 修改。LXD 已准备好的测试环境无需宿主 sudo。
- 保留 `snap wait system seed.loaded` 的提权修复。测试增加语言持久化、真实终端语言选择、中文 TUI 操作、数字版本排序和 sudo 前置认证检查。

一行下载安装并测试：

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --test
```

默认等待 600 秒，每秒探测。测试使用随机 `test-<uuid>` 容器及隔离的 LXD project、临时语言配置；不修改用户容器或语言偏好。

验证环境：当前 WSL2 / Ubuntu 26.04.1 / Python 3.14.4 / LXD 6.9，详细结果见 `WSL_REPORT.json`。原生 Ubuntu、其他架构和全新机器从零安装尚未做端到端实测；缺失 snapd/LXD 的权限路径通过标准库模拟回归测试验证。
