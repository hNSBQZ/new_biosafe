# Phase 1 设计 - SQLite 与 Excel 种子

## 目标与非目标

目标是实现可重复迁移、历史/纠错/实验绑定/admin user repository、历史 API 与 Excel 幂等导入。非目标是将纠错发布到 RAGFlow、历史相似匹配或复制 RAGFlow 文档状态。

## 受影响模块

- `biosafe/storage/`：SQLite 连接、迁移和扁平 repository。
- `biosafe/domain/`：历史和引用快照模型。
- `services/api/routes/history.py`：分页、详情与显式纠错。
- `scripts/import_seed.py`：本地 Excel 导入。

## 接口、事件与数据

创建 `schema_migration`、`chat_history`、`admin_user`、`experiment_dataset_binding`，不使用跨服务外键。`GET /api/history` 分页，`GET /api/history/{id}` 返回详情，`PATCH /api/history/{id}/correction` 只更新纠错和更新时间审计字段。

Excel 指纹由规范化后的固定映射字段计算。第二次导入相同记录命中 `seed_fingerprint` 唯一约束并计为 skipped。引用解析为 JSON 数组；无法解析时保存原始文本快照和解析错误标记，不丢弃整行。

## 风险、回滚与验证

SQLite 并发通过 WAL、busy timeout 和短事务控制。读取损坏 JSON 时返回空数组并记录脱敏错误。回滚方式是回退阶段提交并删除本阶段新建的开发数据库；迁移不自动降级已有库。

验证命令覆盖空库启动、迁移重跑、并发写、损坏 JSON、分页/纠错 API、Excel 首次 84 added 与第二次 84 skipped。
