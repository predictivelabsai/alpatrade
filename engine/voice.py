"""Voice mode — a WebSocket proxy between the browser and x.ai's realtime agent.

Mirrors the kaljuvee-chat implementation (PCM16 mono @ 24kHz, server-side VAD, the
browser just streams mic audio and plays the agent's audio + transcript), and adds a
`get_positions` **function tool** so the agent can answer "what are my positions?" by
calling Alpaca live. The browser never holds the API key — /ws/voice bridges
browser audio ↔ the x.ai realtime WebSocket.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import websockets as wslib
from starlette.websockets import WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

# A pre-created x.ai realtime agent id, or fall back to a realtime model connection.
AGENT_ID = os.environ.get("XAI_VOICE_AGENT_ID", "")
MODEL = os.environ.get("XAI_VOICE_MODEL", "grok-4-fast")
XAI_URL = (
    f"wss://api.x.ai/v1/realtime?agent_id={AGENT_ID}" if AGENT_ID
    else f"wss://api.x.ai/v1/realtime?model={MODEL}"
)

INSTRUCTIONS = (
    "You are AlpaTrade's trading voice assistant. Keep answers short and spoken-friendly. "
    "When the user asks about their positions, portfolio, holdings, P&L or account, call the "
    "get_positions tool and read back the result naturally (round dollars, mention the biggest "
    "movers). Do not invent numbers — always use the tool for live data."
)

# OpenAI/x.ai realtime-compatible function tool.
TOOLS = [{
    "type": "function",
    "name": "get_positions",
    "description": "Get the user's current Alpaca paper-trading account: equity, cash, and open positions with unrealised P&L.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}]

SESSION_UPDATE = {
    "type": "session.update",
    "session": {
        "modalities": ["audio", "text"],
        "instructions": INSTRUCTIONS,
        "input_audio_format": "pcm16",
        "output_audio_format": "pcm16",
        "turn_detection": {"type": "server_vad"},
        "tools": TOOLS,
        "tool_choice": "auto",
    },
}


def _get_positions_text() -> str:
    """Fetch the Alpaca paper account + positions and format a spoken-friendly summary."""
    try:
        from engine.brokers.alpaca import AlpacaAPI
        api = AlpacaAPI(paper=True)
        acct = api.get_account() or {}
        positions = api.get_positions() or []
    except Exception as e:  # noqa: BLE001
        return f"I couldn't reach the brokerage account: {e}"

    equity = float(acct.get("equity", 0) or 0)
    cash = float(acct.get("cash", 0) or 0)
    if not positions:
        return (f"Your account equity is ${equity:,.0f} with ${cash:,.0f} in cash, "
                f"and you have no open positions.")

    lines = []
    for p in positions:
        try:
            sym = p.get("symbol")
            qty = float(p.get("qty", 0) or 0)
            mv = float(p.get("market_value", 0) or 0)
            pl = float(p.get("unrealized_pl", 0) or 0)
            lines.append(f"{sym}: {qty:g} shares worth ${mv:,.0f}, "
                         f"{'up' if pl >= 0 else 'down'} ${abs(pl):,.0f}")
        except Exception:  # noqa: BLE001
            continue
    return (f"Your account equity is ${equity:,.0f} with ${cash:,.0f} cash across "
            f"{len(positions)} open positions. " + "; ".join(lines) + ".")


async def _voice_ws(ws: WebSocket):
    await ws.accept()
    key = os.environ.get("XAI_API_KEY", "")
    if not key:
        await ws.send_json({"type": "error", "message": "voice not configured (no XAI_API_KEY)"})
        await ws.close()
        return

    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with wslib.connect(XAI_URL, additional_headers=headers, max_size=None) as xai:
            await xai.send(json.dumps(SESSION_UPDATE))
            await ws.send_json({"type": "ready"})

            async def browser_to_xai():
                while True:
                    msg = json.loads(await ws.receive_text())
                    mt = msg.get("type")
                    if mt == "audio":
                        await xai.send(json.dumps(
                            {"type": "input_audio_buffer.append", "audio": msg["audio"]}))
                    elif mt == "commit":  # push-to-talk fallback (server VAD is default)
                        await xai.send(json.dumps({"type": "input_audio_buffer.commit"}))
                        await xai.send(json.dumps({"type": "response.create"}))
                    elif mt == "cancel":
                        await xai.send(json.dumps({"type": "response.cancel"}))

            async def handle_function_call(call_id, name):
                # Only get_positions is registered; run it off the event loop.
                out = await asyncio.to_thread(_get_positions_text) if name == "get_positions" \
                    else f"unknown tool {name}"
                await ws.send_json({"type": "tool", "name": name})
                await xai.send(json.dumps({
                    "type": "conversation.item.create",
                    "item": {"type": "function_call_output", "call_id": call_id, "output": out},
                }))
                await xai.send(json.dumps({"type": "response.create"}))

            async def xai_to_browser():
                async for raw in xai:
                    e = json.loads(raw)
                    t = e.get("type")
                    if t == "response.output_audio.delta":
                        await ws.send_json({"type": "audio", "audio": e.get("delta", "")})
                    elif t == "response.output_audio_transcript.delta":
                        await ws.send_json({"type": "assistant_delta", "text": e.get("delta", "")})
                    elif t == "response.output_audio_transcript.done":
                        await ws.send_json({"type": "assistant_done", "text": e.get("transcript", "")})
                    elif t == "input_audio_buffer.input_audio_transcription.completed":
                        await ws.send_json({"type": "user_transcript", "text": e.get("transcript", "")})
                    elif t == "input_audio_buffer.input_audio_transcription.updated":
                        await ws.send_json({"type": "user_partial", "text": e.get("transcript", "")})
                    elif t == "input_audio_buffer.speech_started":
                        await ws.send_json({"type": "speech_started"})
                    elif t == "input_audio_buffer.speech_stopped":
                        await ws.send_json({"type": "speech_stopped"})
                    elif t == "response.function_call_arguments.done":
                        await handle_function_call(e.get("call_id"), e.get("name"))
                    elif t == "response.done":
                        await ws.send_json({"type": "done"})
                    elif t == "error":
                        await ws.send_json({"type": "error",
                                            "message": json.dumps(e.get("error", e))[:300]})

            _, pending = await asyncio.wait(
                [asyncio.create_task(browser_to_xai()), asyncio.create_task(xai_to_browser())],
                return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as ex:  # noqa: BLE001
        log.warning("voice proxy error: %s", ex)
        try:
            await ws.send_json({"type": "error", "message": str(ex)[:200]})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


def register_voice_routes(app):
    """Attach the /ws/voice WebSocket proxy to the FastHTML (Starlette) app.

    Inserted at the front of the router so FastHTML's catch-all static route can't
    shadow the WebSocket handshake.
    """
    from starlette.routing import WebSocketRoute
    app.router.routes.insert(0, WebSocketRoute("/ws/voice", _voice_ws))
