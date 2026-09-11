#!/usr/bin/env python3
"""One-time OAuth2 authorization for the SolarEdge Developer Platform.

Run this once (on a machine with a browser). It:
  1. opens the SolarEdge consent screen in your browser,
  2. catches the redirect on http://localhost:8765/callback,
  3. exchanges the code for an access + refresh token,
  4. writes solaredge/token.json.

The site owner must click "Approve" on the consent screen. After that the site
shows up under the app's "Sites" tab and client.py can pull data headless,
refreshing the access token automatically via the stored refresh token.

    python3 auth.py

Stdlib only.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request
import webbrowser

import config

_result = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        _result.update(urllib.parse.parse_qs(parsed.query))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "code" in _result
        msg = "Authorisierung erfolgreich - Fenster kann geschlossen werden." if ok \
            else "Fehler: %s" % _result.get("error", ["unbekannt"])[0]
        self.wfile.write(("<html><body><h2>%s</h2></body></html>" % msg).encode())

    def log_message(self, *a):  # silence
        pass


def _pkce():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _post_form(url, data, headers=None):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def main():
    if not config.CLIENT_ID or not config.CLIENT_SECRET:
        sys.exit("CLIENT_ID / CLIENT_SECRET fehlen in solaredge/.env")

    state = secrets.token_urlsafe(16)
    verifier = challenge = None

    params = {
        "response_type": "code",
        "client_id": config.CLIENT_ID,
        "redirect_uri": config.REDIRECT_URI,
        "state": state,
    }
    if getattr(config, "USE_PKCE", False):
        verifier, challenge = _pkce()
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    if config.SCOPE:
        params["scope"] = config.SCOPE
    auth_url = config.AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)

    httpd = http.server.HTTPServer((config.REDIRECT_HOST, config.REDIRECT_PORT), _Handler)

    print("Öffne Consent-Screen im Browser ...")
    print("Falls nichts passiert, öffne diese URL manuell:\n  " + auth_url + "\n")
    webbrowser.open(auth_url)

    # serve requests until we get code or error
    while "code" not in _result and "error" not in _result:
        httpd.handle_request()

    if "error" in _result:
        sys.exit("Autorisierung fehlgeschlagen: %s / %s" % (
            _result.get("error"), _result.get("error_description")))
    if _result.get("state", [None])[0] != state:
        sys.exit("state stimmt nicht - Abbruch (CSRF-Schutz).")

    code = _result["code"][0]
    print("Code erhalten, tausche gegen Token ...")

    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.REDIRECT_URI,
        "client_id": config.CLIENT_ID,
        "client_secret": config.CLIENT_SECRET,
    }
    if verifier:
        form["code_verifier"] = verifier
    status, tok = _post_form(config.TOKEN_URL, form)
    if status == 401:
        # retry with HTTP Basic client auth instead of body credentials
        basic = base64.b64encode(
            ("%s:%s" % (config.CLIENT_ID, config.CLIENT_SECRET)).encode()
        ).decode()
        form.pop("client_secret", None)
        status, tok = _post_form(config.TOKEN_URL, form,
                                 headers={"Authorization": "Basic " + basic})
    if status >= 400 or "access_token" not in tok:
        sys.exit("Token-Tausch fehlgeschlagen (%s): %s" % (status, tok))

    tok["obtained_at"] = int(time.time())
    config.TOKEN_PATH.write_text(json.dumps(tok, indent=2))
    os.chmod(config.TOKEN_PATH, 0o600)
    print("OK -> %s" % config.TOKEN_PATH)
    print("  hat refresh_token: %s" % ("ja" if tok.get("refresh_token") else "NEIN"))


if __name__ == "__main__":
    main()
