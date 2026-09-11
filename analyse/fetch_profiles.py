#!/usr/bin/env python3
"""Zieht die PAC2200-Lastprofile (yearly/monthly/daily) und legt sie als JSON ab."""
import json, os, urllib.request, datetime as dt

HOST = os.environ.get("PAC2200_HOST", "192.168.40.73")
OUT = os.path.dirname(os.path.abspath(__file__))

def get(t, count):
    url = "http://%s/data.json?type=%s&count=%d" % (HOST, t, count)
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode())[t]

for t, c in [("YEARLYPROFILE", 10), ("MONTHLYPROFILE", 40), ("DAILYPROFILE", 800)]:
    p = get(t, c)
    path = os.path.join(OUT, t.lower() + ".json")
    json.dump(p, open(path, "w"), indent=1)
    rows = p["data"]
    print("%s: %d rows  %s .. %s" % (t, len(rows), rows[-1]["TS"][:10], rows[0]["TS"][:10]))
