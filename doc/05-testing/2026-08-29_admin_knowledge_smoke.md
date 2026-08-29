# Admin Knowledge Smoke

## 目标

验证管理员登录、dev namespace 过滤、数据集/文档管理、解析、取消、删除和检索预览都能打通真实 RAGFlow。

## 命令

```bash
conda run -n biosafe python scripts/ragflow_admin_smoke.py
```

## 结果

- `ok`: `true`
- `dataset_id`: `af50531ea38911f1adce556d4f780165`
- `dataset_name`: `biosafe-dev-admin-20260829091154`
- `documents`:
  - `病原微生物实验室生物安全管理条例.html` -> `DONE`
  - `中国首个P4实验室正式运行.html` -> `DONE`
  - `cancel_fixture.html` -> `CANCEL`
- `retrieval.chunk_count`: `8`
- `deleted_documents`: 3 个，全部删除成功

## 备注

烟测只操作 `biosafe-dev-` 资源；取消样本使用本地生成的大 HTML fixture，避免对真实业务文档做破坏性尝试。
