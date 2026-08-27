# ADR 0001 - RAGFlow 适配器边界

- 状态：Accepted
- 日期：2026-08-27

## 决策

业务层只使用归一化的 `Dataset`、`Document`、`RetrievedChunk`。RAGFlow REST 路径、响应字段差异和错误码只存在于 adapter。检索入参必须是原始问题与显式 dataset IDs。

adapter 的 `raw_metadata` 保留远端业务字段快照，但不保存请求头、API key 或 HTTP 客户端对象。自动重试仅用于后续确认安全的幂等操作。

## 理由

RAGFlow 版本字段存在差异，且它是知识库事实来源。稳定内部模型可避免远端字段扩散，同时不在 SQLite 建立文档镜像。

## 后果

新增或变更远端 API 时先更新 contract fixture 与 adapter。管理写操作必须额外检查 `biosafe-dev-` 所有权，不能通过通用 `_request` 绕开。
