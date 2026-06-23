#!/usr/bin/env bash
# verify_no_secrets.sh — scan staged changes for leaked secrets before they are committed.
#
# Usage:
#   scripts/verify_no_secrets.sh            # scan staged diff (pre-commit use)
#   scripts/verify_no_secrets.sh --all      # scan the entire working tree (tracked files)
#   scripts/verify_no_secrets.sh <files...> # scan specific files
#
# Install as a pre-commit hook:
#   ln -sf ../../scripts/verify_no_secrets.sh .git/hooks/pre-commit
#
# Exits non-zero (blocking the commit) if a likely secret value is found.
# Reference: the project secrets policy in CLAUDE.md — XAI_API_KEY was leaked once.
set -euo pipefail

RED=$'\033[0;31m'; YEL=$'\033[0;33m'; GRN=$'\033[0;32m'; NC=$'\033[0m'

# Patterns matching actual secret *values* (not the variable names, which are fine to mention).
# Each line: a grep -E regex. Keep these tight to avoid false positives on docs/placeholders.
PATTERNS=(
  'xai-[A-Za-z0-9]{16,}'                              # xAI / Grok keys
  'sk-[A-Za-z0-9_-]{20,}'                             # OpenAI-style keys
  'sk-ant-[A-Za-z0-9_-]{20,}'                         # Anthropic keys
  'AKIA[0-9A-Z]{16}'                                  # AWS access key id
  'AIza[0-9A-Za-z_-]{35}'                             # Google API key
  'gh[pousr]_[A-Za-z0-9]{36,}'                        # GitHub tokens
  '(PK|AK)[A-Z0-9]{16,}'                              # Alpaca-style key ids
  'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'  # JWT
  'gAAAAA[A-Za-z0-9_-]{20,}'                          # Fernet token ciphertext
  'postgres(ql)?://[^:@/ ]+:[^@/ ]+@'                 # DB URL with inline password
)

# Allow obvious placeholders so .env.sample / docs don't trip the scan.
PLACEHOLDER='your_|YOUR_|<[^>]+>|xxxx|XXXX|example|EXAMPLE|changeme|CHANGEME|\.\.\.|placeholder'

mode="${1:-}"
files=()
if [[ "$mode" == "--all" ]]; then
  mapfile -t files < <(git ls-files)
elif [[ $# -gt 0 ]]; then
  files=("$@")
else
  # default: staged, added/changed text files
  mapfile -t files < <(git diff --cached --name-only --diff-filter=ACM)
fi

# Never scan the local .env (gitignored) or the venv; we only care about what could be committed.
filtered=()
for f in "${files[@]:-}"; do
  [[ -z "$f" ]] && continue
  [[ "$f" == ".env" || "$f" == */.env ]] && continue
  [[ "$f" == .venv/* || "$f" == */.venv/* ]] && continue
  [[ -f "$f" ]] || continue
  filtered+=("$f")
done

if [[ ${#filtered[@]} -eq 0 ]]; then
  echo "${GRN}verify_no_secrets: nothing to scan.${NC}"
  exit 0
fi

found=0
for f in "${filtered[@]}"; do
  for pat in "${PATTERNS[@]}"; do
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      # skip placeholder/sample lines
      if echo "$line" | grep -qE "$PLACEHOLDER"; then continue; fi
      echo "${RED}POSSIBLE SECRET${NC} in ${YEL}${f}${NC}: ${line}"
      found=1
    done < <(grep -nE "$pat" "$f" 2>/dev/null || true)
  done
done

if [[ $found -ne 0 ]]; then
  echo ""
  echo "${RED}✗ verify_no_secrets: potential secret(s) detected. Commit blocked.${NC}"
  echo "  If this is a false positive, redact the value or add a placeholder, then retry."
  exit 1
fi

echo "${GRN}✓ verify_no_secrets: no secrets detected in scanned files.${NC}"
exit 0
