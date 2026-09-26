#!/bin/zsh
# Builds Ledger.app into dist/ and zips it.
#
# Optional signing & notarization (needs a paid Apple Developer account):
#   export LEDGER_SIGN_ID="Developer ID Application: Your Name (TEAMID)"
#   export LEDGER_NOTARY_PROFILE="ledger-notary"   # made once with: xcrun notarytool store-credentials
# Without these the app still builds, but macOS will warn players it's from an unidentified developer.
#
# Windows: run `pyinstaller Ledger.spec` on a Windows PC to get dist\Ledger\Ledger.exe.
set -e
cd "$(dirname "$0")"
./venv/bin/pip install -q -r requirements.txt pyinstaller pillow
./venv/bin/python -m unittest discover -s tests -q
./venv/bin/pyinstaller --noconfirm --clean Ledger.spec

APP=dist/Ledger.app
if [[ -n "$LEDGER_SIGN_ID" ]]; then
  codesign --force --deep --options runtime --timestamp --sign "$LEDGER_SIGN_ID" "$APP"
  codesign --verify --deep --strict "$APP"
  echo "Signed with $LEDGER_SIGN_ID"
fi

VERSION=$(grep -m1 '^VERSION = ' "Ledger Game.py" | cut -d'"' -f2)
ZIP="dist/Ledger-$VERSION-mac.zip"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"

if [[ -n "$LEDGER_SIGN_ID" && -n "$LEDGER_NOTARY_PROFILE" ]]; then
  xcrun notarytool submit "$ZIP" --keychain-profile "$LEDGER_NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP"
  rm -f "$ZIP" && ditto -c -k --keepParent "$APP" "$ZIP"
  echo "Notarized and stapled"
fi
echo "Built $ZIP"
