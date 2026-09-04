# 自动开发任务

在 `/cache/hanqingzhe/new_biosafe` 完整实现生物安全网页语音助手重构。

开始时完整阅读 `AGENTS.md`、`doc/README.md`、需求分析、目标架构和实施计划。旧仓库 `/cache/hanqingzhe/biosafe-rag` 仅作只读参考；使用 conda 环境 `biosafe`。从 Phase 0 开始，严格按 `doc/03-plans/2026-08-27_implementation-plan.md` 顺序持续推进到 Phase 6，逐阶段更新状态、记录设计/实现/真实验证结果并按功能提交。

你拥有本机开发所需权限，但权限不扩大产品范围：不得修改旧仓库，不得泄露或提交密钥，不得删除/覆盖非本任务创建的 RAGFlow 资源。RAGFlow live 测试只能操作 `biosafe-dev-` 前缀资源。`demand.txt` 中 token 跨行，读取时必须去除说明文字且不可打印；当前仓库本地 `.env` 是现行服务配置来源且不可提交。

自行解决实现细节并持续工作，不要因为可合理判断的小问题停止。外部服务临时失败时继续做 mock contract、单元测试和其他阶段工作并稍后重试。只有会改变产品边界的缺失决定、连续无法恢复的外部阻塞或需要破坏性操作时才停止，并在计划与进度文档中记录证据。

完成条件不是“代码已写”，而是 Phase 0-6 的代码、测试、文档留痕、独立提交和最终验收全部完成。结束前再次执行 secret scan、`git status`、后端全量测试、前端测试/build 和可执行的 live/E2E smoke，并把真实结果写入最终报告。
