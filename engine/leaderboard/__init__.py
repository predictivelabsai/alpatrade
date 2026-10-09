"""Shareable user strategies and the public strategy Leaderboard (``/leaderboard``).

* :mod:`.store` — CRUD for ``alpatrade.user_strategies`` (owner-scoped writes).
* :mod:`.perf`  — live figures computed from the owner's live runner run
  (``alpatrade.runs`` daily session-close snapshots), never from a snapshot file.
* :mod:`.skill` — the single-markdown strategy skill: front matter, Parameters block,
  chat hand-off prompt.
* :mod:`.seed`  — idempotent seeding of the live Mag-7 BTD strategy (shown as Predictive Labs Ltd).
"""
