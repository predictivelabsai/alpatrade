#!/bin/bash
# AlpaTrade installer
# Usage: curl -fsSL https://alpatrade.chat/install.sh | bash
set -e

echo "==> Installing AlpaTrade..."

# Install uv if not present
if ! command -v uv &>/dev/null; then
    echo "==> Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install alpatrade via uv tool (isolated venv, no system pollution)
uv tool install alpatrade

echo ""
echo "==> Installed! Run:"
echo ""
echo "    alpatrade"
echo ""
