#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
python tasks/cli_trader.py --strategy buy-the-dip --mode paper "$@"
