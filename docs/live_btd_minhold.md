# Live Mag-7 buy-the-dip with true min-hold (`scripts/live_btd_minhold.py`)

Standalone runner for the LIVE Alpaca account. It is **not** imported by the web app/API
and **not** started by `docker-compose.yaml`, so deploying alpatrade.chat never runs it.
Nothing trades unless you pass `--live`.

Strategy defaults: AAPL MSFT GOOGL AMZN META TSLA NVDA; buy when price is ≥3% below the
20-bar high (same reference as `utils/buy_the_dip.py`; `--ref prev_close` for a
close-to-close dip); TP +8%, SL −1.5%, min-hold 3 calendar days (TP/SL cannot fire
earlier), max-hold 3 calendar days (exit in the last minutes of the first session on/after day 3).
Sizing: 10% of equity per position (`--pos-frac 0.142857` = 1/7), notional/fractional
market orders, one position per symbol, cash only (≤ min(cash, non_marginable_buying_power)).
The runner only manages positions it opened (state in `$BTD_STATE_DIR`, default
`~/.alpatrade-live/state.json`); pre-existing positions are ignored but block a new entry in that symbol.

Each run = one idempotent pass (flock, deterministic `client_order_id`s, state file):
exits all session, entries only 15→5 min before the close (reads `/v2/clock`, so half-days work).

```bash
# dry run (no orders); --ignore-hours evaluates as if in the entry window
.venv/bin/python scripts/live_btd_minhold.py --ignore-hours
```

## Switching it on (manual, not done by CI)

`~/.config/systemd/user/alpatrade-btd.service`
```ini
[Unit]
Description=AlpaTrade live Mag-7 BTD min-hold pass
[Service]
Type=oneshot
WorkingDirectory=%h/dev/plai/alpatrade
ExecStart=%h/dev/plai/alpatrade/.venv/bin/python scripts/live_btd_minhold.py --live
```
`~/.config/systemd/user/alpatrade-btd.timer`
```ini
[Unit]
Description=Every 5 min in US market hours
[Timer]
OnCalendar=Mon..Fri *-*-* 09..15:00/5:00 America/New_York
Persistent=false
[Install]
WantedBy=timers.target
```
```bash
systemctl --user daemon-reload && systemctl --user enable --now alpatrade-btd.timer
loginctl enable-linger $USER   # keep user timers running when logged out
# off:  systemctl --user disable --now alpatrade-btd.timer
```
Logs: `~/.alpatrade-live/logs/btd.log` and `journalctl --user -u alpatrade-btd`.
