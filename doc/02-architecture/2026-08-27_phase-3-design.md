# Phase 3 设计 - 实时语音链路

## 目标与非目标

目标是实现浏览器音频 WebSocket：接收一轮音频，调用 ASR 得到原始问题，复用 `QueryService.answer_text()` 完成 instruction/direct/RAG 三条文本路径，再对可朗读文本调用 TTS 并把音频分片回传。ASR 失败、取消、超时和 TTS 失败都必须有稳定消息语义；TTS 失败不能影响文本回答和历史落库。

非目标包括前端录音 UI、流式 LLM token 级 TTS、历史问答短路、查询改写、名录预查、本地检索或任何新的知识处理能力。语音链路只改变输入输出介质，不改变在线问答产品边界。

## 受影响模块

- `biosafe/integrations/asr/`：FunASR WebSocket adapter，内存音频输入，不落盘。
- `biosafe/integrations/tts/`：HTTP TTS adapter，并发、重试和文本归一化。
- `services/audio/`：单轮音频会话、句子切分、有序音频发送和 QueryService 事件适配。
- `services/api/routes/audio.py`：WebSocket 协议转换。
- `services/api/app.py`、`services/api/deps.py`：初始化并注入语音编排器。
- `tests/unit`、`tests/integration`：mock ASR/TTS 和 ASGI WebSocket 测试。

## 接口、事件与数据

WebSocket 路径为 `WS /api/v1/chat/audio?experiment_id=...`，兼容旧测试端的单轮消息：

- 客户端发送 `audio_start`，字段 `sample_rate` 默认 `16000`、`format` 默认 `pcm`。
- 客户端发送多个 `audio_data`，字段 `data` 为 base64 音频，`seq` 原样确认。
- 客户端发送 `audio_end` 后服务端进入 ASR -> QueryService -> TTS。
- 客户端可发送 `interrupt`，服务端停止后续问答/TTS，已进入 QueryService 时通过 `cancel_requested` 标记为 cancelled。

服务端消息保持 JSON：

- `connected`：连接确认，包含 `session_id`、`experiment_id` 和音频协议参数。
- `packet_ack`：确认收到音频包。
- `status`：阶段提示，`phase` 包括 `recording_started/asr_started/query_started/tts_started` 等。
- `transcription`：ASR 结果，包含 `success/text/duration_ms`。
- `query_event`：原样转发 QueryService envelope，便于前端和测试观察 answer_source、引用与历史 ID。
- `instruction`：instruction 终态的便捷消息，包含 FuncCall 字段。
- `answer`：direct/RAG 文本终态，包含 `answer_source/answer/references/history_id`。
- `audio_stream`：`event=data` 时携带 base64 音频、文本段和 `sequence`；`event=finished` 时携带完整文本、引用和 `tts_success`。
- `error`：稳定 `code/message`，不包含外部 token 或完整内部异常。
- `session_complete`：单轮终态，`reason` 为 `done/error/interrupted`。

历史仍只由 `QueryService` 写入 `chat_history`，`input_mode` 固定为 `voice`。语音层不新增 SQLite 表，不复制 ASR/TTS 原始响应。

## 风险、回滚与验证

风险包括 ASR 协议字段差异、TTS 服务偶发失败、浏览器中断导致悬挂任务和 base64 输入异常。处理方式是 adapter 隔离外部字段、TTS 失败降级为仅文本、`interrupt` 贯穿 cancel checker、非法音频包返回错误并结束会话。

回滚 Phase 3 提交后，Phase 0-2 文本链路和数据库 schema 不受影响。

验证覆盖：

- ASR adapter 空音频、未配置、正常转写、超时/异常映射。
- TTS adapter 文本为空、未配置、HTTP 成功、HTTP 失败和重试。
- 音频编排 instruction/direct/RAG、ASR 空结果、TTS 失败文本保留和中断取消。
- WebSocket 集成测试覆盖 `audio_start/audio_data/audio_end`、包确认、转写、QueryService 事件、TTS 音频分片和终态。
