# Phase 1 - SQLite 与 Excel 种子

- 状态：DONE
- 范围：单库迁移、历史/管理员/实验绑定 repository、历史与纠错 API、Excel 幂等种子导入。
- 关键设计：扁平表无跨服务外键；WAL、busy timeout 和短事务支持并发；固定字段内容 SHA-256 作为种子唯一指纹；纠错仅为本地展示和审计。
- 实际变更：新增递增 `schema_migration` 与三张业务表、历史分页/详情/纠错接口、损坏 JSON 容错、命令行种子导入器。
- 数据或接口兼容性：新增本地 SQLite schema v1；RAGFlow 无变化；历史 API 引用字段返回数组，损坏快照降级为空数组。
- 验证命令与真实结果：Ruff 全部通过；Phase 1 单元/集成测试 9 passed，含 24 路并发写、迁移重跑、唯一约束、损坏 JSON 和 API 纠错。
- 外部服务验证：不涉及外部服务。对本地忽略 Excel 的真实导入首次结果为 `added=84, skipped=0, errors=0`，同库第二次为 `added=0, skipped=84, errors=0`；临时数据库已删除。
- 提交：`804ddbd feat(history): add simple sqlite history store and seed importer`。
- 遗留问题：管理员密码初始化和 token 生命周期在 Phase 5/6 实现；种子纠错不会自动发布。
- 下一阶段入口：实现三路径 QueryService 和 SSE，统一写入同一历史表。
