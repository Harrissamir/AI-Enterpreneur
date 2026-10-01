"""Load personas: persona.json (settings), prompt.md (behaviour), knowledge/*.md (facts)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Persona:
    id: str
    brand: str
    assistant_name: str
    tagline: str
    greeting: str
    starter_questions: list[str]
    booking_url: str
    contact_url: str
    accent: str
    allowed_origins: list[str]
    tools: list[str]
    model: str | None
    max_tokens: int
    prompt: str
    knowledge: str

    def system_prompt(self) -> str:
        return (
            f"{self.prompt.strip()}\n\n"
            "# Knowledge\n"
            "The following is your reference material. Treat it as accurate for this firm.\n\n"
            f"{self.knowledge.strip()}"
        )

    def public_config(self) -> dict:
        """What the website widget is allowed to see."""
        return {
            "id": self.id,
            "brand": self.brand,
            "assistant_name": self.assistant_name,
            "tagline": self.tagline,
            "greeting": self.greeting,
            "starter_questions": self.starter_questions,
            "booking_url": self.booking_url,
            "contact_url": self.contact_url,
            "accent": self.accent,
        }


def load_persona(folder: Path) -> Persona:
    meta = json.loads((folder / "persona.json").read_text(encoding="utf-8"))
    prompt = (folder / "prompt.md").read_text(encoding="utf-8")
    knowledge_dir = folder / "knowledge"
    knowledge = "\n\n".join(
        p.read_text(encoding="utf-8") for p in sorted(knowledge_dir.glob("*.md"))
    ) if knowledge_dir.exists() else ""
    return Persona(
        id=meta["id"],
        brand=meta["brand"],
        assistant_name=meta["assistant_name"],
        tagline=meta.get("tagline", ""),
        greeting=meta["greeting"],
        starter_questions=meta.get("starter_questions", []),
        booking_url=meta["booking_url"],
        contact_url=meta.get("contact_url", meta["booking_url"]),
        accent=meta.get("accent", "#1F3A5F"),
        allowed_origins=[o.rstrip("/") for o in meta.get("allowed_origins", [])],
        tools=meta.get("tools", []),
        model=meta.get("model"),
        max_tokens=int(meta.get("max_tokens", 900)),
        prompt=prompt,
        knowledge=knowledge,
    )


def load_personas(personas_dir: Path) -> dict[str, Persona]:
    personas: dict[str, Persona] = {}
    for folder in sorted(p for p in personas_dir.iterdir() if (p / "persona.json").exists()):
        persona = load_persona(folder)
        personas[persona.id] = persona
    if not personas:
        raise RuntimeError(f"No personas found in {personas_dir}")
    return personas
