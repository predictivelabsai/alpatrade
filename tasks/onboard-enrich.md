builder: codex

# Enrich repository onboarding

Inspect code and AGENTS.md. Fill Conventions and Do not touch with concrete
guidance grounded in the code, replacing generic starter guidance while keeping
existing project policies and custom text. Add these sections if missing.
Review Commands against their declared sources and working directories. Correct
wrong commands and record verification results in docs/onboard-verification.md.
Only execute short, demonstrably safe checks. Do not install dependencies, start
long-running servers, execute destructive or deployment scripts, deploy, push,
read secrets, or change unrelated application code. Preserve existing policies.
Never enable Muse. Only edit AGENTS.md and docs/onboard-verification.md. Commit
those files with a message beginning "ops: enrich". Leave the worktree clean.
As your last action, create an empty .dispatch-done file at the repository root.
