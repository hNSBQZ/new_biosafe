# RAGFlow 与 LLM 密集引用 smoke

- 日期：2026-09-02
- 范围：验证原始问题检索、句级引用、RAGFlow 文档名归一化和引用快照。
- 资源边界：只读检索已有配置 dataset；未创建、修改或删除 RAGFlow 资源。

## 请求

通过本机 `POST /api/chat` 提交一个包含多个处置步骤的问题，使用 `generic` 实验上下文。请求未携带查询改写、名录预查或本地检索结果。

## 真实结果

- 第一轮 LLM 返回 `need_rag`。
- QueryService 将用户原始问题和已绑定 dataset ID 交给 RAGFlow。
- RAGFlow 返回 8 个 chunk，随后由现有 LLM 基于这些片段合成回答。
- 最终回答为 RAG 路径，共 18 个可核查完整句，每句均在句末包含有效 `[n]` 引用。
- 返回 6 个实际被引用的 chunk 快照，编号均在本次 8 个 chunk 范围内。
- 文档名成功从 RAGFlow 的 `document_keyword` 字段归一化，实际包含：
  - `病原微生物实验室生物安全管理条例.html`
  - `GB_19489-2007.pdf`
- 前端可使用 `citation_index` 把内联标号映射到文档名和引用详情。

## 自动化结果

```text
Python unit: 35 passed
Python contract: 4 passed
Python targeted query/RAGFlow/audio: 18 passed
Frontend Vitest: 11 passed
Frontend lint: passed
Frontend production build: passed
Ruff: passed
git diff --check: passed
```

`tests/integration/test_chat_api.py`、`test_health.py` 和 `test_history_api.py` 分文件通过。`test_admin_api.py` 与 `test_audio_api.py` 在当前环境进入 FastAPI `TestClient` 生命周期时持续等待，人工中止后无失败断言；本次没有把它们记录为通过。仓库未安装本地 Playwright，因此本检查点未新增 Playwright 截图结果。

## 2026-09-03 引用覆盖回归

草稿日志证明“什么是生物安全？”的 9 条具体资料内容均有有效引用，原失败只来自标题和两句资料不足说明。句级覆盖策略调整为：至少一个引用和编号范围继续硬校验；标题、过渡语和资料不足说明豁免；其他漏标句修复一次，残留漏标只记录 warning。

使用同一问题真实复验：

- 第一轮 LLM 返回 `need_rag`，RAGFlow 返回 8 个 chunk。
- 只调用一次回答合成 LLM，没有触发引用修复。
- 请求以 `completed` 结束，答案 774 字，返回 4 个引用快照，文档名均可展示。
- `synthesis_ms` 为约 6000 ms，未再出现 `rag_citation_incomplete`。
- 回归后完整 Ruff、47 项相关 Python 测试、前端 lint、11 项测试和 build 通过。
