"""Talk to a persona from the terminal:  python -m copilot.cli --persona harris_sons"""

from __future__ import annotations

import argparse
import uuid

from .config import Settings
from .engine import Copilot, CopilotError
from .personas import load_personas
from .store import Store


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with a copilot persona in the terminal.")
    parser.add_argument("--persona", default="harris_sons")
    parser.add_argument("--leads", action="store_true", help="Print captured leads and exit")
    args = parser.parse_args()

    settings = Settings()
    store = Store(settings.db_path)
    if args.leads:
        for lead in store.leads(args.persona):
            print(f"{lead['created_at']}  {lead['name']} <{lead['email']}>  {lead['company']}  — {lead['need']}")
        return

    personas = load_personas(settings.personas_dir)
    bot = Copilot(settings, store, personas)
    persona = personas[args.persona]
    session = f"cli-{uuid.uuid4()}"
    history: list[dict] = []
    print(f"{persona.assistant_name}\n{persona.greeting}\n(Ctrl+C to quit)\n")
    try:
        while True:
            text = input("you > ").strip()
            if not text:
                continue
            history.append({"role": "user", "content": text})
            try:
                reply = bot.reply(persona.id, session, history)
            except CopilotError as exc:
                print(f"[{exc}]")
                history.pop()
                continue
            history.append({"role": "assistant", "content": reply.text})
            print(f"\n{reply.text}\n")
            for action in reply.actions:
                if action["type"] == "book_call":
                    print(f"  [button] {action['label']} → {action['url']}\n")
                elif action["type"] == "role_brief":
                    print(action["markdown"] + "\n")
                elif action["type"] == "lead_captured":
                    print("  [lead saved]\n")
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
