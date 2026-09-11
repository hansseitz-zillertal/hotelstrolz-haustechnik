"""Shared configuration for the SolarEdge Developer Platform (API v2 / "SolarEdge Connect").

Credentials come from solaredge/.env (never commit that file).

The OAuth2 endpoints below are the ones shown in the app's "OAuth2 Flow - Python"
code example on developer.solaredge.com (Credentials tab). Confirm / adjust
TOKEN_URL and SCOPE against that example if calls fail.
"""
import os
import pathlib

_ENV_PATH = pathlib.Path(__file__).with_name(".env")
_TOKEN_PATH = pathlib.Path(__file__).with_name("token.json")


def _load_env():
    vals = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip()
    return vals


_env = _load_env()

CLIENT_ID = os.environ.get("CLIENT_ID") or _env.get("CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET") or _env.get("CLIENT_SECRET", "")
SITE_ID = os.environ.get("SITE_ID") or _env.get("SITE_ID", "2447278")

# --- OAuth2 (authorization code flow with a local redirect) --------------------
AUTHORIZE_URL = "https://monitoringapi.solaredge.com/v2/authorize"
TOKEN_URL = "https://monitoringapi.solaredge.com/v2/token"
API_BASE = "https://monitoringapi.solaredge.com/v2"

# Must exactly match a redirect URI registered under Settings -> OAuth Configuration.
REDIRECT_URI = "http://localhost:8765/callback"
REDIRECT_HOST = "localhost"
REDIRECT_PORT = 8765

# Space-separated scopes. The documented code example passes none.
SCOPE = ""

# The documented example (requests_oauthlib) uses a plain authorization-code flow
# without PKCE. Flip to True only if the token exchange complains about a missing
# code_verifier / code_challenge.
USE_PKCE = False

TOKEN_PATH = _TOKEN_PATH
