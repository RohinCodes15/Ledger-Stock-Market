# Publishing checklist

Done in code:
- [x] Salted scrypt passwords; old plain-text and SHA-256 passwords upgrade automatically on login
- [x] Login and PIN guessing is slowed down (5 tries, then a 60 s wait)
- [x] Username and nickname filter (slurs, profanity, bullying phrases, phone numbers, websites)
- [x] Age check at sign-up; under 13 needs a parent PIN + consent
- [x] Parent View locked by PIN; daily time limit; "Forgot password?" reset with the PIN
- [x] Download my data / Delete my account
- [x] Block, remove and unblock friends; unsafe old usernames are hidden on boards
- [x] Kid-safe filter on live news headlines (live data is currently off)
- [x] Colorblind-friendly colors and a less-motion setting
- [x] Version number, optional update check, problem-report file viewable from Settings
- [x] App icon, bundle ID, version in Info.plist, Google config bundled
- [x] Account file saved atomically (a crash mid-save can't wipe accounts)

Needs you (accounts, money or decisions):
1. **Apple Developer Program** ($99/yr) → create a "Developer ID Application" certificate, then
   `xcrun notarytool store-credentials ledger-notary`, set `LEDGER_SIGN_ID` and
   `LEDGER_NOTARY_PROFILE`, and run `./build_app.sh`. Without this, macOS warns players on first open.
2. **Windows**: build on a Windows PC with `pyinstaller Ledger.spec`. Signing needs a code-signing
   certificate, otherwise SmartScreen shows a warning.
3. **Google sign-in**: in Google Cloud Console → OAuth consent screen, publish the app to
   "In production" (testing mode only allows 100 listed test users) and complete verification.
   Or remove the Google buttons if you don't need them.
4. **Privacy policy**: fill in the date and contact in `PRIVACY.md`, have it reviewed, and host it
   somewhere public (your download page).
5. **Update check**: host a JSON file like `{"latest": "1.0.1", "download": "https://..."}` and set
   `UPDATE_URL` in `ledger_game.py`.
6. **Where to publish**: itch.io is the easiest for a free desktop game (upload the zip).
7. **If you turn on live market data** (`live_mode`): use a licensed data provider instead of
   Yahoo Finance's unofficial endpoints.

Bigger projects (separate decisions):
- Online accounts, so friends and leaderboards work across computers (needs a server, e.g. Supabase or
  Firebase), plus reporting players and moderation. Online accounts for under-13s bring in full
  COPPA obligations (verifiable parental consent).
- A web version for phones, tablets and school Chromebooks.
- Classroom mode (teacher-created classes and class leaderboards).
