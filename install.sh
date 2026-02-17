#!/bin/bash
# AlpaTrade — Termux installer
# Usage: curl -fsSL https://api.alpatrade.dev/install.sh | bash
set -e

echo "==> Installing AlpaTrade..."

# Ensure Python + pip are installed (Termux)
if ! command -v pip &>/dev/null && ! command -v pip3 &>/dev/null; then
    echo "==> Installing Python..."
    pkg install -y python 2>/dev/null || apt install -y python 2>/dev/null || true
fi

# Find pip
PIP=$(command -v pip3 2>/dev/null || command -v pip 2>/dev/null)
if [ -z "$PIP" ]; then
    echo "Error: pip not found. Install Python first: pkg install python"
    exit 1
fi

$PIP install --quiet requests rich 2>/dev/null || $PIP install requests rich

# Download client
DEST="$HOME/.alpatrade"
mkdir -p "$DEST"
curl -fsSL https://raw.githubusercontent.com/predictivelabsai/alpatrade/main/ac.py -o "$DEST/ac.py"

# Create wrapper in ~/bin
mkdir -p "$HOME/bin"
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
cat > "$HOME/bin/ac" << WRAPPER
#!/bin/bash
exec $PY "\$HOME/.alpatrade/ac.py" "\$@"
WRAPPER
chmod +x "$HOME/bin/ac"

# Ensure ~/bin is on PATH
if ! echo "$PATH" | grep -q "$HOME/bin"; then
    echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.bashrc"
    export PATH="$HOME/bin:$PATH"
fi

echo ""
echo "==> Installed! Run:"
echo ""
echo "    ac"
echo ""
echo "    # or connect to a custom server:"
echo "    ac -s http://your-server:5001"
echo ""
