"""HTTP API + widget hosting.  Run:  uvicorn copilot.api:app --reload"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .config import ROOT, Settings
from .engine import Copilot, CopilotError
from .personas import load_personas
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = ROOT / "copilot" / "static"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    persona: str = Field(..., max_length=40)
    session_id: str = Field(..., min_length=8, max_length=100)
    messages: list[ChatMessage] = Field(..., max_length=60)


class RateLimiter:
    def __init__(self, limit: int, window: int):
        self.limit, self.window = limit, window
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


def create_app(settings: Settings | None = None, copilot: Copilot | None = None) -> FastAPI:
    settings = settings or Settings()
    if copilot is None:
        personas = load_personas(settings.personas_dir)
        copilot = Copilot(settings, Store(settings.db_path), personas)
    personas = copilot.personas
    limiter = RateLimiter(settings.rate_limit_messages, settings.rate_limit_window_seconds)

    all_origins = sorted({o for p in personas.values() for o in p.allowed_origins} | set(settings.extra_origins))

    app = FastAPI(title="Business Copilot", version=__version__, docs_url="/docs")
    app.add_middleware(CORSMiddleware, allow_origins=all_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"], max_age=3600)
    app.state.copilot = copilot

    def client_ip(request: Request) -> str:
        # Behind a proxy, uvicorn's --proxy-headers already resolves the visitor's address.
        return request.client.host if request.client else "unknown"

    def require_admin(authorization: str = Header(default="")) -> None:
        if not settings.admin_token or authorization != f"Bearer {settings.admin_token}":
            raise HTTPException(status_code=401, detail="Unauthorised")

    @app.exception_handler(CopilotError)
    def copilot_error(_: Request, exc: CopilotError):
        return JSONResponse(status_code=exc.status, content={"error": str(exc)})

    @app.get("/health")
    def health():
        provider = getattr(copilot.provider, "name", "unknown")
        key = settings.groq_api_key if provider == "groq" else settings.anthropic_api_key
        return {"ok": True, "version": __version__, "personas": sorted(personas),
                "provider": provider, "model": getattr(copilot.provider, "model", None),
                "api_key_set": bool(key and key.strip().lower() not in {"none", ""}),
                "commit": os.getenv("RENDER_GIT_COMMIT", "")[:7]}

    @app.get("/v1/personas/{persona_id}")
    def persona_config(persona_id: str):
        persona = personas.get(persona_id)
        if persona is None:
            raise HTTPException(status_code=404, detail="Unknown assistant")
        return persona.public_config()

    @app.post("/v1/chat")
    def chat(body: ChatRequest, request: Request):
        persona = personas.get(body.persona)
        if persona is None:
            raise HTTPException(status_code=404, detail="Unknown assistant")
        origin = (request.headers.get("origin") or "").rstrip("/")
        same_site = origin.split("://", 1)[-1] == request.headers.get("host", "")  # the /demo page
        if origin and not same_site and origin not in persona.allowed_origins \
                and origin not in settings.extra_origins:
            raise HTTPException(status_code=403, detail="This assistant is not enabled for this website")
        if not limiter.allow(client_ip(request)):
            raise CopilotError("You're sending messages quickly — please wait a few minutes.", status=429)
        reply = copilot.reply(body.persona, body.session_id, [m.model_dump() for m in body.messages])
        return {"reply": reply.text, "actions": reply.actions, "lead_captured": reply.lead_captured}

    @app.get("/v1/leads", dependencies=[Depends(require_admin)])
    def leads(persona: str | None = None, limit: int = 100):
        return {"leads": copilot.store.leads(persona, min(limit, 500)),
                "tokens_today": copilot.store.tokens_today()}

    @app.get("/widget.js")
    def widget():
        return FileResponse(STATIC / "widget.js", media_type="application/javascript",
                            headers={"Cache-Control": "public, max-age=300"})

    @app.get("/demo")
    def demo():
        return FileResponse(STATIC / "demo.html", media_type="text/html")

    return app


app = create_app()
