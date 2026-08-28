# RAGFlow Dev Smoke

## 目标

验证 RAGFlow 适配器写接口、dev dataset 创建/复用、三份来源文档解析和原始问题检索。

## 命令

```bash
conda run -n biosafe python -m ruff check biosafe/integrations/ragflow scripts/ragflow_probe.py scripts/import_seed.py scripts/ragflow_dev_smoke.py tests/contract/test_ragflow_client.py
conda run -n biosafe python -m pytest tests/contract/test_ragflow_client.py tests/unit/test_config.py
conda run -n biosafe python scripts/ragflow_dev_smoke.py --dataset-name biosafe-dev-p4-ppe-20260828161459
```

## 结果

- Ruff：通过。
- pytest：4 passed。
- live smoke：通过，复用 dataset `9f08a224a2fb11f1adce556d4f780165`。
- 文档状态：3/3 为 `DONE`。
- 检索：返回 8 个 chunks。

## 备注

原始 NHC 解释页在本环境返回 `412 Precondition Failed`，烟测改用可访问的湖北省卫健委 P4 文章作为替代来源。
