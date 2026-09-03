"""Conservative rule-based FuncCall detector."""

from __future__ import annotations

import re
from re import Pattern
from typing import TypedDict

from biosafe.domain.query import FuncCallResult


class _RawRule(TypedDict):
    command: str
    triggers: list[str]
    excludes: list[str]


class _CompiledRule(TypedDict):
    command: str
    triggers: list[Pattern[str]]
    excludes: list[Pattern[str]]


_FUNCALL_RULES_RAW: tuple[_RawRule, ...] = (
    {
        "command": "ShowProcedurePanel",
        "triggers": [
            r"(查看|显示|打开).*(步骤|流程|进度)",
            r"(做到哪|到哪一步|第几步|进行到哪)(了|啦|呢)?$",
            r"(当前|现在).*(步骤|进度)",
            r"(进行|进展)到.*(哪一?步|什么地步)",
        ],
        "excludes": [
            r"(如果|万一|假如|遇到|发生)",
            r"(怎么做|怎么处理|怎么操作|怎么配|如何).{4,}",
        ],
    },
    {
        "command": "CurrentExperimentOperation",
        "triggers": [
            r"(当前|这一?步|现在).*(怎么[做操]|该[做干]什么)",
            r"(这步|这一步).*(是什么|做什么)",
        ],
        "excludes": [
            r"(如果|万一|假如|遇到|发生)",
            r".{6,}(怎么做|下一步)",
        ],
    },
    {
        "command": "ShowEquipmentName",
        "triggers": [
            r"(这个?|那个?)(设备|仪器|器材|东西).*(叫什么|是什么|名[字称])",
            r"(显示|查看).*(仪器|设备).*(名[字称]|标签)",
        ],
        "excludes": [],
    },
    {
        "command": "SwitchExperimentScene",
        "triggers": [
            r"^(?:请|帮我)?(?:切换|换|跳转|转到|进入)(?:到|至)?"
            r"[^，。？！?!]{0,24}(?:实验场景|实验项目|实验(?!室)|场景|项目)"
            r"(?:页面|界面)?(?:吧|一下)?$",
            r"^(?:请|帮我)?(?:我要?做|我想做|开始做?|打开)"
            r"[^，。？！?!]{0,24}实验(?!室)(?:场景|项目|页面|界面)?(?:吧|一下)?$",
        ],
        "excludes": [],
    },
)


def _compile_rules() -> tuple[_CompiledRule, ...]:
    return tuple(
        {
            "command": rule["command"],
            "triggers": [re.compile(pattern) for pattern in rule["triggers"]],
            "excludes": [re.compile(pattern) for pattern in rule["excludes"]],
        }
        for rule in _FUNCALL_RULES_RAW
    )


_FUNCALL_RULES = _compile_rules()


def _normalize_query(query: str) -> str:
    normalized = re.sub(r"\s+", "", query.strip())
    return normalized.rstrip("？?。！!.，,…~")


def detect_funcall(query: str) -> FuncCallResult | None:
    if not query or not query.strip():
        return None

    query_clean = _normalize_query(query)
    if not query_clean:
        return None

    for rule in _FUNCALL_RULES:
        if any(pattern.search(query_clean) for pattern in rule["excludes"]):
            continue
        if any(pattern.search(query_clean) for pattern in rule["triggers"]):
            return FuncCallResult(command=rule["command"], confidence=0.95, params={})
    return None
