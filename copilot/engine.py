"""The conversation engine: Claude + tools + guardrails."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import anthropic

from .config import Settings
from .personas import Persona
from .store import Store
from .tools import ToolContext, run_tool, tool_definitions

log = logging.getLogger("copilot.engine")

MAX_TOOL_ROUNDS = 4


class CopilotError(Exception):
    """An error safe to show to the visitor."""

    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


@dataclass
class Reply:
    text: str
    actions: list[dict] = field(default_factory=list)
    lead_captured: bool = False
    usage: dict = field(default_factory=dict)


def clean_history(messages: list[dict], max_messages: int, max_chars: int) -> list[dict]:
    """Keep only plain user/assistant text, alternating, starting with the user, ending with the user."""
    cleaned: list[dict] = []
    for m in messages[-max_messages:]:
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        content = content.strip()[: max_chars if role == "user" else max_chars * 3]
        if cleaned and cleaned[-1]["role"] == role:
            cleaned[-1]["content"] += "\n\n" + content
        else:
            cleaned.append({"role": role, "content": content})
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    if not cleaned or cleaned[-1]["role"] != "user":
        raise CopilotError("Please type a message.", status=400)
    return cleaned


class Copilot:
    def __init__(self, settings: Settings, store: Store, personas: dict[str, Persona],
                 client: anthropic.Anthropic | None = None):
        self.settings = settings
        self.store = store
        self.personas = personas
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            if not self.settings.anthropic_api_key:
                raise CopilotError("The assistant is not configured yet (missing API key).")
            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key, max_retries=2)
        return self._client

    def reply(self, persona_id: str, session_id: str, messages: list[dict]) -> Reply:
        persona = self.personas.get(persona_id)
        if persona is None:
            raise CopilotError("Unknown assistant.", status=404)
        if len(session_id) < 8 or len(session_id) > 100:
            raise CopilotError("Invalid session.", status=400)

        session = self.store.session(session_id, persona.id)
        if session["turns"] >= self.settings.max_turns_per_session:
            raise CopilotError(
                f"This conversation has reached its limit. Please continue directly: {persona.booking_url}",
                status=429)
        if self.store.tokens_today() >= self.settings.daily_token_budget:
            raise CopilotError(
                f"The assistant is resting for today. You can reach us directly: {persona.contact_url}",
                status=429)

        history = clean_history(messages, self.settings.max_history_messages, self.settings.max_message_chars)
        ctx = ToolContext(persona=persona, session_id=session_id, store=self.store,
                          webhook_url=self.settings.lead_webhook_url,
                          lead_captured=session["lead_captured"])

        system = [
            {"type": "text", "text": persona.system_prompt(), "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": self._session_note(ctx, session)},
        ]
        tools = tool_definitions(persona)
        convo: list[dict] = list(history)
        texts: list[str] = []
        usage = {"input_tokens": 0, "output_tokens": 0}

        for _ in range(MAX_TOOL_ROUNDS + 1):
            try:
                kwargs = dict(model=persona.model or self.settings.model, max_tokens=persona.max_tokens,
                              system=system, messages=convo)
                if tools:
                    kwargs["tools"] = tools
                resp = self.client.messages.create(**kwargs)
            except anthropic.APIError as exc:
                log.error("anthropic error: %s", exc)
                raise CopilotError(
                    f"The assistant is temporarily unavailable. You can reach us directly: {persona.contact_url}"
                ) from exc

            usage["input_tokens"] += getattr(resp.usage, "input_tokens", 0) or 0
            usage["output_tokens"] += getattr(resp.usage, "output_tokens", 0) or 0
            texts.extend(b.text for b in resp.content if b.type == "text" and b.text.strip())

            tool_calls = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not tool_calls:
                break
            convo.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})
            convo.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call.id, "content": run_tool(call.name, call.input or {}, ctx)}
                for call in tool_calls
            ]})

        self.store.add_usage(usage["input_tokens"], usage["output_tokens"])
        self.store.bump_turn(session_id)

        text = "\n\n".join(texts).strip()
        if not text:
            text = "Done — see above." if ctx.actions else "Sorry, I didn't catch that. Could you rephrase?"
        return Reply(text=text, actions=_dedupe(ctx.actions), lead_captured=ctx.lead_captured, usage=usage)

    @staticmethod
    def _session_note(ctx: ToolContext, session: dict) -> str:
        notes = ["# Session context"]
        notes.append("A lead was ALREADY captured in this conversation; do not ask for contact details again."
                     if ctx.lead_captured else "No contact details have been captured yet.")
        if session.get("role_brief"):
            notes.append("A hiring brief was already drafted in this conversation:\n" + session["role_brief"])
        return "\n".join(notes)


def _dedupe(actions: list[dict]) -> list[dict]:
    seen, out = set(), []
    for a in actions:
        key = a["type"]
        if key in seen and key != "role_brief":
            continue
        seen.add(key)
        out.append(a)
    return out
