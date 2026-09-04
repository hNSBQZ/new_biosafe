# New Biosafe

面向生物安全实验训练的网页语音助手。项目在保留指令识别、实验上下文直答、现有 LLM/ASR/TTS 服务的基础上，将文档解析、分块、向量化、关键词检索和融合排序统一交给 RAGFlow。

当前仓库处于重构启动阶段。需求边界、目标架构和可执行计划见：

- `doc/01-requirements/2026-08-27_requirement-analysis.md`
- `doc/02-architecture/2026-08-27_target-architecture.md`
- `doc/03-plans/2026-08-27_implementation-plan.md`
- `doc/00-governance/development-trace-policy.md`

旧项目 `/cache/hanqingzhe/biosafe-rag` 只作为可复用代码和服务配置的来源，不在本次重构中直接修改。

## 生产部署

仓库提供同时托管 React 页面和 API 的单容器镜像，以及带 SQLite 持久卷的 `docker-compose.yml`。生产配置差异、宿主 Nginx、首次启动、备份恢复及升级步骤见 `doc/06-operations/2026-09-04_production-docker-deployment.md`。
