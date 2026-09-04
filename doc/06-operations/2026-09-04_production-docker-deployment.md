# 生产 Docker 部署

## 部署结果

Compose 只运行 `biosafe` 一个容器，把容器 `8000` 映射到宿主机指定端口。镜像构建时生成 React 静态文件，运行时由 FastAPI 同时提供页面、HTTP/SSE API 和语音 WebSocket；宿主机 Nginx 只需转发这一个端口。SQLite 位于 `biosafe-data` 命名卷，执行 `docker compose down`、重建镜像或替换容器都不会删除该卷。

> 不要执行 `docker compose down -v`，除非已备份且确定要删除数据。

## 生产配置

生产 `.env` 不需要与开发机完全相同。建议从 `deploy/production.env.example` 核对变量，真实文件放在 Git 仓库外，例如 `/etc/biosafe/biosafe.env`：

```bash
sudo install -d -m 700 /etc/biosafe
sudo install -m 600 deploy/production.env.example /etc/biosafe/biosafe.env
sudo editor /etc/biosafe/biosafe.env
export BIOSAFE_ENV_FILE=/etc/biosafe/biosafe.env
```

每次 Compose 命令同时传入该文件，使其中的端口、镜像名和卷名也参与 Compose 变量替换：

```bash
docker compose --env-file "$BIOSAFE_ENV_FILE" config --quiet
docker compose --env-file "$BIOSAFE_ENV_FILE" up -d --build
```

如果生产机已在仓库根目录维护 `.env`，可直接保持默认，不设 `BIOSAFE_ENV_FILE`。`.env` 已被 Git 和 Docker build context 忽略。

如果生产机不能访问 Docker Hub，将 `PYTHON_BASE_IMAGE` 和 `NODE_BASE_IMAGE` 改为生产私有仓库或本机已有镜像名。运行阶段默认 `python:3.12-slim` 与旧 `biosafe-rag` 生产 Dockerfile 一致；Node 只用于构建，不会进入最终镜像。`PIP_INDEX_URL` 和 `NPM_REGISTRY` 也可换成生产可访问的依赖镜像，但不要把带凭据的 URL 写入 Git。

### 旧项目变量迁移

| 旧环境变量 | 新环境处理 |
| :--- | :--- |
| `CHAT_*` | 继续使用，补充 `CHAT_TIMEOUT_SECONDS` |
| `ASR_*` | 继续使用；宿主服务地址不能在容器中写 `localhost` |
| `TTS_*` | 继续使用，建议显式补充采样率和重试变量 |
| `ANSWER_EVALUATION_*` | 仍有兼容别名；建议改名为 `CORRECTION_*` 并设置 `CORRECTION_ENABLED` |
| `BIOSAFE_ADMIN_*` | 继续使用；`BIOSAFE_ADMIN_TOKEN_SECRET` 必须至少 32 个随机字符 |
| `RAGFLOW_*` | 新系统必须新增，其中 `RAGFLOW_DATASET_IDS` 是在线默认检索范围 |
| `EMBEDDING_*`、`HISTORY_QA_*`、`RAG_ROLE_TOP_K` | 已删除，不要复制到新配置 |
| `TAGGING_*`、`MINERU_API_TOKEN`、`DEMO_MOCK_ENABLED` | 已删除，不要复制到新配置 |

如果 RAGFlow、ASR 或 TTS 运行在同一台 Docker 宿主机，容器内地址使用 `host.docker.internal`，Compose 已在 Linux 上映射到 host gateway。如果运行在其他机器，使用真实 DNS 名或局域网 IP。

## 首次启动

```bash
git clone <repository-url> new_biosafe
cd new_biosafe
export BIOSAFE_ENV_FILE=/etc/biosafe/biosafe.env
docker compose --env-file "$BIOSAFE_ENV_FILE" build --pull
docker compose --env-file "$BIOSAFE_ENV_FILE" up -d
docker compose --env-file "$BIOSAFE_ENV_FILE" ps
curl --fail http://127.0.0.1:8192/health
curl --fail --head http://127.0.0.1:8192/admin/history
```

如果修改了 `BIOSAFE_HTTP_PORT`，同步替换上述端口。API 启动时会在持久卷中建立/迁移 `/app/data/biosafe.db`，并在管理员配置完整时幂等更新密码哈希。

查看状态和日志：

```bash
docker compose --env-file "$BIOSAFE_ENV_FILE" ps
docker compose --env-file "$BIOSAFE_ENV_FILE" logs --tail=200 biosafe
docker volume inspect biosafe-data
```

## HTTPS 与语音

Compose 默认把容器的 `8000` 映射到宿主 `127.0.0.1:8192`，应由宿主机的 HTTPS Nginx 转发。非 localhost 网页必须使用 HTTPS，否则浏览器通常拒绝麦克风权限。宿主 Nginx 可使用以下核心配置：

```nginx
location / {
    proxy_pass http://127.0.0.1:8192;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 300s;
    client_max_body_size 500m;
}
```

如暂时需要局域网 HTTP 直连，将 `BIOSAFE_BIND_ADDRESS` 设为 `0.0.0.0`；该方式不适合启用浏览器录音的正式环境。

## SQLite 备份与恢复

SQLite 使用 WAL。备份前先停止 API，然后打包整个卷：
以下命令使用默认卷名 `biosafe-data`；如果生产配置修改了 `BIOSAFE_DATA_VOLUME`，同步替换命令中的卷名。

```bash
mkdir -p backups
export BACKUP_FILE="biosafe-data-$(date +%Y%m%d-%H%M%S).tgz"
docker compose --env-file "$BIOSAFE_ENV_FILE" stop biosafe
docker run --rm \
  -v biosafe-data:/data:ro \
  -v "$PWD/backups:/backup" \
  alpine:3.20 tar czf "/backup/$BACKUP_FILE" -C /data .
docker compose --env-file "$BIOSAFE_ENV_FILE" start biosafe
```

恢复时不覆盖原卷，而是建立新卷，验证后再切换：

```bash
docker compose --env-file "$BIOSAFE_ENV_FILE" stop biosafe
docker volume create biosafe-data-restored
docker run --rm \
  -v biosafe-data-restored:/data \
  -v "$PWD/backups:/backup:ro" \
  alpine:3.20 tar xzf "/backup/$BACKUP_FILE" -C /data
```

将生产配置中 `BIOSAFE_DATA_VOLUME` 改为 `biosafe-data-restored`，然后重建容器：

```bash
docker compose --env-file "$BIOSAFE_ENV_FILE" up -d --force-recreate biosafe
curl --fail http://127.0.0.1:8192/health
```

确认历史和人工标注后再决定是否保留原 `biosafe-data` 卷。

## 升级与回滚

升级前先备份，然后：

```bash
git pull --ff-only
docker compose --env-file "$BIOSAFE_ENV_FILE" build --pull
docker compose --env-file "$BIOSAFE_ENV_FILE" up -d
docker compose --env-file "$BIOSAFE_ENV_FILE" ps
```

当前容器内含进程内异步纠错队列，不要设置多 worker，也不要在没有队列架构调整的情况下水平扩容。Compose 给容器 45 秒停止宽限，容纳默认 30 秒的任务排空。

代码回滚时检出上一个已验证提交并重建，不要自动降级 SQLite schema。如果新版本已执行不兼容数据迁移，从升级前整卷备份恢复到新命名卷。
