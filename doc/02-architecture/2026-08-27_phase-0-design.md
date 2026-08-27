# Phase 0 设计 - 仓库基线与外部契约

## 目标与非目标

目标是建立 Python/React 工程、环境配置、脱敏日志、健康 API、RAGFlow 只读 adapter 与确定性测试。非目标是数据库、问答编排、语音会话和知识库写操作。

## 受影响模块

- `biosafe/config.py`：仅从环境变量构造不可变配置。
- `biosafe/logging.py`：JSON 日志及 credential 脱敏。
- `biosafe/integrations/ragflow/`：远端字段归一化。
- `services/api/app.py`：应用工厂与 `/health`。
- `web/`：Vite/React 测试与构建基线。

## 接口与数据

`GET /health` 返回稳定的服务状态与版本。RAGFlow adapter 提供 `health/list_datasets/list_documents/retrieve`，内部模型保存业务元数据但不保存鉴权信息。本阶段无持久化数据变化。

## 风险、回滚与验证

风险是 RAGFlow 实例版本字段差异，通过脱敏 fixture 和 live 只读 probe 验证。阶段提交可整体回滚，不影响远端和本地业务数据。

验证命令：

```bash
conda run -n biosafe python -m pytest tests/unit tests/contract tests/integration/test_health.py
conda run -n biosafe python -m ruff check biosafe services scripts tests
npm --prefix web test -- --run
npm --prefix web run build
```
