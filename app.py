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
from engine.web import ph_charts  # noqa: E402
from engine.web import ph_settings  # noqa: E402
from engine.web import ph_pnl  # noqa: E402
from engine.web import ph_filings  # noqa: E402
from engine.web import ph_marketintel  # noqa: E402
from engine.web import ph_ipomap  # noqa: E402
from engine.web import ph_index_options  # noqa: E402
from engine.web import ph_hedgefunds  # noqa: E402
from engine.web import ph_press  # noqa: E402
from engine.web import ph_spacs  # noqa: E402
from engine.web import ph_premarket  # noqa: E402
from engine.web import ph_research  # noqa: E402

ph_landing.register(app, rt)
ph_auth.register(app, rt)
ph_chat.register(app, rt)
ph_guide.register(app, rt)
ph_charts.register(app, rt)
ph_settings.register(app, rt)
ph_pnl.register(app, rt)
ph_filings.register(app, rt)
ph_marketintel.register(app, rt)
ph_ipomap.register(app, rt)
ph_index_options.register(app, rt)
ph_hedgefunds.register(app, rt)
ph_press.register(app, rt)
ph_spacs.register(app, rt)
ph_premarket.register(app, rt)
ph_research.register(app, rt)

# --- voice (mic button → /voice/* endpoints) --------------------------------
from engine.voice import register_voice_routes  # noqa: E402

register_voice_routes(app)

# --- autonomy bootstrap (runs inside the web process) ----------------------
# Coolify deploys this app via Dockerfile.agui → `python main.py` → app.py.
# The docker-compose `autonomy` service is NOT started by Coolify (it builds
# from the Dockerfile, not `docker compose up`), so we bootstrap the autonomy
# loop here as daemon threads within the web process.
#
# 1. Nightly PnL email scheduler — always starts (disable via PNL_REPORT_FREQUENCY=off).
#    Idempotent per process (schedule.py guards with _started).
# 2. Autonomy worker loop — only starts when AUTONOMY_ENABLED=true. Runs the
#    scout→backtest→gate→paper→reconcile→refit→promote pipeline on a timer
#    (AUTONOMY_SCAN_SECONDS, default 300s). Paper-only; policy.py hard-rejects
#    live orders. When AUTONOMY_ENABLED is false/absent, the worker just sleeps.
#
# Both are daemon threads → die with the process, never block shutdown.
def _bootstrap_autonomy():
    import logging, threading
    log = logging.getLogger("autonomy.bootstrap")
    try:
        from engine.autonomy.schedule import start as _start_scheduler
        _start_scheduler()
        log.info("PnL-report scheduler started")
    except Exception as e:  # noqa: BLE001
        log.warning("PnL scheduler failed to start: %s", e)
    if os.getenv("AUTONOMY_ENABLED", "false").lower() in ("1", "true", "yes", "on"):
        try:
            from engine.autonomy.worker import loop as _worker_loop
            wid = os.getenv("AUTONOMY_WORKER_ID", "web-1")
            threading.Thread(target=_worker_loop, args=(wid,),
                             name="autonomy-worker", daemon=True).start()
            log.info("Autonomy worker started (AUTONOMY_ENABLED=true, worker_id=%s)", wid)
        except Exception as e:  # noqa: BLE001
            log.warning("Autonomy worker failed to start: %s", e)
    else:
        log.info("Autonomy worker disabled (AUTONOMY_ENABLED not true)")


_bootstrap_autonomy()


if __name__ == "__main__":
    serve(port=int(os.getenv("ASSETHERO_WEB_PORT", "5001")))
