# Ledger

A pretend-money stock trading game for kids and teens. Players get $1,000 of fake cash, trade a
simulated market of 76 real-company stocks, finish Academy lessons, battle trading bots, and play
Scam Detective, with no real money, ads, chat or purchases.

## Run from source

```sh
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python "Ledger Game.py"
```

## Test

```sh
./venv/bin/python -m unittest discover -s tests
```

## Build

`./build_app.sh` makes `dist/Ledger.app` and `dist/Ledger-<version>-mac.zip` (runs the tests first).
On Windows, run `pyinstaller Ledger.spec`. Signing and notarization are in `PUBLISHING.md`.

## Files

| File | What it is |
|---|---|
| `Ledger Game.py` | The game (Pygame) |
| `ledger_safety.py` | Password/PIN hashing, username and headline filters, age rules |
| `google_auth.py` | Optional Google sign-in (needs `google_config.json`, not committed) |
| `tests/` | Unit tests for the safety rules |
| `tools/make_icon.py` | Regenerates `assets/icon.png` |

## Where data lives

Packaged app: `~/Library/Application Support/Ledger/` (Mac) or `%APPDATA%\Ledger\` (Windows).
From source: `data/` next to the game. Nothing is sent to a server.
