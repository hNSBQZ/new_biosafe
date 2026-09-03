"""Independent answer correction model adapter."""

from __future__ import annotations

import json
from typing import Any, Protocol

from openai import APIError, APITimeoutError, AsyncOpenAI

from biosafe.config import CorrectionConfig
from biosafe.domain.correction import CorrectionResult


class CorrectionClientError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class AnswerCorrectionClientProtocol(Protocol):
    async def generate(self, question: str, original_answer: str) -> CorrectionResult: ...


class OpenAIAnswerCorrectionClient:
    def __init__(self, config: CorrectionConfig):
        self.config = config
        self._client: AsyncOpenAI | None = None
        if config.ready:
            self._client = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=config.timeout_seconds,
                max_retries=0,
            )

    async def generate(self, question: str, original_answer: str) -> CorrectionResult:
        if self._client is None or not self.config.ready:
            raise CorrectionClientError(
                "correction_not_configured", "Answer correction model is not configured"
            )
        try:
            response = await self._client.responses.create(
                model=self.config.model,
                tools=[{"type": "web_search"}],
                temperature=0,
                input=_build_prompt(question, original_answer),
            )
        except APITimeoutError as exc:
            raise CorrectionClientError(
                "correction_timeout", "Answer correction request timed out"
            ) from exc
        except APIError as exc:
            raise CorrectionClientError(
                "correction_api_error", "Answer correction request failed"
            ) from exc
        except Exception as exc:
            raise CorrectionClientError(
                "correction_unavailable", "Answer correction service was unavailable"
            ) from exc

        payload = _response_to_dict(response)
        output_text = _extract_output_text(response, payload)
        try:
            return parse_correction_response(output_text, payload)
        except ValueError as exc:
            raise CorrectionClientError("correction_parse_error", str(exc)) from exc

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()


def _build_prompt(question: str, original_answer: str) -> str:
    return (
        "你是生物安全问答复核助手。请使用 web_search 检索权威公开来源，优先采用中国"
        "国家标准、法律法规以及政府或监管机构正式文件。请独立核实问题，不要默认原系统"
        "答案正确。\n\n"
        "如果问题缺少必要上下文或无法由公开权威来源可靠回答，can_answer=false；否则给出"
        "简洁、准确、可核查的中文答案。输出只能是一个 JSON 对象，不要 Markdown 或额外"
        "说明。\n\n"
        "JSON 格式：\n"
        '{"can_answer":true或false,"answer":"可回答时填写，否则为空",'
        '"cannot_answer_reason":"不可回答时填写，否则为空",'
        '"citations":[{"title":"","url":"","note":""}]}\n\n'
        f"问题：{question}\n"
        f"原系统答案（仅供对照）：{original_answer}"
    )


def parse_correction_response(
    output_text: str, response_payload: dict[str, Any] | None = None
) -> CorrectionResult:
    json_text = _extract_first_json_object(output_text)
    if json_text is None:
        raise ValueError("Correction model output did not contain a JSON object")
    try:
        value = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError("Correction model output was not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Correction model output JSON was not an object")
    can_answer = _normalize_bool(value.get("can_answer"))
    if can_answer is None:
        raise ValueError("Correction model output had an invalid can_answer value")
    answer = str(value.get("answer") or "").strip()
    reason = str(value.get("cannot_answer_reason") or "").strip()
    if can_answer and not answer:
        raise ValueError("Correction model output did not contain an answer")

    citations: list[dict[str, str]] = []
    _collect_annotations(response_payload or {}, citations)
    raw_citations = value.get("citations")
    if isinstance(raw_citations, list):
        for item in raw_citations:
            normalized = _normalize_citation(item)
            if normalized is not None:
                citations.append(normalized)
    return CorrectionResult(
        can_answer=can_answer,
        answer=answer if can_answer else "",
        cannot_answer_reason=reason,
        citations=_deduplicate(citations),
    )


def _response_to_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        try:
            value = response.model_dump(mode="json")
        except TypeError:
            value = response.model_dump()
        return value if isinstance(value, dict) else {}
    return {}


def _extract_output_text(response: Any, payload: dict[str, Any]) -> str:
    output_text = getattr(response, "output_text", None) or payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    texts: list[str] = []
    for output in payload.get("output", []):
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                texts.append(content["text"].strip())
    return "\n".join(text for text in texts if text)


def _extract_first_json_object(text: str) -> str | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines.pop()
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        character = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : index + 1]
    return None


def _normalize_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "可答", "可以", "能回答"}:
            return True
        if normalized in {"false", "no", "0", "不可答", "不可以", "不能回答"}:
            return False
    return None


def _normalize_citation(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    citation = {
        "title": str(value.get("title") or value.get("name") or "").strip(),
        "url": str(value.get("url") or value.get("uri") or value.get("source_url") or "").strip(),
        "note": str(
            value.get("note") or value.get("snippet") or value.get("quote") or ""
        ).strip(),
    }
    return citation if any(citation.values()) else None


def _collect_annotations(value: Any, output: list[dict[str, str]]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_annotations(item, output)
        return
    if not isinstance(value, dict):
        return
    annotations = value.get("annotations")
    if isinstance(annotations, list):
        for annotation in annotations:
            normalized = _normalize_citation(annotation)
            if normalized is not None:
                output.append(normalized)
    for nested in value.values():
        _collect_annotations(nested, output)


def _deduplicate(citations: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for citation in citations:
        key = (citation["title"], citation["url"], citation["note"])
        if key not in seen:
            result.append(citation)
            seen.add(key)
    return result
