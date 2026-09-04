# 生产 Docker 部署

## 部署结果

Compose 只运行 `biosafe` 后端容器，把容器 `8000` 映射到宿主机指定端口。该镜像只包含 Python API，不包含 Node、前端源码或静态产物。生产宿主机使用已有 Node 构建 `web/dist`，再由宿主机 Nginx 直接提供页面并将 `/api/` 和 `/health` 转发到后端。SQLite 位于 `biosafe-data` 命名卷，执行 `docker compose down`、重建镜像或替换容器都不会删除该卷。

> 不要执行 `docker compose down -v`，除非已备份且确定要删除数据。

## 生产配置

与旧项目一致，生产机直接在仓库根目录提供 `.env`，Compose 通过 `env_file` 注入容器。变量名必须与当前仓库的 `.env.example` 保持一致，生产环境只修改值，不增加旧系统变量或 Docker 构建控制变量。至少确认 `BIOSAFE_ENV=production`，数据库路径保持 `data/biosafe.db`，实验目录保持 `experiments`。

```bash
cd new_biosafe
test -f .env
chmod 600 .env
docker compose config --quiet
```

`.env` 已被 Git 和 Docker build context 忽略，不会写入镜像。Dockerfile 固定使用 `python:3.12-slim` 和旧项目相同的阿里 PyPI 源；Compose 固定容器名、`127.0.0.1:8192:8000` 端口和 `biosafe-data`/`biosafe-logs` 卷，不再为这些值增加环境变量。

RAGFlow、ASR 或 TTS 如果运行在 Docker 宿主机，`.env` 中对应地址使用 `host.docker.internal`，Compose 已在 Linux 上映射到 host gateway；如果运行在其他机器，使用真实 DNS 名或局域网 IP，不能写容器自身的 `localhost`。

### 前端 API 地址

前端恢复旧项目使用的 `VITE_API_BASE` 配置，并统一作用于 HTTP、健康检查和语音 WebSocket：

- `web/.env.production`：值为空，production build 使用当前域名，由 Nginx 转发 `/api/` 和 `/health`。
- `web/.env.development`：默认 `http://127.0.0.1:8000`，开发浏览器直接访问指定后端。
- `web/.env.development.local`：可在本机覆盖开发地址，例如 `VITE_API_BASE=http://10.158.0.31:8000`；该文件被 Git 忽略。

开发环境跨域直连时，后端 `BIOSAFE_CORS_ORIGINS` 必须包含实际前端 Origin（协议、IP 和端口均需匹配）。生产前后端同源，不需要额外跨域配置；重新修改 `VITE_API_BASE` 后必须重新执行前端 build。

## 首次启动

```bash
git clone <repository-url> new_biosafe
cd new_biosafe

# 在宿主机生成并发布前端静态文件
npm --prefix web ci
npm --prefix web run build
sudo install -d -m 755 /var/www/biosafe
sudo rsync -a --delete web/dist/ /var/www/biosafe/

# 构建并启动纯后端容器
docker compose build --pull
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8192/health
```

如需修改宿主端口，直接编辑 `docker-compose.yml` 的 `ports`。API 启动时会在持久卷中建立/迁移 `/app/data/biosafe.db`，并在管理员配置完整时幂等更新密码哈希。Nginx 配置生效后，再通过正式域名检查 `/` 和 `/admin/history`。

查看状态和日志：

```bash
docker compose ps
docker compose logs --tail=200 biosafe
docker volume inspect biosafe-data
```

## Nginx、HTTPS 与语音

Compose 默认把容器的 `8000` 映射到宿主 `127.0.0.1:8192`。Nginx 从 `/var/www/biosafe` 提供前端，只将后端路径反向代理到该端口。默认 production build 的 fetch 和 WebSocket 均使用同源路径。非 localhost 网页必须使用 HTTPS，否则浏览器通常拒绝麦克风权限。

以下内容放在对应的 Nginx `server` 块中：

```nginx
root /var/www/biosafe;
index index.html;

location /assets/ {
    try_files $uri =404;
    expires 1y;
    add_header Cache-Control "public, immutable";
}

location / {
    try_files $uri $uri/ /index.html;
}

location = /health {
    proxy_pass http://127.0.0.1:8192;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}

location /api/ {
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

`try_files` 只用于前端页面。不要让 `/api/` 或 `/health` 回退到 `index.html`，否则 API 404 会被误包装成 HTML。`proxy_buffering off` 用于保证流式回答及时到达浏览器，Upgrade 头用于 `/api/v1/chat/audio` WebSocket。

如暂时需要局域网 HTTP 直连，可将 Compose 端口绑定从 `127.0.0.1` 改为 `0.0.0.0`；该方式不适合启用浏览器录音的正式环境。

## SQLite 备份与恢复

SQLite 使用 WAL。备份前先停止 API，然后打包固定的 `biosafe-data` 卷：

```bash
mkdir -p backups
export BACKUP_FILE="biosafe-data-$(date +%Y%m%d-%H%M%S).tgz"
docker compose stop biosafe
docker run --rm \
  -v biosafe-data:/data:ro \
  -v "$PWD/backups:/backup" \
  alpine:3.20 tar czf "/backup/$BACKUP_FILE" -C /data .
docker compose start biosafe
```

恢复时不覆盖原卷，而是建立新卷，验证后再切换：

```bash
docker compose stop biosafe
docker volume create biosafe-data-restored
docker run --rm \
  -v biosafe-data-restored:/data \
  -v "$PWD/backups:/backup:ro" \
  alpine:3.20 tar xzf "/backup/$BACKUP_FILE" -C /data
```

将 `docker-compose.yml` 中 `biosafe-data` 的固定 `name` 暂时改为 `biosafe-data-restored`，然后重建容器：

```bash
docker compose up -d --force-recreate biosafe
curl --fail http://127.0.0.1:8192/health
```

确认历史和人工标注后再决定是否保留原 `biosafe-data` 卷。

## 升级与回滚

升级前先备份，然后：

```bash
git pull --ff-only

# 更新前端静态文件
npm --prefix web ci
npm --prefix web run build
sudo rsync -a --delete web/dist/ /var/www/biosafe/

# 更新后端
docker compose build --pull
docker compose up -d
docker compose ps
```

当前容器内含进程内异步纠错队列，不要设置多 worker，也不要在没有队列架构调整的情况下水平扩容。Compose 给容器 45 秒停止宽限，容纳默认 30 秒的任务排空。

代码回滚时检出上一个已验证提交并重建，不要自动降级 SQLite schema。如果新版本已执行不兼容数据迁移，从升级前整卷备份恢复到新命名卷。
