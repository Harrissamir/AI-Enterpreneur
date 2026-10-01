# Business Copilot

An AI assistant that sits on your websites, answers visitors' questions from your own knowledge base, scopes their needs and turns the good-fit ones into booked calls.

One engine, several **personas** (one per brand). It ships with two:

| Persona | Site | What it does |
|---|---|---|
| `harris_sons` — Harris & Sons Hiring Copilot | harrisandsons.lovable.app | Answers EU/UK companies' questions about hiring in India (EOR vs entity, compensation, 2025 Labour Codes, PoSH, exits), drafts a hiring brief, captures leads and offers a call. |
| `veraxis` — VERAXIS Assistant | xveraxis.lovable.app | Explains the eight domains, engagement process, published fees and integrity policy; prepares a scoping-conversation enquiry. Gives no advice on specific matters. |

> The original 2025 notebook is kept in [`legacy/`](legacy/). It was a simulation class with a deprecated OpenAI call; nothing from it runs in the new engine.

## How it works

```
Visitor's browser                      Your API (this repo, e.g. on Render)          Anthropic
┌──────────────────────┐  POST /v1/chat ┌──────────────────────────────────┐  messages ┌────────┐
│ widget.js on a       │ ─────────────▶ │ origin check → rate limit →      │ ────────▶ │ Claude │
│ Lovable site         │ ◀───────────── │ daily budget → persona prompt +  │ ◀──────── │        │
│ (one <script> tag)   │ reply+actions  │ knowledge → tools                │           └────────┘
└──────────────────────┘                │   capture_lead  → SQLite + webhook ──▶ Zapier → Gmail/Sheets
                                        │   offer_booking → "Book a call" button
                                        │   draft_role_brief → hiring-brief card
                                        └──────────────────────────────────┘
```

- **Personas** live in `personas/<id>/`: `persona.json` (name, colours, booking link, allowed websites, tools), `prompt.md` (behaviour and hard limits), `knowledge/*.md` (facts). Edit the Markdown to change what the assistant knows — no code changes.
- **Guardrails:** each persona only answers on its own websites; per-visitor rate limit; per-conversation turn limit; a daily token budget that switches the assistant to a "contact us directly" message when reached; leads are saved only with explicit consent.
- **Leads** go to SQLite and, if `LEAD_WEBHOOK_URL` is set, are POSTed as JSON (name, email, company, need, hiring brief) — point it at a Zapier Catch Hook to get an email and a Google Sheet row per lead.

## Run it locally

```bash
pip install -r requirements.txt
cp .env.example .env            # then paste your ANTHROPIC_API_KEY
uvicorn copilot.api:app --reload
```

Open http://localhost:8000/demo to try both personas in the browser, or chat in the terminal:

```bash
python -m copilot.cli --persona harris_sons
python -m copilot.cli --persona harris_sons --leads    # list captured leads
```

## Deploy (Render)

1. On render.com: **New + → Blueprint** → choose this repository. `render.yaml` sets everything up.
2. Fill in `ANTHROPIC_API_KEY` and (recommended) `LEAD_WEBHOOK_URL`. `ADMIN_TOKEN` is generated for you.
3. When it is live, check `https://<your-service>.onrender.com/health`.

Notes: free instances sleep when idle, so the first message after a quiet spell can take ~a minute. Without a persistent disk the SQLite lead log resets on each deploy — the webhook is your durable copy.

## Add it to your Lovable sites

Add one line before `</body>` in each site's `index.html` (see [`docs/LOVABLE.md`](docs/LOVABLE.md) for the exact prompts to paste into Lovable):

```html
<!-- Harris & Sons -->
<script src="https://<your-service>.onrender.com/widget.js" data-persona="harris_sons" async></script>

<!-- VERAXIS -->
<script src="https://<your-service>.onrender.com/widget.js" data-persona="veraxis" async></script>
```

Optional attributes: `data-accent="#hex"`, `data-position="left"`, `data-open="true"`. Any button on the site can open the chat with `window.BusinessCopilot.open()` or ask a question with `window.BusinessCopilot.ask("…")`.

If you add a custom domain (e.g. harrisandsons.com), add it to `allowed_origins` in that persona's `persona.json`.

## Read your leads

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" https://<your-service>.onrender.com/v1/leads
```

The response also shows `tokens_today` so you can watch spend.

## Add a new persona

Copy `personas/harris_sons` to `personas/<new_id>`, change `persona.json` (`id`, brand, booking URL, `allowed_origins`, tools), rewrite `prompt.md` and the knowledge files, redeploy, and embed with `data-persona="<new_id>"`.

## Tests

```bash
pytest -q
```

The suite uses a scripted fake model, so it needs no API key.

## Roadmap

- **Private copilot** — an owner-only persona over the same engine: lead follow-ups, proposal and LinkedIn drafts, using `/v1/leads` as its memory.
- Streaming replies.
- Weekly lead digest by email.
