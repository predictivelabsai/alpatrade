"""Autonomous trading agent team — durable run engine (Phase B).

Postgres-backed, paper-only. See docs/autonomous-agent-team-plan.md.

- ``policy``  — pure, deterministic RiskPolicy (no LLM); the model extracts facts,
  this decides admission + sizing, and enforces the paper-only wall.
- ``store``   — Postgres CRUD for runs / checkpoints (steps) / events / promotions.
- ``queue``   — DB-backed run queue (claim via FOR UPDATE SKIP LOCKED, heartbeat,
  ack/fail, requeue_unfinished).
- ``graph``   — resumable checkpointed pipeline over the existing Orchestrator phases.
- ``worker``  — continuous loop (gated by AUTONOMY_ENABLED).
"""
