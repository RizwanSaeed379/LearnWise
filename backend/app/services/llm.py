"""Pluggable LLM adapter.

Every provider we care about (Ollama, vLLM, Groq, LM Studio, the Kaggle tunnel)
speaks the same "OpenAI-compatible" chat API:

    POST {LLM_BASE_URL}/chat/completions
    {"model": "...", "messages": [{"role": "user", "content": "..."}]}

So switching provider = changing LLM_BASE_URL / LLM_MODEL / LLM_API_KEY in .env.
No code changes needed.
"""
import json
import re
from typing import Any, Optional

import httpx

from app.config import Settings, get_settings

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Optional[Settings] = None):
        self.s = settings or get_settings()
        self.base_url = self.s.llm_base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        # Tunnels add a browser warning page; these headers skip it.
        return {
            "Authorization": f"Bearer {self.s.llm_api_key}",
            "ngrok-skip-browser-warning": "true",
        }

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 1500,
        json_mode: bool = False,
    ) -> str:
        """Send messages, return the assistant's text (with <think> blocks removed)."""
        messages = [dict(m) for m in messages]
        if self.s.llm_disable_thinking and "qwen3" in self.s.llm_model.lower():
            # Qwen3 soft switch: '/no_think' in the prompt disables the reasoning trace.
            messages[-1]["content"] = messages[-1]["content"] + " /no_think"

        payload: dict[str, Any] = {
            "model": self.s.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=self.s.llm_timeout_seconds) as client:
                r = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=self._headers())
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"LLM request to {self.base_url} failed: {e}") from e

        text = r.json()["choices"][0]["message"]["content"] or ""
        return _THINK_RE.sub("", text).strip()

    async def chat_json(self, messages: list[dict[str, str]], **kw) -> Any:
        """Like chat(), but parses the reply as JSON. Retries once if the model returns bad JSON."""
        last_err: Exception | None = None
        for _ in range(2):
            text = await self.chat(messages, json_mode=True, **kw)
            try:
                return json.loads(_FENCE_RE.sub("", text))
            except json.JSONDecodeError as e:
                last_err = e
                messages = messages + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": "That was not valid JSON. Reply with ONLY the JSON object."},
                ]
        raise LLMError(f"Model did not return valid JSON: {last_err}")

    async def ping(self) -> bool:
        """True if the server answers GET /models (cheap reachability check)."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self.base_url}/models", headers=self._headers())
                return r.status_code == 200
        except httpx.HTTPError:
            return False


def get_llm() -> LLMClient:
    return LLMClient()
