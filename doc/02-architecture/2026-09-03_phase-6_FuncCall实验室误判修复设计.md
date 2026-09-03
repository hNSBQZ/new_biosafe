# Phase 6 - FuncCall 实验室误判修复设计

## 问题与目标

`SwitchExperimentScene` 使用未锚定的 `进入.*实验` 规则，导致“进入生物安全实验室时，应当佩戴什么防护？”被识别为切换实验场景。目标是只让完整、短促的场景控制命令命中，并让包含“实验室”的知识问题继续进入 direct/RAG 链路。

## 范围与非目标

- 收紧 `biosafe/application/funcall_detector.py` 的场景切换正则。
- 增加“进入实验室”“打开实验室门”负例，以及“进入 PCR 实验”正例。
- 不增加 LLM 意图分类、查询改写、槽位抽取或新的回答路径。

## 规则

场景切换必须匹配完整输入，动作限于“切换/换/跳转/转到/进入/开始/打开”等明确控制动词，目标必须是 `实验(?!室)`、场景或项目。控制短语之后不得再带“时应当如何”等知识问句。

## 风险与回滚

严格锚定可能让带礼貌尾词的真实控制命令漏判；首版保留可选“页面/界面”和句末语气词。回滚只需恢复原两条正则，不涉及数据或 API。

## 验证

```bash
conda run -n biosafe python -m pytest tests/unit/test_funcall_detector.py tests/unit/test_query_service.py
conda run -n biosafe ruff check biosafe/application/funcall_detector.py tests/unit/test_funcall_detector.py
```
