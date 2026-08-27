# Agent 开发规范

## 开工顺序

1. 先读根目录 `readme.md`。
2. 再读 `doc/README.md`、需求分析、目标架构和当前实施计划。
3. 执行 `git status --short --branch`，保护已有改动。
4. 只在 `/cache/hanqingzhe/new_biosafe` 开发。旧仓库 `/cache/hanqingzhe/biosafe-rag` 只读参考，不得修改。
5. Python 命令优先使用 `conda run -n biosafe ...`。

## 不可偏离的产品边界

在线问答只有四条结果路径：

```text
用户问题
  -> 指令识别命中：返回 FuncCall
  -> 否则携带实验上下文请求 LLM
       -> 能回答：直接回答
       -> 不能回答：把原始问题直接交给 RAGFlow 检索
            -> 现有 LLM 基于 RAGFlow 片段生成答案和可核查引用
```

- 不实现历史问答前匹配或历史答案短路。
- 不实现名录预查、槽位补全、查询改写、角色分类、本地 embedding、本地 BM25、RRF 或重排序。
- 文档解析、分块、embedding、关键词检索和融合排序由 RAGFlow 负责。
- 纠错答案只供展示和审计，未经明确人工发布动作不得进入知识库，也不得影响在线回答。
- RAGFlow 是知识库和文档状态的事实来源，本地数据库不复制整套 RAGFlow 元数据。

## 代码边界

- `biosafe/`：配置、领域模型、查询编排、SQLite repository、外部服务客户端。
- `services/`：FastAPI、SSE/WebSocket、鉴权和依赖注入；路由只做协议转换。
- `web/`：React + Vite 网页测试端和管理端。
- `scripts/`：种子导入、开发检查和运维脚本。
- `tests/`：unit、contract、integration、e2e 分层测试。
- 不从旧仓库整目录复制；只复制确认需要的 FuncCall、实验上下文、LLM、ASR、TTS 代码，并同步裁掉旧依赖。

## 配置与安全

- 所有服务地址、模型名、账号和密钥只从环境变量进入配置对象。
- RAGFlow 使用 `RAGFLOW_BASE_URL`、`RAGFLOW_API_KEY`，禁止把 token 写入代码、文档、提交、测试输出或日志。
- `demand.txt` 含实时 token，保持 Git 忽略；日志中对 `Authorization`、API key 和密码脱敏。
- 自动化验证只创建 `biosafe-dev-` 前缀的 RAGFlow 数据集。不得删除、重命名或覆盖非本任务创建的远端资源。
- `.env.example` 只放占位符。可读取旧仓库 `.env` 供本机运行，但不得复制进 Git。

## 数据规范

- SQLite 采用简单表和 JSON 快照，不建立跨服务外键。
- 一条历史记录至少保存：原始问题、系统答案、纠错答案、回答路径、实验 ID、RAGFlow 引用快照、时间和错误状态。
- 引用快照必须保留 RAGFlow 的 dataset/document/chunk 标识、文档名、片段文本、页码或位置、各类相似度（实例返回时）和可访问链接（可生成时）。
- Excel 种子映射固定为：`question -> question`、`original_answer -> system_answer`、`answer -> corrected_answer`、`references -> references_json`、`timestamp -> created_at`。
- 种子导入必须幂等；不得自动把 Excel 中的纠错答案发布到 RAGFlow。

## RAGFlow 知识库规则

一个 RAGFlow dataset 只有一种主要解析策略，因此按解析方式和业务边界建库，而不是给每个文件建库。首批模板：

| 模板 | RAGFlow chunk method | 用途 |
| :--- | :--- | :--- |
| 法规标准 | `laws` | 法律、条例、国家/行业标准 |
| SOP 与设备手册 | `manual` | 实验流程、操作规程、设备说明 |
| 名录与表格 | `table` | 病原体名录、清单、台账、结构化表格 |
| 论文与报告 | `paper` | 论文、研究报告、技术报告 |
| 通用资料 | `naive` | 不属于上述类型的普通文档 |
| 审核问答 | `qa` | 仅人工明确发布的问答材料，默认不创建/不检索 |

运行时应从当前 RAGFlow 实例验证支持的 method。图片、演示文稿、音频等内置解析方式按需扩展，不为没有文件的类别预建空库。

## 文档留痕与计划状态

- 遵守 `doc/00-governance/development-trace-policy.md`。
- 每阶段开始前创建或更新设计记录，写清范围、接口、数据变化和测试方法。
- 实现过程中持续更新 `doc/03-plans/2026-08-27_implementation-plan.md` 的状态，不能等到最后一次性勾选。
- 每阶段结束在 `doc/04-progress/` 新增实现记录，包含提交、变更、验证结果、遗留问题和下一阶段入口。
- 架构决策写入 `doc/02-architecture/adr/`，不要只留在聊天或提交信息里。

## 提交和验证

- 按可独立验证的功能提交，禁止把所有阶段压成一个大提交。
- 推荐提交前缀：`chore:`、`feat(config):`、`feat(ragflow):`、`feat(chat):`、`feat(history):`、`feat(voice):`、`feat(web):`、`feat(admin):`、`test:`、`docs:`。
- 提交前检查 staged diff，确保没有 `.env`、token、数据库、日志、大产物和旧仓库文件。
- Python 至少运行相关 `pytest`、语法/静态检查；前端至少运行单元测试和 `npm run build`；跨服务阶段运行 contract 或 integration smoke test。
- 远端服务暂时不可用时必须用 mock/fixture 完成确定性测试，并在阶段记录里明确未验证项；不可把请求成功写成假结果。
- 不为通过测试而降低断言、吞掉异常或把真实接口替换成永久 mock。

## 完成定义

一个阶段只有在代码、测试、文档留痕和独立提交全部完成后才能标记完成。整个重构只有在文本直答/RAG、语音链路、历史与纠错、RAGFlow 文档管理、种子导入、部署说明和端到端验证均通过后才算完成。

