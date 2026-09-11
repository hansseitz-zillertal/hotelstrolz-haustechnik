#!/usr/bin/env python3
"""Read the boiler Shelly Pro 3EM energy meters over their local HTTP RPC API.

All three boilers are Shelly Pro 3EM (SPEM-003CEBEU, gen 2, "triphase" profile,
no auth). Reachable from the Mac:

    Boiler Haupthaus    192.168.40.159
    Boiler Villa        192.168.2.139
    Boiler Gartenhaus   192.168.40.66

    EM.GetStatus?id=0      -> live power  (total_act_power W, per-phase, voltages)
    EMData.GetStatus?id=0  -> energy accumulators (total_act Wh, total_act_ret Wh)

Usage:
    python3 shelly.py                 # one snapshot of all boilers, human readable
    python3 shelly.py --json          # same as JSON
    python3 shelly.py 192.168.40.66   # just one device

Stdlib only.
"""
import json
import sys
import urllib.request

BOILERS = {
    "haupthaus": "192.168.40.159",
    "villa": "192.168.2.139",
    "gartenhaus": "192.168.40.66",
}

TIMEOUT = 6


def _rpc(ip, method, params=""):
    url = "http://%s/rpc/%s" % (ip, method)
    if params:
        url += "?" + params
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def read_boiler(ip):
    """Return dict: power_w, energy_kwh (consumed), plus per-phase power."""
    em = _rpc(ip, "EM.GetStatus", "id=0")
    emd = _rpc(ip, "EMData.GetStatus", "id=0")
    return {
        "ip": ip,
        "power_w": round(em.get("total_act_power", 0.0), 1),
        "p_a": round(em.get("a_act_power", 0.0), 1),
        "p_b": round(em.get("b_act_power", 0.0), 1),
        "p_c": round(em.get("c_act_power", 0.0), 1),
        "current_a": round(em.get("total_current", 0.0), 2),
        "energy_kwh": round(emd.get("total_act", 0.0) / 1000.0, 3),
    }


def snapshot():
    out = {}
    for name, ip in BOILERS.items():
        try:
            out[name] = read_boiler(ip)
        except Exception as e:
            out[name] = {"ip": ip, "error": str(e)}
    return out


def main(argv):
    if argv and not argv[0].startswith("-"):
        print(json.dumps(read_boiler(argv[0]), indent=2))
        return
    snap = snapshot()
    if "--json" in argv:
        print(json.dumps(snap, indent=2))
        return
    total = 0.0
    for name, d in snap.items():
        if "error" in d:
            print("%-11s %s  ERROR %s" % (name, d["ip"], d["error"]))
            continue
        total += d["power_w"]
        print("%-11s %-15s %8.0f W   %10.1f kWh"
              % (name, d["ip"], d["power_w"], d["energy_kwh"]))
    print("%-11s %-15s %8.0f W" % ("SUMME", "", total))


if __name__ == "__main__":
    main(sys.argv[1:])
