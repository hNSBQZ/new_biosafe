# Phase 6 - 模型统一决策 FuncCall 检查点

- 状态：IN_PROGRESS
- 范围：将既有四个 FuncCall 纳入第一轮实验上下文 LLM 的 `func_call/direct/need_rag` 三路决定，删除在线本地正则 detector。
- 关键设计：只使用现有一次模型请求；FuncCall 必须是严格 JSON、命令位于四项白名单、confidence 不低于 0.8 且 `params={}`，否则按 `need_rag` 使用原始问题检索。保留既有 API、SSE/WebSocket stage、历史和空参数契约。
- 实际变更：扩展实验提示词的三路输出契约、四项命令说明和知识问句反例；QueryService 在 direct decision 后处理合法 FuncCall；删除 `funcall_detector.py` 及其规则测试，新增模型 FuncCall、知识问句、未知命令和非空参数回归测试。
- 数据或接口兼容性：无 schema 变化；合法 FuncCall 的 completed 事件与历史 `answer_source=instruction` 不变。模型不可用或结构无效时沿用原有 RAG 降级。
- 验证命令与真实结果：相关后端 21 项通过；完整可执行后端 50 项、Ruff 全量、前端 13 项和 production build 通过；`git diff --check` 通过。
- 外部服务验证：当前 CHAT 模型真实判断中，“现在第几步了”“这一步怎么操作”“这个设备叫什么”“切换实验场景”分别返回四个既有白名单命令且参数均为空；“进入生物安全实验室时，应当佩戴什么防护？”返回 `need_rag`。重启 API 后再次请求真实 `/api/chat`：历史 17 返回 instruction / ShowProcedurePanel / 空参数，历史 18 返回 rag。
- 提交：`d278d67 feat(chat): let model decide funcalls`。
- 遗留问题：指令现在依赖 CHAT 模型可用性和单次推理延迟；模型不可用时按既定策略进入 RAG。admin/audio 的既有 TestClient portal 挂起问题未在本检查点处理。
- 下一阶段入口：从网页继续 Phase 6 其余浏览器验收。
