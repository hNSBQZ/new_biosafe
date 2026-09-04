# Phase 6 设计 - RAGFlow 文档名称过滤兼容

## 目标与非目标

修复知识库文件中心选择文件后的同名预检查失败。当前 RAGFlow 实例的文档列表接口使用
`keywords` 过滤文件名；传入 `name` 时会把文件名进入文档归属校验，并以 HTTP 200、业务码
102 返回 `you don't own the document`。RAGFlow adapter 应继续向应用提供稳定的 `name`
语义，但在外部请求中将其映射为 `keywords`。

本工作段不改变前端文件中心 API、跨类别同名规则、上传和解析流程，不新增本地文档元数据，
也不操作远端文档或数据集。

## 受影响模块

- `biosafe/integrations/ragflow/client.py`：把 `list_documents(name=...)` 映射到 RAGFlow
  支持的 `keywords` 查询参数；显式 `keywords` 保持优先。
- `tests/contract/test_ragflow_client.py`：固定 adapter 的外部请求参数。
- `tests/integration/test_admin_api.py`：覆盖文件中心按名称查询及同名预检查所依赖的 API 路径。

## API 与数据变化

对内 Python 接口和 HTTP API 均保持兼容：`GET /api/admin/knowledge/files?name=...` 仍按文件名
筛选，`RAGFlowClient.list_documents(..., name=...)` 调用方式不变。仅外部 RAGFlow 请求由
`name=<文件名>` 改为 `keywords=<文件名>`，响应仍经过现有本地大小写不敏感过滤。

无 SQLite schema 或数据迁移，无远端写操作。

## 风险与回滚

- `keywords` 可能采用模糊匹配，因此服务端继续执行 `_matches_file_filters`，避免把不相关结果
  当作同名文件。
- 同时传入 `keywords` 与 `name` 时优先使用显式 `keywords`，避免重复查询参数和语义冲突。
- 回滚时恢复 adapter 原参数映射即可；HTTP API 和数据库均无需回滚。

## 验证

```bash
conda run -n biosafe python -m pytest tests/contract/test_ragflow_client.py tests/integration/test_admin_api.py -q
conda run -n biosafe python -m ruff check biosafe services tests
```

真实实例使用两个现有 `biosafe-dev-` 数据集执行只读文档名称查询，确认 `keywords` 返回
业务码 0；随后重启本地 API，通过前端代理验证同名检查不再返回 `ragflow_api_error`。
