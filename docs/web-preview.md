# 见舟 Web 预览

本环境仅用于个人评估，默认演示模式并禁用切换到真实运行。固定托管尚未启用。上游授权范围待核实。

## Codespaces 首次登录和恢复

1. 在 GitHub 的 [Codespaces Secrets](https://github.com/settings/codespaces) 为本仓库配置 `JIANZHOU_ADMIN_PASSWORD`：16–512 字符的独立强密码，保存在密码管理器。
2. 若要在后台写入服务密钥，另配置 `JIANZHOU_SECRET_KEY`：32 个随机字节的 URL 安全 Base64 编码。密码管理器和云端密钥中各保留一份，备份时不要放在数据库旁。管理员密码和加密密钥分别使用不同随机值。Codespace 可在容器内以 `.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` 生成后直接填入 GitHub Secrets；不要把结果粘贴到聊天或提交。
3. 从 [Codespaces](https://github.com/codespaces) 停止并恢复 Web 预览环境以加载新设置。打开 Ports 中的 8741（Private）。在工作台登录提示或 `/admin` 输入管理员密码。不要把端口改为公开。
4. 若应用启动失败，维护者应检查 `data/codespaces-web-demo/logs/preview.log`。依赖更新时重建容器；在同一个 Codespace 内重启会保留仓库目录，删除 Codespace 会丢失预览数据。旧 PR #1 的独立演示目录不会被复用。

服务端验证工作台和后台 API 的会话，登录有效期 8 小时，退出后立即失效。替换管理员密码并重启会使旧会话失效。API 写请求要求来源与部署的 HTTPS 入口一致。模型密钥只显示是否已配置；云端环境变量预设的服务密钥优先于后台保存的值。真实服务联调需要另行审核。

## 固定托管、部署和回滚

`render.yaml` 是待审方案，会创建付费服务和持久磁盘；不要在获得明确批准前应用。免费 Web 服务无法持久保存 SQLite 与上传素材。创建后，由平台生成 HTTPS 地址；`/admin` 使用同域入口，应用从 Render 提供的 HTTPS Origin 验证写操作。上线前从未登录窗口和管理员窗口各验收一次。

功能分支从 `develop` 创建，经 PR 和审批合入 `develop`。Actions 同时检查 PR 和合入后的提交；Render 启用后，`checksPass` 要求检查成功才自动部署。首次上线及平台启用状态须单独验收。生产分支保持独立。回滚应用时选择 Render 部署历史中最后一个通过验收的提交；若该版本不兼容当前数据库，先停服务并恢复与该版本配对的数据快照。修复完成后再恢复自动部署。

## 数据与迁移

固定环境只应使用独立的持久卷 `/var/lib/jianzhou`；其中有 `app.db`、上传素材和生成文件。后台「系统与备份」可下载一致的数据库快照，不含活跃会话。素材未包含在该下载中，管理员应使用云平台的卷备份功能，或安排维护窗口停机备份整个卷。密钥单独保存；只持有数据库快照不能解密已加密凭据。

恢复前先在隔离环境检查备份完整性并试启。恢复整卷时停服务并保留当前卷的副本，恢复数据库、上传及其他生成文件，检查数据库和密钥能正确读取后再开放 HTTPS。若只用后台数据库快照，停机后替换 `app.db` 时要移走旧的 `app.db-wal` 和 `app.db-shm`，并同时恢复配套的素材。不要把备份文件提交到 Git。

后续 Ubuntu VPS 可复用同一容器和同一挂载路径，避免数据库中的绝对素材路径失效。部署时为持久卷设置权限，通过反向代理终止 HTTPS，应用端口只在内部网络监听，设置 `JIANZHOU_WEB_ORIGIN` 为精确的外部 HTTPS 地址，并从云端密钥注入原加密密钥和新管理员密码。正式环境的上线、域名及备份自动化另行审核。
