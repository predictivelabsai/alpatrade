# Hermes Phase 1

AlpaTrade runs Nous Hermes Agent as a separate Coolify/Compose service. The
Hermes API is private to the application network; browsers continue to use the
authenticated AlpaTrade `/app` chat endpoint.

## Required Coolify configuration

Set `HERMES_API_SERVER_KEY` to a generated secret of at least eight characters.
Configure one supported upstream model credential, such as `XAI_API_KEY`,
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENROUTER_API_KEY`. Never expose
port 8642 publicly.

Hermes persists its profile, sessions, memory, and skills in the `hermes-data`
volume mounted at `/opt/data`. Do not attach two Hermes containers to this same
volume. If the profile needs initial configuration, run the official `setup`
command once against that volume before starting `gateway run`.

Optional variables:

- `HERMES_IMAGE_TAG` pins the tested image version.
- `HERMES_API_MODEL` selects the advertised Hermes profile/model name.
- `HERMES_API_TIMEOUT_SECONDS` changes AlpaTrade's request timeout.

## Chat routing

Use `/hermes` for a single message:

```text
/hermes explain how you would optimize an AAPL backtest
```

The following unprefixed message returns to the user's saved default framework.
`/deepagents` and `/langgraph` provide equivalent one-message overrides. Users
can still choose a persistent default in Settings.

If Hermes is unavailable before producing output, AlpaTrade reports the route
change and falls back to DeepAgents. Phase 1 provides conversation only; scoped
backtest and paper-trading tools are intentionally deferred to Phase 2.
