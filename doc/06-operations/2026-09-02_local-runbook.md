# 本地运行与排障

## 运行前提

- 工作目录：`/cache/hanqingzhe/new_biosafe`。
- Python 环境：conda `biosafe`。
- Node.js 与 `web/node_modules` 已准备。
- 根目录 `.env` 已按 `.env.example` 配置；不得把真实凭据提交到 Git。

首次安装或依赖变化后运行：

```bash
conda run -n biosafe python -m pip install -e .
```

## 后端

```bash
conda run -n biosafe python scripts/run_api.py
```

`scripts/run_api.py` 按以下顺序工作：

1. 定位并读取 `.env`，默认不覆盖进程已有环境变量。
2. 从环境构造 `Settings`，建立日志目录和 JSON 日志处理器。
3. 启动 Uvicorn，启用 error 和 access 日志。
4. FastAPI 启动时执行 SQLite 迁移，并在管理员配置完整时更新本地管理员密码哈希。

命令参数通过 `python scripts/run_api.py --help` 查看。缺少 `.env` 时脚本会直接退出并打印文件路径，避免使用一套空配置误启动。

## 前端

```bash
npm --prefix web run dev
```

Vite 把 `/api` 和 `/health` 代理到本机 8000 端口，其中 `/api` 显式开启 WebSocket 转发。通过 `http://10.158.0.31:5173` 访问时，浏览器语音地址应为 `ws://10.158.0.31:5173/api/v1/chat/audio`，再由 Vite 转发到 FastAPI。浏览器路由包括 `/`、`/history`、`/system` 和 `/knowledge`。生产部署的反向代理必须同时支持 `/api/v1/chat/audio` 的 WebSocket upgrade，并把非 API 页面路径回退到前端 `index.html`。

## 管理员初始化

管理员认证依赖四个变量：

- `BIOSAFE_ADMIN_USERNAME`：登录名，示例值为 `admin`。
- `BIOSAFE_ADMIN_PASSWORD`：本机管理员密码，不提供代码默认值。
- `BIOSAFE_ADMIN_TOKEN_SECRET`：至少 32 字符的随机签名密钥。
- `BIOSAFE_ADMIN_TOKEN_TTL_SECONDS`：登录 token 有效期，默认 28800 秒。

密码只在应用启动时读取并哈希写入 `admin_user`。修改 `.env` 后必须重启 API。浏览器只在 localStorage 保存有过期时间的签名 token，不保存密码。

## 日志

默认文件为 `logs/biosafe-api.log`，由 `BIOSAFE_LOG_FILE` 调整。日志同时写 stderr，采用 JSON 行格式，单文件上限 10 MiB，保留 5 个滚动备份。

检查顺序：

1. 启动终端是否出现 `starting biosafe api`。
2. `logs/biosafe-api.log` 是否创建且可写。
3. 访问 `http://localhost:8000/health` 后是否出现 HTTP access 记录。
4. 按 `request_id` 或 `session_id` 检查问答和语音链路。

禁止把日志复制到版本控制。日志消息中的 Authorization、API key、token 和 password 会由 formatter 脱敏；新增日志字段时仍应避免直接记录请求头或完整配置对象。

## 常见故障

### 页面能开，API 状态异常

确认后端仍在运行，检查端口 8000 和日志中的启动异常。前端开发代理不会自动启动后端。

### 管理员无法登录

- `admin_auth_not_configured`：检查密码和 token secret 是否同时配置，随后重启。
- `admin_login_failed`：检查用户名和密码是否与当前 `.env` 一致，随后确认 API 已在修改后重启。
- 登录后立即 401：可能是签名密钥已变化或 token 过期，退出后重新登录。

### 实验列表为空

检查 `BIOSAFE_EXPERIMENTS_DIR` 指向的目录是否存在。通用实验场景仍可选择，但具体实验上下文需要有效的实验配置文件。

### 语音一直显示正在连接

浏览器开发工具中确认连接地址为当前前端主机的 `/api/v1/chat/audio`。开发环境需使用当前 `vite.config.ts` 的 `ws: true` 配置，并在配置变化后重启 Vite；生产代理需转发 WebSocket upgrade。前端等待 8 秒仍未建立连接时会显示超时，不会永久停在连接状态。注意 `ASR_URI` 是 FastAPI 到 ASR 服务的第二层连接，只有录音提交后才会使用。

### 直接访问子路由 404

Vite 开发环境应自动回退。生产环境出现该问题时，在 Web 服务器配置 SPA fallback；不要把 `/api` 和 `/health` 回退到 `index.html`。
