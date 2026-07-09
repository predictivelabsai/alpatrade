"""AlpaTrade — merged single FastHTML app (PEHero skin).

One entry point, one process. The shared house-style shell lives in
:mod:`engine.web.ph_layout`; every feature module exposes ``register(app, rt)``
and renders its pages through that shell:

  - :mod:`engine.web.ph_landing`  — anonymous marketing site ( ``/``, ``/platform`` … )
  - :mod:`engine.web.ph_auth`     — auth + profile ( ``/signin``, ``/register``, ``/profile`` … )
  - :mod:`engine.web.ph_chat`     — the 3-pane chat product ( ``/app``, ``/app/chat``, ``/news`` )
  - :mod:`engine.web.ph_guide`    — user guide / download ( ``/guide``, ``/download`` )

Voice routes come from :func:`engine.voice.register_voice_routes`.

Run:  ASSETHERO_WEB_PORT=5001 python app.py
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from fasthtml.common import (  # noqa: E402
    Link, Script, fast_app, serve,
)

# --- shared CDN + static assets loaded on every page ------------------------
_MARKED_CDN = "https://cdn.jsdelivr.net/npm/marked/marked.min.js"
_PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

_HDRS = (
    Link(rel="stylesheet", href="/static/app.css"),
    Script(src=_MARKED_CDN),
    Script(src=_PLOTLY_CDN),
    Script(src="/static/voice.js", defer=True),
)

app, rt = fast_app(
    exts="ws",
    pico=False,
    secret_key=os.getenv("JWT_SECRET", "dev-insecure-secret-change-me"),
    hdrs=_HDRS,
)

# --- feature modules: each adds its routes via register(app, rt) ------------
# Order matters: landing owns '/', auth owns '/signin', chat owns '/app'.
from engine.web import ph_landing  # noqa: E402
from engine.web import ph_auth  # noqa: E402
from engine.web import ph_chat  # noqa: E402
from engine.web import ph_guide  # noqa: E402

ph_landing.register(app, rt)
ph_auth.register(app, rt)
ph_chat.register(app, rt)
ph_guide.register(app, rt)

# --- voice (mic button → /voice/* endpoints) --------------------------------
from engine.voice import register_voice_routes  # noqa: E402

register_voice_routes(app)


if __name__ == "__main__":
    serve(port=int(os.getenv("ASSETHERO_WEB_PORT", "5001")))
