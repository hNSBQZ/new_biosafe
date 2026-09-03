# Phase 6 - 模型统一决策 FuncCall 设计

## 目标

将 FuncCall 识别并入现有的第一轮实验上下文 LLM 请求。模型必须在 `func_call`、`direct`、`need_rag` 三种结构化决定中三选一；QueryService 根据决定继续走原有四条结果路径，不再在 LLM 前执行本地关键词正则。

## 非目标

- 不增加第二次意图分类请求、查询改写、槽位补全或本地检索。
- 不允许模型生成白名单以外的命令或任意参数。
- 不改变 RAGFlow 原始问题检索、引用校验、历史存储和异步答案修正边界。

## 决策契约

第一轮 LLM 只允许输出：

```json
{"decision":"func_call","func_call":{"command":"ShowProcedurePanel","confidence":0.98,"params":{}}}
{"decision":"direct","answer":"不超过 120 字的中文回答"}
{"decision":"need_rag"}
```

命令白名单保持现有四项：`ShowProcedurePanel`、`CurrentExperimentOperation`、`ShowEquipmentName`、`SwitchExperimentScene`。所有命令沿用原有契约，`params` 必须为空。命令、置信度、参数或 JSON 任一项无效时一律降级为 `need_rag`，不得执行部分解析结果。

提示词强调“控制界面/询问当前虚拟实验状态”才是 FuncCall；包含“实验室”的防护、法规、操作知识问题不是控制命令。系统提示同时提供正反例，不能仅因“进入、打开、步骤、实验”等关键词触发。

## 状态与失败策略

查询事件保留现有 `direct_decision` 和 `instruction` 名称。模型超时、API 错误或不可解析时沿用安全降级：把原始问题直接交给 RAGFlow。由于不再有本地识别，模型不可用时控制指令也会进入 RAG，这是本方案接受的可用性取舍。

## 数据与兼容性

FuncCall 完成事件、历史 `answer_source=instruction`、WebSocket instruction 消息、事件 stage、latency 字段和前端展示契约均不变。

## 风险与回滚

- 模型误判可能触发错误的白名单操作：严格 schema、命令/参数白名单和反例提示降低风险。
- 指令延迟增加到一次 LLM 请求：不增加额外模型轮次。
- 回滚时恢复 QueryService 的本地 detector 分支即可；无 schema 迁移。

## 验证

```bash
conda run -n biosafe python -m pytest tests/unit/test_experiment_prompts.py tests/unit/test_query_service.py
conda run -n biosafe ruff check biosafe services tests
npm --prefix web test -- --run
```

真实验证至少覆盖“现在第几步了”返回 instruction，以及“进入生物安全实验室时，应当佩戴什么防护？”返回 direct/RAG。
