#!/bin/zsh
# Builds Ledger.app (Mac) into dist/. Run on Windows with the same pyinstaller line to get Ledger.exe.
cd "$(dirname "$0")"
./venv/bin/pip install -q pyinstaller
./venv/bin/pyinstaller --noconfirm --windowed --name Ledger "Ledger Game.py"
cd dist && ditto -c -k --keepParent Ledger.app Ledger-mac.zip && echo "Built dist/Ledger-mac.zip"
