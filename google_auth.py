"""Real Google sign-in for Ledger (OAuth 2.0 desktop flow with PKCE, standard library only).

Setup (once, by the app owner):
  1. Google Cloud Console -> create a project -> APIs & Services -> Credentials.
  2. Create an OAuth client ID of type "Desktop app".
  3. Put the values in google_config.json next to the game:
       {"client_id": "...apps.googleusercontent.com", "client_secret": "..."}
Only the Google account id and display name are kept; the email is never stored.
"""
import base64, hashlib, json, os, secrets, ssl, threading, time, urllib.parse, urllib.request, webbrowser

try:
    import certifi
    # python.org's Python on macOS ships without trusted root certificates, so HTTPS calls to
    # Google fail with CERTIFICATE_VERIFY_FAILED. certifi supplies a known-good bundle.
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()
from http.server import BaseHTTPRequestHandler, HTTPServer

# In the packaged app PyInstaller unpacks bundled files into sys._MEIPASS; from source, look next to this file.
_HERE = getattr(__import__("sys"), "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(_HERE, "google_config.json")
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# status: idle | waiting | done | error
result = {"status": "idle", "message": "", "sub": "", "name": ""}


def _valid(cfg):
    cid, sec = str(cfg.get("client_id", "")), str(cfg.get("client_secret", ""))
    return bool(cid and sec) and "PASTE" not in cid and "PASTE" not in sec and cid.endswith(".apps.googleusercontent.com") and "-" in cid


def _candidate_files():
    yield CONFIG_PATH
    # Google's "Download JSON" file (client_secret_....json) also works if placed next to the game.
    try:
        names = sorted(os.listdir(_HERE))
    except OSError:
        return
    for n in names:
        if n.startswith("client_secret") and n.endswith(".json"):
            yield os.path.join(_HERE, n)


def load_config():
    for path in _candidate_files():
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        cfg = data.get("installed") or data.get("web") or data
        if isinstance(cfg, dict) and _valid(cfg):
            return cfg
    return None


def is_configured():
    return load_config() is not None


def _set(**kw):
    result.update(kw)


def _run(cfg):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    expected_state = secrets.token_urlsafe(16)
    box = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q or "error" in q:
                box.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body style='font-family:sans-serif;text-align:center;margin-top:80px'>"
                             b"<h2>You're signed in!</h2><p>You can close this tab and go back to Ledger.</p></body></html>")

        def log_message(self, *a):
            pass

    try:
        server = HTTPServer(("127.0.0.1", 0), Handler)
        server.timeout = 1.0
        redirect = f"http://127.0.0.1:{server.server_port}"
        params = {
            "client_id": cfg["client_id"], "redirect_uri": redirect, "response_type": "code",
            "scope": "openid profile", "state": expected_state,
            "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account",
        }
        webbrowser.open(AUTH_URL + "?" + urllib.parse.urlencode(params))
        deadline = time.time() + 180
        while time.time() < deadline and "code" not in box and "error" not in box:
            server.handle_request()
        server.server_close()
        if "code" not in box or box.get("state") != expected_state:
            _set(status="error", message="Google sign-in was cancelled or timed out.")
            return
        data = urllib.parse.urlencode({
            "code": box["code"], "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
            "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier,
        }).encode()
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data), timeout=15, context=SSL_CONTEXT) as r:
            token = json.load(r)["access_token"]
        req = urllib.request.Request(USERINFO_URL, headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as r:
            info = json.load(r)
        _set(status="done", sub=str(info.get("sub", "")), name=str(info.get("given_name") or info.get("name") or "Trader"))
    except Exception as exc:  # network, bad credentials, etc.
        _set(status="error", message=f"Google sign-in failed ({type(exc).__name__}). Try again.")


def start():
    """Begin sign-in in a background thread. Returns an error string, or '' if started."""
    cfg = load_config()
    if not cfg:
        return "Google sign-in isn't set up yet. Download the JSON from Google and put it in the Ledger folder."
    if result["status"] == "waiting":
        return ""
    _set(status="waiting", message="Finish signing in in your browser...", sub="", name="")
    threading.Thread(target=_run, args=(cfg,), daemon=True).start()
    return ""


def take_result():
    """Return the finished result once (then reset), or None while idle/waiting."""
    if result["status"] in ("done", "error"):
        out = dict(result)
        _set(status="idle", message="", sub="", name="")
        return out
    return None
