# Phase 5 - RAGFlow dev 知识库烟测

- 状态：DONE
- 范围：RAGFlow 适配器写接口、dev dataset 生成脚本、三份来源文档上传解析、原始问题检索烟测。
- 关键设计：adapter 继续只输出归一化对象；新增 dataset/document/create-parse/delete 写方法；烟测脚本默认使用 `biosafe-dev-` 前缀并复用已有 dataset；`Document.status` 以远端 `run` 字段为准。
- 实际变更：`feat(ragflow): add dev dataset smoke and write adapter`，新增 `scripts/ragflow_dev_smoke.py`，补齐 `RAGFlowClient` 创建/上传/解析/删除接口和脚本入口 bootstrap，`tests/contract/test_ragflow_client.py` 覆盖新契约。
- 数据或接口兼容性：`biosafe/integrations/ragflow/models.py` 增补少量展示字段；`QueryService` 在线检索仍只读取 `.env`/binding 中的 dataset id，不依赖新增管理面。
- 验证命令与真实结果：
  - `conda run -n biosafe python -m ruff check biosafe/integrations/ragflow scripts/ragflow_probe.py scripts/import_seed.py scripts/ragflow_dev_smoke.py tests/contract/test_ragflow_client.py`：通过。
  - `conda run -n biosafe python -m pytest tests/contract/test_ragflow_client.py tests/unit/test_config.py`：4 passed。
  - `conda run -n biosafe python scripts/ragflow_dev_smoke.py --dataset-name biosafe-dev-p4-ppe-20260828161459`：通过，复用 dataset `9f08a224a2fb11f1adce556d4f780165`，3 个文档均为 `DONE`，检索返回 8 个 chunk。
- 外部服务验证：创建并复用了 `biosafe-dev-p4-ppe-20260828161459`，上传 `病原微生物实验室生物安全管理条例.html`、`中国首个P4实验室正式运行.html`、`GB_19489-2007.pdf`；原始 NHC 解释页返回 `412`，改用可访问的湖北省卫健委 P4 文章作为替代来源。
- 提交：`a4e09a6 feat(ragflow): add dev dataset smoke and write adapter`
- 遗留问题：知识库管理页、删除/重试/预览等管理接口还没做完；Phase 4 前端工作仍有未收口改动。
- 下一阶段入口：继续补 RAGFlow 管理路由和网页管理端，或先收尾 Phase 4 的现存改动后再整体推进。
