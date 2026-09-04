# Phase 6 - 生产 Docker 部署设计

## 目标

- 从 Git 检出的仓库可构建只包含 FastAPI 的生产镜像。
- 前端在生产宿主机使用 Node 构建，静态产物由宿主机 Nginx 提供。
- Compose 只运行 API 容器，向宿主机映射一个可配置端口。
- SQLite 数据库保存到独立 Docker 命名卷，容器重建和版本升级不丢数据。
- 提供首次启动、配置、健康检查、备份、恢复、升级和回滚步骤。

## 非目标

- 不在本 Compose 中部署或复制 RAGFlow、LLM、ASR 和 TTS。
- 不把生产密钥、`.env`、SQLite、日志或种子 Excel 写入镜像和 Git。
- 不在容器内引入本地 embedding、Milvus 或旧项目的数据迁移逻辑。
- 不在应用容器内管理公网 TLS 证书。

## 镜像与运行拓扑

```text
宿主机 Nginx / HTTPS
    |-- /、/assets、/admin/* -> web/dist 静态文件 + SPA fallback
    `-- /api/*、/health -> 127.0.0.1:8192
                              |
                              v
                     biosafe: Uvicorn, workers=1
                       |-- FastAPI HTTP/SSE/WebSocket
                       |-- biosafe-data:/app/data
                       `-- 外部 RAGFlow/LLM/ASR/TTS
```

- `Dockerfile` 只构建 Python 3.12 API 镜像，不复制 `web/`，也不依赖 Node 镜像。
- 生产机在 `web/` 执行锁文件安装和 Vite production build，再将 `web/dist` 同步到 Nginx 静态目录。
- 前端统一通过 `VITE_API_BASE` 生成 HTTP 和 WebSocket 地址。生产配置留空以使用同源 `/api` 和 Nginx 反代；开发配置可指定后端 IP 和端口。Nginx 只对页面路由执行 SPA fallback，`/api/*` 不回退到 `index.html`。
- 运行阶段使用非 root 用户，启动时由应用执行幂等 SQLite migration 和管理员 upsert。
- Uvicorn 只运行一个 worker。当前纠错队列是进程内队列，多 worker/多容器会改变任务恢复和消费语义。

## 配置与数据

- Compose 从可配置的 `BIOSAFE_ENV_FILE` 注入生产环境，并强制 `BIOSAFE_ENV=production`、`BIOSAFE_DATABASE_PATH=/app/data/biosafe.db` 和容器内日志路径。
- `biosafe-data` 命名卷挂载到 `/app/data`，SQLite 主文件、WAL 和 SHM 位于同一持久化文件系统。
- `biosafe-logs` 命名卷挂载到 `/app/logs`；同时保留 stderr JSON 日志供 Docker 驱动轮转。
- RAGFlow/LLM/ASR/TTS 如果运行在 Docker 宿主机，使用 `host.docker.internal`；Compose 为 Linux 添加 `host-gateway` 映射。
- 命名卷备份时必须先停止 API，并整卷打包，不在运行中只拷贝 `.db` 而遗漏 WAL。

## 安全与故障策略

- 对外默认绑定 `127.0.0.1:8192`，由宿主机已有 HTTPS 反向代理转发；浏览器录音在非 localhost 环境需要 HTTPS。
- `.dockerignore` 排除 `.env*`、数据库、日志、Git 历史、本地依赖和测试产物。
- 镜像使用非 root 用户和只读根文件系统，仅数据/日志卷和 `/tmp` 可写。
- 容器配置健康检查、有界日志轮转、`unless-stopped` 重启和大于纠错队列排空时间的停止宽限。

## 回滚

- 镜像通过 `BIOSAFE_IMAGE` 可选标签命名；回滚时重新检出上一 Git 提交并重建。
- 代码回滚默认不回滚 SQLite schema。当前 migration 仅向前且可重复执行；需要数据回滚时必须在停止 API 后从整卷备份恢复。

## 验证

- `docker compose config --quiet`，不在开发机创建生产容器或镜像。
- `npm --prefix web run build` 验证宿主机静态产物构建。
- 生产机执行 `docker compose build/up` 后检查容器 health、HTTP/SSE 和 WebSocket；通过 Nginx 检查 SPA 子路由。
- 在隔离的测试卷写入历史，重建容器后确认记录仍存在。
- `conda run -n biosafe python -m pytest -q`
- `npm --prefix web test -- --run && npm --prefix web run lint && npm --prefix web run build`
