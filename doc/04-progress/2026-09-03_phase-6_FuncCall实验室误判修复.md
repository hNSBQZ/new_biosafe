# Phase 6 - FuncCall 实验室误判修复检查点

- 状态：IN_PROGRESS
- 范围：修复“进入生物安全实验室时，应当佩戴什么防护？”被误识别为 `SwitchExperimentScene` 的问题。
- 关键设计：场景切换规则改为完整输入锚定，并用 `实验(?!室)` 区分实验任务与实验室名词；不增加 LLM 分类、槽位提取或查询改写。
- 实际变更：收紧两条场景切换正则；增加“进入 PCR 实验”正例及“进入生物安全实验室”“打开实验室门”负例。
- 数据或接口兼容性：无 schema 或 API 变化；明确控制命令仍返回原有 FuncCall，知识问题继续进入 direct/RAG。
- 验证命令与真实结果：目标问题 detector 返回 `None`；“进入 PCR 实验”和“切换到 PCR 实验”返回 `SwitchExperimentScene`；相关 19 项测试通过；排除已知 TestClient portal 挂起的 admin/audio 5 项后，其余后端 55 项通过；Ruff 全量和前端 13 项测试通过；`git diff --check` 通过。
- 外部服务验证：重启 API 后用原问题请求真实 `/api/chat`，HTTP 200、终态 completed、`answer_source=rag`，历史 ID 16，返回 7 个 RAGFlow 引用，确认未再进入 instruction。后续自动修正任务为 success；独立模型因实验室等级未明确判定 `can_answer=false`，保存不可答原因和 5 条公开来源，人工纠错字段保持为空。
- 提交：`6613435 fix(chat): avoid laboratory question funcall`。
- 遗留问题：自然语言控制表达仍由保守规则识别，新增表达应同时提供正例和知识问句负例。
- 下一阶段入口：继续完成 Phase 6 浏览器验收，并根据产品需要决定是否在实验上下文明确等级时把等级信息提供给离线修正模型；不得影响在线回答路径。
