#!/usr/bin/env python3
"""SolarEdge Developer Platform (API v2) client with automatic token refresh.

Requires solaredge/token.json (created once by auth.py).

    python3 client.py sites                 # list authorized sites
    python3 client.py overview              # overview for SITE_ID from .env
    python3 client.py energy 2026-09-01 2026-09-06 [DAY|HOUR|QUARTER_HOUR]
    python3 client.py power  2026-09-06T00:00:00Z 2026-09-06T23:59:59Z
    python3 client.py raw /sites/<id>/overview

Stdlib only. Endpoint paths follow the API v2 docs (api-docs.solaredge.com);
adjust in the methods below if a path 404s.
"""
import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import config

_REFRESH_SKEW = 120  # refresh this many seconds before expiry


class SolarEdgeClient:
    def __init__(self):
        self._tok = json.loads(config.TOKEN_PATH.read_text())

    # --- token handling ------------------------------------------------------
    def _expired(self):
        exp = self._tok.get("expires_in")
        got = self._tok.get("obtained_at", 0)
        if not exp:
            return False
        return time.time() >= got + exp - _REFRESH_SKEW

    def _refresh(self):
        rt = self._tok.get("refresh_token")
        if not rt:
            sys.exit("token.json hat kein refresh_token - auth.py erneut ausführen.")
        form = {
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": config.CLIENT_ID,
            "client_secret": config.CLIENT_SECRET,
        }

        def _post(extra_headers=None):
            req = urllib.request.Request(
                config.TOKEN_URL,
                data=urllib.parse.urlencode(form).encode(),
                method="POST",
            )
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            req.add_header("Accept", "application/json")
            for k, v in (extra_headers or {}).items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())

        try:
            new = _post()
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            basic = base64.b64encode(
                ("%s:%s" % (config.CLIENT_ID, config.CLIENT_SECRET)).encode()
            ).decode()
            form.pop("client_secret", None)
            new = _post({"Authorization": "Basic " + basic})
        new.setdefault("refresh_token", rt)  # some servers omit it on refresh
        new["obtained_at"] = int(time.time())
        self._tok = new
        config.TOKEN_PATH.write_text(json.dumps(new, indent=2))

    def _auth_header(self):
        if self._expired():
            self._refresh()
        return "Bearer " + self._tok["access_token"]

    # --- HTTP --------------------------------------------------------------
    def get(self, path, params=None, _retried=False):
        url = config.API_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", self._auth_header())
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 401 and not _retried:
                self._refresh()
                return self.get(path, params, _retried=True)
            raise SystemExit("HTTP %s auf %s\n%s" % (e.code, url, e.read().decode()))

    # --- convenience -----------------------------------------------------
    def sites(self):
        return self.get("/sites")

    def overview(self, site_id=None):
        return self.get("/sites/%s/overview" % (site_id or config.SITE_ID))

    def energy(self, start, end, resolution="DAY", site_id=None):
        return self.get("/sites/%s/energy" % (site_id or config.SITE_ID),
                        {"from": start, "to": end, "resolution": resolution})

    def power(self, start, end, site_id=None):
        return self.get("/sites/%s/power" % (site_id or config.SITE_ID),
                        {"from": start, "to": end})


def main(argv):
    if not argv:
        print(__doc__)
        return
    c = SolarEdgeClient()
    cmd = argv[0]
    if cmd == "sites":
        out = c.sites()
    elif cmd == "overview":
        out = c.overview()
    elif cmd == "energy":
        res = argv[3] if len(argv) > 3 else "DAY"
        out = c.energy(argv[1], argv[2], res)
    elif cmd == "power":
        out = c.power(argv[1], argv[2])
    elif cmd == "raw":
        out = c.get(argv[1])
    else:
        sys.exit("unbekanntes Kommando: %s" % cmd)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
