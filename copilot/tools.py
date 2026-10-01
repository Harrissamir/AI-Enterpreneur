"""Tools the model can call, and the server-side handlers that run them."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx

from .personas import Persona
from .store import Store

log = logging.getLogger("copilot.tools")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

TOOL_SCHEMAS: dict[str, dict] = {
    "capture_lead": {
        "name": "capture_lead",
        "description": (
            "Save a visitor's contact details so the firm can follow up. Call ONLY after the visitor has "
            "typed their name, email and organisation in this conversation AND explicitly agreed to be "
            "contacted. Never guess or fill in fields the visitor did not give."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
                "company": {"type": "string", "description": "Company or organisation"},
                "country": {"type": "string", "description": "Where the organisation is based"},
                "need": {"type": "string", "description": "One or two sentences on what they need"},
                "roles": {"type": "string", "description": "Roles or domains involved, if given"},
                "headcount": {"type": "string", "description": "Planned hires or team size, if given"},
                "timeline": {"type": "string", "description": "Timeline, if given"},
                "consent_to_contact": {"type": "boolean"},
            },
            "required": ["name", "email", "company", "need", "consent_to_contact"],
        },
    },
    "offer_booking": {
        "name": "offer_booking",
        "description": (
            "Show the visitor a button to book a call / send an enquiry. Use when the visitor asks about "
            "pricing, next steps or help with their specific situation, or after you have helped and they "
            "look like a fit. Do not use more than once every few messages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Short reason shown on the button, e.g. 'Scope your first India hire'"},
            },
            "required": ["reason"],
        },
    },
    "draft_role_brief": {
        "name": "draft_role_brief",
        "description": (
            "Produce a structured hiring brief for a role in India once you know at least the title, "
            "seniority and the main outcomes. Use the visitor's own words; leave a field out rather than invent it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "seniority": {"type": "string"},
                "location": {"type": "string", "description": "City/state or remote"},
                "employment_model": {"type": "string", "description": "EOR, own entity, contractor, or undecided"},
                "outcomes": {"type": "array", "items": {"type": "string"}, "description": "What success looks like in 6 months"},
                "must_have": {"type": "array", "items": {"type": "string"}},
                "nice_to_have": {"type": "array", "items": {"type": "string"}},
                "budget": {"type": "string", "description": "Budget as the visitor stated it"},
                "open_questions": {"type": "array", "items": {"type": "string"}, "description": "Decisions still to make"},
            },
            "required": ["title", "seniority", "outcomes"],
        },
    },
}


@dataclass
class ToolContext:
    persona: Persona
    session_id: str
    store: Store
    webhook_url: str = ""
    actions: list[dict] = field(default_factory=list)
    lead_captured: bool = False


def tool_definitions(persona: Persona) -> list[dict]:
    return [TOOL_SCHEMAS[name] for name in persona.tools if name in TOOL_SCHEMAS]


def run_tool(name: str, args: dict, ctx: ToolContext) -> str:
    if name not in ctx.persona.tools or name not in TOOL_SCHEMAS:
        return f"Error: tool {name} is not available."
    try:
        return _HANDLERS[name](args, ctx)
    except Exception as exc:  # never let a tool crash the conversation
        log.exception("tool %s failed", name)
        return f"Error running {name}: {exc}"


def _capture_lead(args: dict, ctx: ToolContext) -> str:
    if ctx.lead_captured:
        return "Already saved for this conversation. Do not ask for details again."
    if not args.get("consent_to_contact"):
        return "Not saved: the visitor has not agreed to be contacted. Ask for consent first."
    email = str(args.get("email", "")).strip()
    if not EMAIL_RE.match(email):
        return "Not saved: the email address looks invalid. Ask the visitor to check it."
    lead = {k: str(v).strip()[:500] for k, v in args.items() if k != "consent_to_contact" and v}
    lead["email"] = email
    lead_id = ctx.store.add_lead(ctx.persona.id, ctx.session_id, lead)
    ctx.lead_captured = True
    ctx.actions.append({"type": "lead_captured"})
    _send_webhook(ctx, {"event": "lead", "lead_id": lead_id, "persona": ctx.persona.id,
                        "brand": ctx.persona.brand, "session_id": ctx.session_id,
                        "role_brief": ctx.store.session(ctx.session_id, ctx.persona.id).get("role_brief"),
                        **lead})
    return (f"Saved. Tell the visitor {ctx.persona.brand} will reply by email, and that they can also "
            f"book directly: {ctx.persona.booking_url}")


def _offer_booking(args: dict, ctx: ToolContext) -> str:
    label = str(args.get("reason") or "Book a call").strip()[:60]
    ctx.actions.append({"type": "book_call", "label": label, "url": ctx.persona.booking_url})
    return "A booking button is now shown under your message. Mention it in one short sentence; do not paste the link."


def _bullets(items) -> str:
    return "\n".join(f"- {i}" for i in items if str(i).strip()) if items else ""


def _draft_role_brief(args: dict, ctx: ToolContext) -> str:
    parts = [f"## Hiring brief: {args.get('title', '').strip()} ({args.get('seniority', '').strip()})"]
    for label, key in (("Location", "location"), ("Employment model", "employment_model"), ("Budget", "budget")):
        if args.get(key):
            parts.append(f"**{label}:** {args[key]}")
    for label, key in (("Outcomes in the first 6 months", "outcomes"), ("Must-have", "must_have"),
                       ("Nice-to-have", "nice_to_have"), ("Open questions", "open_questions")):
        body = _bullets(args.get(key))
        if body:
            parts.append(f"**{label}**\n{body}")
    brief = "\n\n".join(parts)
    ctx.store.set_role_brief(ctx.session_id, brief)
    ctx.actions.append({"type": "role_brief", "markdown": brief})
    return ("The brief is now displayed to the visitor as a card. Do not repeat it. In one or two sentences, "
            "point out the most important open decision, then offer help turning it into a search.")


def _send_webhook(ctx: ToolContext, payload: dict) -> None:
    if not ctx.webhook_url.lower().startswith(("https://", "http://")):
        return  # empty or a placeholder such as "none": webhook switched off
    try:
        httpx.post(ctx.webhook_url, json=payload, timeout=8)
    except httpx.HTTPError:
        log.warning("lead webhook failed; lead is still stored in the database")


_HANDLERS = {
    "capture_lead": _capture_lead,
    "offer_booking": _offer_booking,
    "draft_role_brief": _draft_role_brief,
}
