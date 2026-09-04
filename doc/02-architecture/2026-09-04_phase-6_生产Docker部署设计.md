# Phase 6 - 生产 Docker 部署设计

## 目标

- 从 Git 检出的仓库可构建一个同时包含 FastAPI 和 React 构建产物的生产镜像。
- Compose 只运行一个容器，向宿主机映射一个可配置端口。
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
           |
           v
  biosafe: Uvicorn, workers=1
    |-- FastAPI HTTP/SSE/WebSocket
    |-- React static + SPA fallback
    |-- biosafe-data:/app/data
    `-- 外部 RAGFlow/LLM/ASR/TTS
```

- `Dockerfile` 的 Node 阶段构建 React，Python 3.12 运行阶段只复制 `dist`，不包含 Node 运行时。
- FastAPI 在所有 API 路由之后挂载静态资源和 SPA fallback。未知 `/api/*` 仍返回 JSON 404，不会被 `index.html` 掩盖。
- 运行阶段使用非 root 用户，启动时由应用执行幂等 SQLite migration 和管理员 upsert。
- Uvicorn 只运行一个 worker。当前纠错队列是进程内队列，多 worker/多容器会改变任务恢复和消费语义。

## 配置与数据

- Compose 从可配置的 `BIOSAFE_ENV_FILE` 注入生产环境，并强制 `BIOSAFE_ENV=production`、`BIOSAFE_DATABASE_PATH=/app/data/biosafe.db`、`BIOSAFE_WEB_DIST_PATH=/app/web/dist` 和容器内日志路径。
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

- `docker compose config --quiet`
- `docker compose build`
- `docker compose up -d` 后检查容器 health、SPA 子路由、HTTP/SSE 和 WebSocket。
- 在隔离的测试卷写入历史，重建容器后确认记录仍存在。
- `conda run -n biosafe python -m pytest -q`
- `npm --prefix web test -- --run && npm --prefix web run lint && npm --prefix web run build`
