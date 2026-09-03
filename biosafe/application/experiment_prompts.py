"""Experiment context loading and strict direct-decision prompt building."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DECISION_RULES = """\
你只能输出一个 JSON 对象，不要输出 Markdown、解释或额外文本。

可选输出：
1. 只有当用户的主要意图是控制实验界面，或询问当前虚拟实验的界面状态时：
   {"decision":"func_call","func_call":{"command":"命令名","confidence":0到1,"params":{}}}
2. 如果当前实验上下文足以可靠回答用户问题：
   {"decision":"direct","answer":"不超过 120 字的中文回答"}
3. 如果当前实验上下文不足、问题超出当前实验、你不确定，或需要法规/标准/文档依据：
   {"decision":"need_rag"}

FuncCall 命令白名单：
- ShowProcedurePanel：用户明确要求查看当前步骤、流程或进度，params 必须为空。
- CurrentExperimentOperation：用户询问当前这一步在界面中要做什么，params 必须为空。
- ShowEquipmentName：用户要求显示当前选中设备的名称，params 必须为空。
- SwitchExperimentScene：用户明确要求切换、打开或进入实验场景，params 必须为空。

FuncCall 判断要求：
- 不能只因出现“进入、打开、步骤、实验”等关键词就调用命令。
- “进入生物安全实验室时，应当佩戴什么防护？”是知识问题，不是 FuncCall。
- “打开实验室门前需要注意什么？”是知识问题，不是 FuncCall。
- “现在第几步了？”可以返回 ShowProcedurePanel。
- “这一步怎么操作？”可以返回 CurrentExperimentOperation。
- “这个设备叫什么？”可以返回 ShowEquipmentName。
- “切换到 PCR 实验”可以返回 SwitchExperimentScene。
- 只有高度确定时才返回 func_call，confidence 必须不低于 0.8。

直接回答要求：
- 只使用当前实验上下文中能支持的信息，不编造依据。
- 回答适合语音播报，避免项目符号、编号列表和 Markdown。
- 涉及安全等级、法规依据、设备参数且上下文没有明确给出时，必须选择 need_rag。
"""

_EXPERIMENT_SYSTEM_TEMPLATE = """\
你是一名生物安全实验训练助手，正在指导学生完成虚拟实验。

当前实验：{title}

实验用品：
{supplies}

实验步骤：
{steps}

核心知识点：
{knowledge_points}

{decision_rules}
"""

_GENERIC_SYSTEM_PROMPT = """\
你是一名生物安全领域助手。

当前没有绑定具体实验上下文。你只能在能稳定、简洁、可靠回答时 direct；只要需要法规、
标准、SOP、名录或文档依据，就选择 need_rag。

{decision_rules}
"""


@dataclass(frozen=True)
class ExperimentContext:
    id: str
    title: str
    supplies: tuple[str, ...]
    steps: tuple[str, ...]
    knowledge_points: tuple[str, ...]


def _is_generic(experiment_id: str | None) -> bool:
    if experiment_id is None:
        return True
    return str(experiment_id).strip().lower() in {"", "generic", "none", "null"}


def _extract_json_block(text: str) -> str | None:
    brace_start = text.find("{")
    has_props = '"experiment_supplies"' in text or '"experiment_steps"' in text
    if brace_start == -1 and has_props:
        prop_start = text.find('"experiment_')
        last_bracket = text.rfind("]")
        if prop_start == -1 or last_bracket == -1:
            return None
        return "{" + text[prop_start : last_bracket + 1] + "}"
    if brace_start == -1:
        return None

    depth = 0
    for index in range(brace_start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start : index + 1]
    return text[brace_start:] + "}"


def _parse_json_robustly(raw_json: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        fixed = re.sub(r',\s*"[^"]*$', "", raw_json)
        fixed += "]" * max(fixed.count("[") - fixed.count("]"), 0)
        fixed += "}" * max(fixed.count("{") - fixed.count("}"), 0)
        try:
            parsed = json.loads(fixed)
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _parse_experiment(path: Path) -> ExperimentContext | None:
    text = path.read_text(encoding="utf-8")
    title_match = re.search(r'title:\s*"([^"]+)"', text)
    title = title_match.group(1) if title_match else f"实验{path.stem}"

    backtick_match = re.search(r"context:\s*`(.*?)`", text, re.DOTALL)
    if backtick_match:
        raw_context = backtick_match.group(1)
    else:
        context_match = re.search(r"context:\s*`?", text)
        if not context_match:
            logger.warning("experiment file has no context: %s", path)
            return None
        raw_context = text[context_match.end() :]

    json_block = _extract_json_block(raw_context)
    if not json_block:
        logger.warning("experiment context has no JSON block: %s", path)
        return None

    data = _parse_json_robustly(json_block)
    if data is None:
        logger.warning("experiment context JSON parse failed: %s", path)
        return None

    return ExperimentContext(
        id=path.stem,
        title=title,
        supplies=_strings(data.get("experiment_supplies")),
        steps=_strings(data.get("experiment_steps")),
        knowledge_points=_strings(data.get("knowledge_points_list")),
    )


class ExperimentPromptStore:
    def __init__(self, experiments_dir: Path | str = "experiments"):
        self.experiments_dir = Path(experiments_dir)
        self._experiments: dict[str, ExperimentContext] = {}
        self.reload()

    def reload(self) -> None:
        self._experiments.clear()
        if not self.experiments_dir.exists():
            logger.info("experiment directory does not exist: %s", self.experiments_dir)
            return
        for path in sorted(self.experiments_dir.glob("*.md")):
            experiment = _parse_experiment(path)
            if experiment:
                self._experiments[experiment.id] = experiment
        logger.info("loaded %d experiment contexts", len(self._experiments))

    def list_experiments(self) -> list[ExperimentContext]:
        return list(self._experiments.values())

    def build_messages(self, experiment_id: str | None, question: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.build_system_prompt(experiment_id)},
            {"role": "user", "content": question},
        ]

    def build_system_prompt(self, experiment_id: str | None) -> str:
        if _is_generic(experiment_id):
            return _GENERIC_SYSTEM_PROMPT.format(decision_rules=_DECISION_RULES)

        experiment = self._experiments.get(str(experiment_id))
        if experiment is None:
            logger.info("experiment %s not found, using generic prompt", experiment_id)
            return _GENERIC_SYSTEM_PROMPT.format(decision_rules=_DECISION_RULES)

        return _EXPERIMENT_SYSTEM_TEMPLATE.format(
            title=experiment.title,
            supplies="\n".join(f"- {item}" for item in experiment.supplies) or "无",
            steps="\n".join(experiment.steps) or "无",
            knowledge_points="\n".join(f"- {item}" for item in experiment.knowledge_points)
            or "无",
            decision_rules=_DECISION_RULES,
        )
