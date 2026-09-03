# 目标架构

## 总体数据流

```text
React Web（文本、录音、历史、知识管理）
            |
            v
FastAPI（HTTP/SSE/WebSocket、鉴权、校验）
            |
            v
QueryService
  |-- ExperimentPromptStore -> LLM FuncCall/direct/RAG decision
  |-- RAGFlowClient -> retrieval only
  |-- AnswerSynthesizer -> LLM + citation markers
  `-- HistoryRepository -> one SQLite database

AnswerCorrectionDispatcher -> bounded async queue -> independent LLM + web search
                           `-> correction audit in the same SQLite database

VoiceSession: browser audio -> existing ASR -> QueryService -> existing TTS -> browser
KnowledgeAdminService -> RAGFlow datasets/documents/parsing status
```

## 目录建议

```text
biosafe/
  config.py
  domain/
  application/
  integrations/{llm,ragflow,asr,tts}/
  storage/
services/
  api/{app,deps,schemas,routes}/
  audio/
web/
tests/{unit,contract,integration,e2e}/
scripts/
doc/
```

## 查询状态机

1. `received`：校验问题和实验 ID。
2. `direct_decision`：实验提示词 + 原始问题交给 LLM，响应只能是白名单 FuncCall、direct answer 或 NEED_RAG；FuncCall 参数保持为空。
3. `instruction`：模型决定为合法 FuncCall 时返回命令并记历史。
4. `retrieving`：只把原始问题、选择的数据集 ID 和可配置检索参数交给 RAGFlow。
5. `synthesizing`：把归一化 chunks 交给 LLM，要求使用 `[1]` 形式引用且禁止编造来源。
6. `completed/failed/cancelled`：先完成数据库记录，再发送终态事件。

服务端事件使用稳定 envelope：`event, request_id, sequence, stage, data, timestamp`。网页和语音共享同一 QueryService，不复制问答逻辑。

## RAGFlow adapter

adapter 隔离实际 REST 字段，内部至少提供：

- `health()`
- `list_datasets()` / `create_dataset()` / `delete_owned_dataset()`
- `list_documents()` / `upload_document()` / `start_parse()` / `cancel_parse()` / `delete_owned_document()`
- `retrieve(question, dataset_ids, options)`

归一化 chunk：

```text
chunk_id, dataset_id, dataset_name,
document_id, document_name, content,
page_numbers, positions, image_id,
similarity, vector_similarity, term_similarity,
source_url, raw_metadata
```

`raw_metadata` 作为 JSON 快照用于兼容实例差异，但 API 响应和数据库不保存授权头。重试只用于幂等 GET 和可安全重试操作；上传/创建使用调用方 idempotency key 或先确认远端状态。

## 知识库设计

首批提供五个可创建模板：法规标准 (`laws`)、SOP/设备手册 (`manual`)、名录表格 (`table`)、论文报告 (`paper`)、通用资料 (`naive`)。审核问答 (`qa`) 只作为未来显式人工发布选项，不连接历史纠错流程。

检索范围由实验配置映射到 dataset IDs；没有映射时使用显式默认集合，不能自动搜索租户全部数据集。映射存本地简单配置/表，RAGFlow 保存数据集和文档真状态。

## SQLite

只使用一个业务数据库。初始表保持扁平、无外键：

### `chat_history`

`id, request_id(unique), session_id, created_at, experiment_id, input_mode, question, answer_source, system_answer, corrected_answer, references_json, ragflow_request_json, latency_json, status, error_code, error_message, seed_fingerprint(unique nullable)`

### `admin_user`

`id, username(unique), password_hash, role, enabled, created_at, updated_at`

### `experiment_dataset_binding`

`id, experiment_id, dataset_id, dataset_name_snapshot, enabled, created_at, updated_at`

### `answer_correction`

`id, history_id(unique logical link), question, original_answer, status, model, can_answer, answer, cannot_answer_reason, citations_json, error, enqueued_at, started_at, finished_at`

模型修正只保存独立回答和公开来源供展示、审计及人工采纳，不更新 `chat_history.corrected_answer`，不发布到 RAGFlow，也不参与 QueryService 的在线回答。

不保存 RAGFlow 文档镜像表。知识管理页面实时读 RAGFlow；必要的异步轮询状态在进程内或短期 cache，不制造第二事实源。

SQLite 迁移使用递增版本和 `schema_migration`，每次迁移可重复执行。JSON 字段写入前做 schema 校验，读取旧数据失败时返回空值并记录错误而不是让列表崩溃。

## API 边界

- `POST /api/chat`：SSE 文本问答。
- `WS /api/v1/chat/audio`：语音会话，复用旧协议时保留兼容说明。
- `GET /api/experiments`：实验和绑定数据集。
- `GET /api/history`、`GET /api/history/{id}`、`PATCH /api/history/{id}/correction`。
- `POST /api/history/{id}/auto-correction`：为旧记录或失败任务重新提交异步模型修正。
- `POST /api/admin/login`。
- `GET/POST /api/admin/knowledge/datasets`。
- `GET/POST/DELETE /api/admin/knowledge/datasets/{id}/documents...`。
- `POST /api/admin/knowledge/retrieval-preview`。

所有请求/响应先定义 Pydantic schema；管理写接口需要 Bearer token；外部异常映射成稳定 `code`，细节只进脱敏日志。

## 前端视图

- 助手：实验选择、消息流、录音控制、回答路径状态、内联引用和引用详情抽屉。
- 历史：筛选/分页，原始问题、系统回答、模型修正及公开来源、人工纠错、RAGFlow 引用快照，支持重新修正和保存人工纠错。
- 知识库：数据集模板、文档上传、解析进度、失败重试、删除确认、检索预览。
- 系统状态：后端、RAGFlow、ASR、TTS 健康状态，不能显示 secret 或完整内部异常。

## 可观测与失败策略

- 所有链路贯穿 `request_id/session_id`，记录各阶段耗时和回答来源。
- RAGFlow 超时/空召回返回可识别错误，不降级为无依据答案。
- ASR 或 TTS 失败不丢失文本问答：ASR 失败可重录，TTS 失败仍保留文本。
- 前端取消时服务端停止后续合成/TTS并把记录标为 cancelled。
- 日志 JSON 化并脱敏；健康接口不执行破坏性探测。
