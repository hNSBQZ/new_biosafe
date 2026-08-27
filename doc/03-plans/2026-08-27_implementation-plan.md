# 分阶段实施计划

状态值：`TODO`、`IN_PROGRESS`、`DONE`、`BLOCKED`。任何时刻只允许一个阶段为 `IN_PROGRESS`。

## Phase 0 - 仓库基线与外部契约（IN_PROGRESS）

目标：建立可运行骨架和确定性契约，避免在错误的 RAGFlow/旧服务假设上开发。

- 建立 Python/React 项目、`.env.example`、配置对象、结构化日志和 `/health`。
- 从旧仓库只读提取 FuncCall、experiment prompt、LLM/ASR/TTS 最小可复用接口。
- 完成 RAGFlow 只读 client probe，保存脱敏 response fixture，确认 list/retrieve/document API 和 chunk methods。
- 建立 pytest、前端测试、lint/build 基线和 CI/本地 check 脚本。
- 写 Phase 0 实现记录并提交。

验收：后端健康测试、配置 secret 测试、前端 build、RAGFlow list datasets live smoke 通过；无 secret 入库。

建议提交：`chore: bootstrap biosafe web assistant`、`feat(ragflow): add versioned API adapter contract`。

## Phase 1 - SQLite 与 Excel 种子（TODO）

- 实现单库迁移、`chat_history`、`admin_user`、`experiment_dataset_binding` repository。
- 实现幂等 Excel 导入及 84 行映射校验，输出统计但不打印完整敏感内容。
- 实现历史分页、详情和纠错 repository/API 测试。
- 写 Phase 1 实现记录并提交。

验收：空库启动、迁移重跑、Excel 连续导入两次、并发写入和损坏 JSON 容错测试通过。

建议提交：`feat(history): add simple sqlite history store and seed importer`。

## Phase 2 - 简化文本查询链路（TODO）

- 移植并测试 FuncCall detector 与实验提示词存储。
- 实现严格 direct/NEED_RAG 决定，不引入槽位、名录或改写。
- 实现 RAGFlow 原始问题检索和 chunk normalization。
- 实现带编号引用的答案合成、引用校验、空召回/超时语义。
- 实现 SSE API 和统一历史落库，覆盖 instruction/direct/rag/error/cancelled。
- 写 Phase 2 实现记录并提交。

验收：三条路径单测与集成测试通过；断言 RAGFlow 请求问题等于原始问题；引用编号均能反查 chunk。

建议提交：`feat(chat): implement instruction direct and ragflow query paths`。

## Phase 3 - 实时语音链路（TODO）

- 移植 ASR、TTS client 和必要的文本规范化/有序发送逻辑。
- WebSocket 编排复用 QueryService；实现会话状态、取消、超时、重录和 TTS 失败文本保留。
- 固定音频格式/采样率协议并提供浏览器兼容路径。
- 写 contract/integration tests 和 Phase 3 记录并提交。

验收：录制样例完成 ASR -> direct/RAG -> TTS；中断与各服务失败用例不会产生悬挂任务。

建议提交：`feat(voice): add browser audio conversation pipeline`。

## Phase 4 - 网页人工测试端（TODO）

- React + Vite 实现助手第一屏：实验选择、文本、录音、会话、状态和错误恢复。
- 引用使用答案内编号、来源列表和详情抽屉，展示文档、页码/位置、片段、分数与原文入口。
- 实现历史分页、引用查看和纠错编辑。
- 做桌面/移动响应式、无障碍和 Playwright 截图/关键流程检查。
- 写 Phase 4 记录并提交。

验收：人工测试常用流程无需开发工具；动态内容不重排工具栏、不重叠；刷新后历史可查。

建议提交：`feat(web): build text voice history and citation workspace`。

## Phase 5 - RAGFlow 知识库管理（TODO）

- 后端实现 dataset/document/parse/retry/delete/retrieval preview adapter 与管理员鉴权。
- 网页实现解析模板、数据集和文档状态、上传、轮询、失败重试、确认删除、检索预览。
- live 测试只操作 `biosafe-dev-` 资源，验证异步解析真实状态；不实现本地文档解析。
- 写 Phase 5 记录并提交。

验收：至少用一个小 fixture 完成开发数据集创建 -> 上传 -> 解析 -> 检索预览 -> 删除；非 owned 资源删除被拒绝。

建议提交：`feat(admin): manage ragflow datasets and documents`。

## Phase 6 - 集成、部署与最终验收（TODO）

- 整理 requirements、前端 lockfile、Docker Compose、健康检查和运行文档。
- 校验从旧 `.env` 复用服务配置但不复制 secret；补齐管理员初始化和 token 生命周期。
- 运行后端全量测试、前端测试/build、RAGFlow live smoke、文本/语音/管理 Playwright E2E。
- 检查 Git 历史和工作树没有 secret、数据库、日志或大产物。
- 写最终测试报告、运维文档和 Phase 6 记录并提交。

验收：按文档可从干净环境启动，核心验收标准全部有真实证据；未通过项不得标 DONE。

建议提交：`chore: add deployment and end-to-end verification`、`docs: record final acceptance results`。

## 自动执行规则

- 按 Phase 0 到 Phase 6 顺序连续执行，不为非阻塞的小选择暂停。
- 每完成一个验收门槛立即更新状态、写进度文档并提交，不等到最后统一处理。
- 遇到 RAGFlow/ASR/TTS 临时不可用，先完成 mock contract 和其他不依赖工作，再重试 live smoke；真实外部验证未通过时阶段不能标 DONE。
- 不修改旧仓库，不提交 demand/Excel/.env，不操作非 `biosafe-dev-` 远端资源。

