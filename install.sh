#!/bin/bash
# AssetHero installer
# Usage: curl -fsSL https://assethero.chat/install.sh | bash
set -e

echo "==> Installing AssetHero..."

# Install uv if not present
if ! command -v uv &>/dev/null; then
    echo "==> Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install assethero via uv tool (isolated venv, no system pollution)
uv tool install assethero

echo ""
echo "==> Installed! Run:"
echo ""
echo "    assethero"
echo ""
