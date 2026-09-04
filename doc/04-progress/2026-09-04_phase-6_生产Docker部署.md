# Phase 6 工作段 - 生产 Docker 部署

> 本记录描述首次实现及其当时的真实验证结果。该版内置前端的部署拓扑已被同日“生产前后端分离部署修订”取代，保留本文件用于开发留痕。

- 状态：DONE
- 范围：为 Git 传输到生产机后的单容器部署提供 Dockerfile、Compose、无密钥生产配置模板、宿主 Nginx 说明和 SQLite 持久化/备份恢复流程。
- 关键设计：Node 多阶段只负责构建 React，最终 Python 3.12 slim 镜像中由单 worker FastAPI 同时提供 SPA、HTTP/SSE API 和 WebSocket；Compose 只映射一个宿主端口，不运行 Nginx 容器；宿主 Nginx 自行负责 HTTPS 和反向代理。
- 实际变更：初版新增 Dockerfile、Compose、生产配置模板和空实验目录，并让 FastAPI 提供静态资源和 SPA fallback；该拓扑及额外部署变量随后均已由前后端分离和环境变量收敛工作段替代。
- 数据或接口兼容性：无 SQLite schema 变更，无业务 API 变更。数据库位于命名卷的 `/app/data/biosafe.db`，WAL/SHM 与主文件同卷；当前 Compose 直接加载仓库根 `.env`。
- 验证命令与真实结果：`docker compose ... config --quiet` 通过；使用 DaoCloud 基础镜像代理、阿里 PyPI 和 npmmirror 仅作本机构建参数覆盖，`new-biosafe:latest` 单镜像构建成功，约 197 MB；隔离 Compose 容器 health 通过，运行用户为 `biosafe`、根文件系统只读；`/`、`/admin/history`、`/health`、未知 API JSON 404 和 `/api/v1/chat/audio` WebSocket 全部通过映射端口。
- 持久化验证：在本任务创建的隔离测试卷写入 `single-container-persistence` 记录，执行 `docker compose up -d --force-recreate biosafe` 后查询数量仍为 1，前端子路由仍可访问。验证结束后已删除测试容器、网络和仅本任务创建的测试卷。
- 其他验证：`conda run --no-capture-output -n biosafe python -m pytest -q` 通过，65 项全部通过；Ruff 通过；前端 15 项测试、ESLint 和 production build 通过；镜像检查确认包含 `/app/web/dist/index.html`、不包含 `.env` 和预生成数据库；`git diff --check` 通过。
- 外部服务验证：本工作段只验证容器与本地持久化，未向 RAGFlow、LLM、ASR 或 TTS 发起业务请求，未修改远程资源。Docker Hub 在当前机器首次构建时鉴权超时，故使用可配置 build args 完成镜像代理验证；生产环境应指向其可访问的镜像/依赖源。
- 提交：`78d04ea chore: add single-container production deployment`
- 遗留问题：不在开发机保持或运行部署容器；生产 `.env`、基础镜像名、真实端口、宿主 Nginx 域名/证书和外部服务连通性由生产机调试确认。
- 下一阶段入口：在生产机按 `doc/06-operations/2026-09-04_production-docker-deployment.md` 配置外置 env，构建单镜像，接入宿主 Nginx/HTTPS，然后执行文本、语音和管理端真实验收。
