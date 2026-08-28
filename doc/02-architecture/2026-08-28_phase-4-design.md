# Phase 4 设计 - 网页人工测试端

## 目标与非目标

目标是把现有 React + Vite 壳升级为可人工测试的工作台：实验选择、文本问答、录音控制、路径状态、回答引用、历史分页和纠错编辑都在第一屏和相邻视图内完成。页面只消费已存在的后端契约，文本问答使用 `POST /api/chat` SSE，历史使用 `/api/history`，实验列表使用 `/api/experiments`，录音入口连接 Phase 3 已实现的 `WS /api/v1/chat/audio`。

非目标包括知识库管理写接口、管理员鉴权、Playwright 端到端自动化、真实浏览器麦克风兼容矩阵、任何本地检索/改写/重排能力，以及在页面中展示内部 prompt 或 secret。知识库页在 Phase 4 只保留状态入口，实际 dataset/document 管理由 Phase 5 完成。

## 受影响模块

- `web/src/App.tsx`：前端状态、API client、SSE 解析、WebSocket 录音消息、引用抽屉和历史纠错。
- `web/src/styles.css`：响应式工作台布局、助手会话、历史列表、抽屉和录音状态样式。
- `web/src/App.test.tsx`：覆盖实验加载、文本问答 SSE、引用查看、历史纠错和语音控制降级状态。
- `web/eslint.config.js`：React hooks 和浏览器全局变量的独立 lint 配置。
- `doc/03-plans/2026-08-27_implementation-plan.md`：Phase 4 状态。
- `doc/04-progress/`：阶段完成或遗留记录。

## 接口、事件与数据

前端读取 `GET /api/experiments`，失败时回退到 `generic` 实验选项并显示系统状态异常。文本问答发送：

```json
{"question":"...","experiment_id":"...","session_id":"...","input_mode":"text"}
```

SSE 只解析 `data:` 行中的 QueryService envelope。`stage` 和 `stage_result` 更新路径时间线，`completed` 写入当前回答并记录 `history_id`，`failed/cancelled` 以稳定错误区展示。RAG 引用使用 `data.references` 或历史记录中的 `references` 快照，引用编号优先读取 `citation_index`。

历史视图读取 `GET /api/history?page=1&page_size=10&experiment_id=...`，选择记录后用 `PATCH /api/history/{id}/correction` 保存人工纠错。纠错只写本地历史，不触发知识库发布，也不影响后续在线回答。

录音入口使用浏览器 `MediaRecorder`。连接建立后发送 `audio_start`，录音停止时发送 `audio_data` 和 `audio_end`；若浏览器或服务不支持，显示可恢复错误。Phase 4 页面只负责控制和展示 `transcription/query_event/answer/audio_stream/error/session_complete`，不在前端模拟 ASR/TTS 成功。

## 风险、回滚与验证

风险包括 SSE 分片解析、浏览器录音格式与 ASR 期望不一致、历史记录引用字段随 RAGFlow 版本变化、移动布局中动态文本挤压工具栏。处理方式是前端使用稳定 QueryService envelope、录音错误显式展示、引用字段容错读取、固定工具栏尺寸并在桌面/移动布局下约束文本换行。

回滚 Phase 4 提交只影响 `web/` 与文档，后端 Phase 0-3 契约和 SQLite 数据不变。

验证覆盖：

- Vitest + Testing Library 覆盖实验加载、文本问答 SSE 解析、引用抽屉、历史纠错和录音入口错误。
- `npm --prefix web test -- --run`
- `npm --prefix web run build`
- 后端相关接口 smoke：`conda run -n biosafe python -m pytest tests/integration/test_chat_api.py tests/integration/test_history_api.py tests/integration/test_audio_api.py`
- `git diff --check`

仓库当前未引入 Playwright harness，因此本阶段不新增浏览器自动化脚手架；后续若需要自动化截图/关键流程检查，再放到 Phase 6 统一补齐。
