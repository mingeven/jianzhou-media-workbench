# 见舟工作台云端演示

从当前分支打开 GitHub Codespaces。容器会安装 Python 项目依赖及 FFmpeg，并在启动时运行见舟。通过编辑器的 Ports 标签页确认 8741 为 Private，再点击该端口的浏览器链接。此入口需要使用创建 Codespace 的 GitHub 账号登录。

演示数据保存在 `data/codespaces-demo/`，Git 会忽略该目录。此目录在同一个 Codespace 中停止和恢复后会保留，删除 Codespace 前需另行保存。首次使用此目录时进入演示模式。云端预览限个人评估，请保持演示模式，使用示例数据。

如预览未启动，可在云端终端运行 `bash scripts/start_cloud_preview.sh`，启动日志位于 `data/codespaces-demo/logs/preview.log`。工作台仅监听容器回环地址，浏览器的 HTTPS 访问和认证由 GitHub 私有端口处理。

在云端终端运行基础测试。

```bash
.venv/bin/python -m compileall -q app app.py
.venv/bin/python -m unittest discover -s tests -v
curl --fail http://127.0.0.1:8741/healthz
```

业务冒烟脚本会写入数据。需要单独启动一个使用临时数据目录的实例，然后对该实例运行 `scripts/smoke_test.py`。
