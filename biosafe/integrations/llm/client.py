"""OpenAI-compatible chat client adapter."""

from __future__ import annotations

from typing import Any, Protocol

from openai import APIError, APITimeoutError, AsyncOpenAI

from biosafe.config import LLMConfig


class LLMError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ChatLLMProtocol(Protocol):
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        extra_body: dict[str, Any] | None = None,
    ) -> str: ...


class OpenAIChatClient:
    def __init__(self, config: LLMConfig):
        self.config = config
        self._client: AsyncOpenAI | None = None
        if config.ready:
            self._client = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=config.timeout_seconds,
                max_retries=0,
            )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        extra_body: dict[str, Any] | None = None,
    ) -> str:
        if self._client is None or not self.config.ready:
            raise LLMError("llm_not_configured", "LLM is not configured")
        try:
            response = await self._client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                extra_body=extra_body,
            )
        except APITimeoutError as exc:
            raise LLMError("llm_timeout", "LLM request timed out") from exc
        except APIError as exc:
            raise LLMError("llm_api_error", "LLM request failed") from exc
        except Exception as exc:
            raise LLMError("llm_unavailable", "LLM response was unavailable") from exc

        content = response.choices[0].message.content if response.choices else ""
        return content.strip() if content else ""
