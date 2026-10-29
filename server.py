"""
Small FastAPI backend exposing core.py's translate logic over HTTP, plus
the static frontend (static/index.html, style.css, script.js).

Run with:
    uvicorn server:app --reload
then open http://127.0.0.1:8000

No changes to core.py's translate() interface were needed for the CLI -
stream_translate() is an additional generator-based entry point, added
specifically because a web-search-grounded lookup can take 30-90s+ with
no output in between, which was silently tripping Cloudflare tunnel
timeouts (524) and looking indistinguishable from "broken" to a user
staring at a blank spinner. Streaming progress fixes both.
"""

import json
import logging
import os
import secrets

from anthropic import APIStatusError
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import stream_translate

load_dotenv()

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="cogni")
logger = logging.getLogger("cogni")

# Lightweight access control for /api/translate specifically - this is the
# route that actually spends API credits, so it's the one that matters
# once this server is reachable from outside localhost (e.g. via a
# tunnel). Deliberately NOT full auth/accounts (see README
# "Status") - just enough that a random visitor with the base URL but
# not the key can't run up your Anthropic bill. A custom header + one
# shared key (rather than HTTP Basic) because Basic's browser-native login
# dialog behaves inconsistently with fetch()-based requests; see
# static/script.js for how the key gets attached automatically after the
# first visit via ?key=...
UI_ACCESS_KEY = os.environ.get("UI_ACCESS_KEY")


def require_access_key(x_cogni_key: str | None = Header(default=None)) -> None:
    if not UI_ACCESS_KEY:
        return  # no key configured (e.g. plain localhost use) - open access
    if not x_cogni_key or not secrets.compare_digest(x_cogni_key, UI_ACCESS_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid access key")


class TranslateRequest(BaseModel):
    text: str
    source_lang: str | None = None
    target_lang: str
    mode: str = "auto"  # "auto" | "expression" | "text"


@app.post("/api/translate", dependencies=[Depends(require_access_key)])
def api_translate(req: TranslateRequest) -> StreamingResponse:
    def event_stream():
        # Each line is one JSON event: {"type": "status"|"delta"|"done"|"error", ...}
        # - see core.stream_translate() for what each type carries, and
        # static/script.js for how they're consumed. Errors are reported
        # as an event rather than an HTTP error status because streaming
        # has already started (and returned 200) by the time anything
        # could go wrong here.
        try:
            for event in stream_translate(req.text, req.source_lang or None, req.target_lang, mode=req.mode):
                yield json.dumps(event) + "\n"
        except APIStatusError as e:
            # A transient failure on Anthropic's own infrastructure (5xx,
            # after the SDK's built-in retries were already exhausted) -
            # e.text can read as alarmingly specific ("credential
            # validation failed") despite being a server-side hiccup, not
            # an actual problem with this app's API key. Give the user an
            # accurate message instead of Anthropic's raw (and here,
            # misleading) wording - full detail still goes to the log.
            logger.exception("Anthropic API error while streaming translation for %r", req.text)
            yield json.dumps({"type": "error", "message": "Anthropic's API had a temporary problem on their end (not your request) - please try again."}) + "\n"
        except Exception as e:
            # The client only ever sees str(e) - log the full traceback
            # server-side too, since this is the only place that ever
            # will: uvicorn's access log just shows 200 (the HTTP status
            # is already committed by the time a generator like this one
            # can fail mid-stream), and this except block previously
            # swallowed the real exception entirely once it turned it
            # into a client-facing event.
            logger.exception("Error while streaming translation for %r", req.text)
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


# Registered after /api/translate so that route takes precedence - a
# mount at "/" would otherwise swallow every path, API included. Static
# files themselves aren't behind the access key (they're free to serve
# and contain no secrets) - only the paid API call is gated.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
