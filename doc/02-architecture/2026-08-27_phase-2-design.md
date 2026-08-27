# Phase 2 设计 - 简化文本查询链路

## 目标与非目标

目标是实现 FuncCall、实验上下文 direct、原始问题 RAG 三条路径及失败/取消持久化。非目标包括历史匹配、名录预查、槽位补全、角色分类、查询改写以及任何本地检索或重排。

## 受影响模块

- `biosafe/application/query_service.py`：唯一问答状态机。
- `biosafe/integrations/llm/`：OpenAI 兼容模型与严格 JSON 决策。
- `biosafe/domain/query.py`：稳定事件 envelope 和结果模型。
- `services/api/routes/chat.py`：只做 SSE 协议转换。

## 接口、事件与数据

`POST /api/chat` 接收 `question, experiment_id, session_id`，返回 `text/event-stream`。事件固定为 `event, request_id, sequence, stage, data, timestamp`。终态事件只在历史写入后发送。

第一轮 LLM 只接受 JSON：`{"decision":"direct","answer":"..."}` 或 `{"decision":"need_rag"}`。解析失败、超时或非 direct 一律进入 RAG。RAGFlow 入参断言为原始问题和实验显式绑定 dataset IDs。合成答案的 `[n]` 必须落在 chunk 数量内；无引用或越界视为合成失败。

## 风险、回滚与验证

风险是模型格式漂移和引用幻觉；通过严格解析、默认 RAG、引用编号反查和明确错误码控制。取消检查位于每个外部调用前后。阶段提交回滚后数据库已有历史仍兼容。

验证覆盖 instruction/direct/rag/empty/timeout/synthesis failure/cancelled，且 contract 断言检索问题未经改写。
