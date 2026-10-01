"""Model providers. Each one runs the tool-calling loop in its own API format.

- AnthropicProvider: Claude via the Anthropic SDK (prompt caching on the persona prompt).
- OpenAICompatProvider: any OpenAI-compatible chat API — used for Groq's free tier.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import anthropic
import httpx

log = logging.getLogger("copilot.providers")

MAX_TOOL_ROUNDS = 4
ToolRunner = Callable[[str, dict], str]


class ProviderError(Exception):
    """The model API failed. `retry_after` is set when it was a rate limit."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class Completion:
    texts: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str = "", model: str = "", client: anthropic.Anthropic | None = None):
        self.model = model
        self._api_key = api_key
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            if not self._api_key:
                raise ProviderError("missing ANTHROPIC_API_KEY")
            self._client = anthropic.Anthropic(api_key=self._api_key, max_retries=2)
        return self._client

    def complete(self, *, system: str, session_note: str, history: list[dict], tools: list[dict],
                 max_tokens: int, model: str | None, run_tool: ToolRunner) -> Completion:
        out = Completion()
        system_blocks = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": session_note},
        ]
        convo: list[dict] = list(history)
        for _ in range(MAX_TOOL_ROUNDS + 1):
            kwargs = dict(model=model or self.model, max_tokens=max_tokens, system=system_blocks, messages=convo)
            if tools:
                kwargs["tools"] = tools
            try:
                resp = self.client.messages.create(**kwargs)
            except anthropic.APIError as exc:
                raise ProviderError(str(exc)) from exc
            out.input_tokens += getattr(resp.usage, "input_tokens", 0) or 0
            out.output_tokens += getattr(resp.usage, "output_tokens", 0) or 0
            out.texts.extend(b.text for b in resp.content if b.type == "text" and b.text.strip())
            calls = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not calls:
                break
            convo.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})
            convo.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": c.id, "content": run_tool(c.name, c.input or {})}
                for c in calls
            ]})
        return out


class OpenAICompatProvider:
    """Chat Completions API with function calling (Groq, OpenRouter, OpenAI, ...)."""

    def __init__(self, *, name: str, api_key: str, base_url: str, model: str,
                 extra_body: dict | None = None, http: httpx.Client | None = None,
                 max_wait_seconds: float = 20):
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.extra_body = extra_body or {}
        self.max_wait_seconds = max_wait_seconds
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=60)

    def _post(self, payload: dict) -> dict:
        if not self._api_key:
            raise ProviderError(f"missing API key for {self.name}")
        for attempt in range(2):
            r = self._http.post(f"{self.base_url}/chat/completions", json=payload,
                                headers={"Authorization": f"Bearer {self._api_key}"})
            if r.status_code == 429:
                wait = _retry_after(r)
                if attempt == 0 and wait <= self.max_wait_seconds:
                    log.info("%s rate limit; waiting %.1fs", self.name, wait)
                    time.sleep(wait)
                    continue
                raise ProviderError(f"{self.name} rate limit: {r.text[:300]}", retry_after=wait)
            if r.status_code >= 400:
                raise ProviderError(f"{self.name} error {r.status_code}: {r.text[:500]}")
            return r.json()
        raise ProviderError(f"{self.name} rate limit")

    def complete(self, *, system: str, session_note: str, history: list[dict], tools: list[dict],
                 max_tokens: int, model: str | None, run_tool: ToolRunner) -> Completion:
        out = Completion()
        messages: list[dict] = [{"role": "system", "content": f"{system}\n\n{session_note}"}, *history]
        fn_tools = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in tools]
        for _ in range(MAX_TOOL_ROUNDS + 1):
            payload = {"model": model or self.model, "messages": messages,
                       # reasoning models spend part of the budget thinking; leave headroom
                       "max_completion_tokens": max_tokens + (600 if "reasoning_effort" in self.extra_body else 0),
                       **self.extra_body}
            if fn_tools:
                payload["tools"] = fn_tools
            data = self._post(payload)
            usage = data.get("usage") or {}
            out.input_tokens += int(usage.get("prompt_tokens") or 0)
            out.output_tokens += int(usage.get("completion_tokens") or 0)
            msg = (data.get("choices") or [{}])[0].get("message") or {}
            text = (msg.get("content") or "").strip()
            if text:
                out.texts.append(text)
            calls = msg.get("tool_calls") or []
            if not calls:
                break
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for call in calls:
                fn = call.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                messages.append({"role": "tool", "tool_call_id": call.get("id"),
                                 "content": run_tool(fn.get("name", ""), args if isinstance(args, dict) else {})})
        return out


def _retry_after(r: httpx.Response) -> float:
    try:
        return float(r.headers.get("retry-after", "60"))
    except ValueError:
        return 60.0


def build_provider(settings) -> AnthropicProvider | OpenAICompatProvider:
    if settings.llm_provider == "groq":
        return OpenAICompatProvider(
            name="groq", api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1",
            model=settings.groq_model,
            # gpt-oss models think before answering; keep that short to save the free daily tokens.
            extra_body={"reasoning_effort": "low"} if "gpt-oss" in settings.groq_model else {},
        )
    return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.model)
