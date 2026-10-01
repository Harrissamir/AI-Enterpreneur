"""The conversation engine: model provider + tools + guardrails."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import anthropic

from .config import Settings
from .personas import Persona
from .providers import AnthropicProvider, ProviderError, build_provider
from .store import Store
from .tools import ToolContext, run_tool, tool_definitions

log = logging.getLogger("copilot.engine")


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
                 client: anthropic.Anthropic | None = None, provider=None):
        self.settings = settings
        self.store = store
        self.personas = personas
        if provider is None:
            provider = AnthropicProvider(model=settings.model, client=client) if client else build_provider(settings)
        self.provider = provider

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

        try:
            result = self.provider.complete(
                system=persona.system_prompt(), session_note=self._session_note(ctx, session),
                history=history, tools=tool_definitions(persona), max_tokens=persona.max_tokens,
                model=persona.model, run_tool=lambda name, args: run_tool(name, args, ctx))
        except ProviderError as exc:
            log.error("%s error: %s", self.provider.name, exc)
            if exc.retry_after is not None:
                raise CopilotError(
                    "The assistant is busy right now. Please try again in a minute, "
                    f"or reach us directly: {persona.contact_url}", status=429) from exc
            raise CopilotError(
                f"The assistant is temporarily unavailable. You can reach us directly: {persona.contact_url}"
            ) from exc

        usage = {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens}
        self.store.add_usage(result.input_tokens, result.output_tokens)
        self.store.bump_turn(session_id)

        text = "\n\n".join(result.texts).strip()
        if not text:
            text = "Done — see below." if ctx.actions else "Sorry, I didn't catch that. Could you rephrase?"
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
