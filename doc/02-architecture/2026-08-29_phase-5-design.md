# Phase 5 设计 - RAGFlow 知识库管理

## 目标与非目标

目标是把 RAGFlow 作为唯一知识库事实源，补齐管理员登录、数据集和文档管理、解析/重试/取消、删除确认和检索预览，并把管理入口嵌到现有系统页里。管理写操作只允许 `biosafe-dev-` 命名空间，避免误删或误改非本任务资源。

非目标包括本地文档解析、RAGFlow 元数据镜像表、历史纠错发布到知识库、非 dev 命名空间的通用管理面，以及新的检索算法。

## 受影响模块

- `biosafe/auth.py`：管理员密码哈希与签名 token。
- `services/api/routes/admin.py`：登录、数据集、文档、解析、删除和检索预览。
- `services/api/schemas.py`：管理接口请求/响应 schema。
- `biosafe/storage/admin_repository.py`、`services/api/app.py`：管理员初始化与依赖注入。
- `web/src/KnowledgeAdminPanel.tsx`、`web/src/App.tsx`、`web/src/styles.css`：系统页内管理 UI。
- `scripts/ragflow_admin_smoke.py`：真实 RAGFlow live smoke。
- `tests/integration/test_admin_api.py`、`tests/unit/test_auth.py`：鉴权与契约测试。

## 接口、事件与数据

管理入口使用 `POST /api/admin/login` 颁发 HMAC 签名 bearer token。管理页调用：

- `GET /api/admin/knowledge/datasets`
- `POST /api/admin/knowledge/datasets`
- `GET /api/admin/knowledge/datasets/{id}/documents`
- `POST /api/admin/knowledge/datasets/{id}/documents`
- `POST /api/admin/knowledge/datasets/{id}/documents/{document_id}/parse`
- `POST /api/admin/knowledge/datasets/{id}/documents/{document_id}/retry`
- `POST /api/admin/knowledge/datasets/{id}/documents/{document_id}/cancel`
- `DELETE /api/admin/knowledge/datasets/{id}/documents/{document_id}`
- `DELETE /api/admin/knowledge/datasets/{id}`
- `POST /api/admin/knowledge/retrieval-preview`

`list_datasets` 只展示 `biosafe-dev-` 命名空间；所有数据集写操作和文档写操作都会先确认 dataset 属于该命名空间。`retrieval-preview` 只接受已确认的 dev dataset IDs。前端 token 存本地 `localStorage`，服务端只落地签名 token，不记录原始 secret。

## 风险、回滚与验证

风险包括管理页误暴露非 dev 数据集、上传时临时文件未清理、远端 RAGFlow 状态变化慢于前端轮询、以及 token 误打印到日志。处理方式是 namespace 过滤、显式 temp 文件清理、状态轮询和日志脱敏。

回滚 Phase 5 提交只影响管理鉴权、管理 UI 与 smoke 脚本，不改已有文本问答和语音链路。

验证覆盖：

- `conda run -n biosafe python -m ruff check biosafe services scripts tests`
- `conda run -n biosafe python -m pytest tests/unit/test_auth.py tests/integration/test_admin_api.py tests/contract/test_ragflow_client.py`
- `npm --prefix web test -- --run`
- `npm --prefix web run build`
- `conda run -n biosafe python scripts/ragflow_admin_smoke.py`
