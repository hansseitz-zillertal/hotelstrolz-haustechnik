#!/usr/bin/env python3
"""Kombi-Logger fuer die Power-to-Heat-Anlage.

Schreibt im festen Takt eine CSV-Zeile mit:
  - Netz-Leistung am PAC2200 (P_SUM, negativ = Einspeisung) + Zaehlerstaende
  - Leistung + kWh-Zaehler je Boiler-Shelly (Pro 3EM)
  - abgeleitet: aktuelle Einspeisung, aktueller Netzbezug, Summe Boiler-Leistung

Damit laesst sich auswerten, wie viel PV-Ueberschuss die Boiler schon abfangen
und wie viel noch ins Netz geht - Grundlage fuer die Batterie-Entscheidung.

    python3 ueberschuss_log.py --once
    python3 ueberschuss_log.py                 # Schleife, alle 60 s
    python3 ueberschuss_log.py --interval 30 --hours 24

CSV -> ~/ptheat-log/ (lokale Platte, nicht iCloud). Nur stdlib.
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "shelly"))
import shelly  # noqa: E402

PAC_HOST = os.environ.get("PAC2200_HOST", "192.168.40.73")      # Hauptzähler (Netz)
PAC_WR34_HOST = os.environ.get("PAC2200_WR34_HOST", "192.168.40.72")  # Produktion WR3+4
LOG_DIR = os.path.expanduser("~/ptheat-log")
BOILERS = list(shelly.BOILERS)  # haupthaus, villa, gartenhaus


def _overview(host):
    url = "http://%s/data.json?type=OVERVIEW" % host
    with urllib.request.urlopen(url, timeout=6) as r:
        ov = json.loads(r.read().decode())["OVERVIEW"]

    def val(k):
        x = ov.get(k)
        return x["value"] if isinstance(x, dict) else x

    return ov, val


def pac_overview():
    ov, val = _overview(PAC_HOST)
    p_sum = val("P_SUM")
    if p_sum is None:
        p_sum = sum(val("P_L%d" % i) or 0.0 for i in (1, 2, 3))
    return {
        "pac_time": ov.get("LOCAL_TIME"),
        "grid_w": round(p_sum * 1000.0),          # negativ = Einspeisung
        "import_kwh": val("Import_T1"),
        "export_kwh": val("Export_T1"),
        "today_kwh": val("TODAY_T1"),
    }


def pac_wr34():
    """2. PAC2200: misst die Produktion von WR3 + WR4 (Export_T1 = erzeugte kWh)."""
    ov, val = _overview(PAC_WR34_HOST)
    p_sum = val("P_SUM")
    if p_sum is None:
        p_sum = sum(val("P_L%d" % i) or 0.0 for i in (1, 2, 3))
    return {
        "pv_wr34_w": round(-p_sum * 1000.0),      # P_SUM negativ bei Erzeugung -> +W
        "pv_wr34_kwh": val("Export_T1"),
    }


def collect():
    ts = dt.datetime.now().replace(microsecond=0).isoformat()
    row = {"ts": ts}
    try:
        row.update(pac_overview())
    except Exception as e:
        row["pac_time"] = "ERR:%s" % e
    try:
        row.update(pac_wr34())
    except Exception as e:
        row["pv_wr34_w"] = "ERR:%s" % e

    snap = shelly.snapshot()
    boiler_total = 0.0
    for name in BOILERS:
        d = snap.get(name, {})
        if "error" in d:
            row["b_%s_w" % name] = None
            row["b_%s_kwh" % name] = None
        else:
            row["b_%s_w" % name] = d["power_w"]
            row["b_%s_kwh" % name] = d["energy_kwh"]
            boiler_total += d["power_w"]
    row["boiler_total_w"] = round(boiler_total)

    g = row.get("grid_w")
    if isinstance(g, (int, float)):
        row["einspeisung_w"] = max(0, -g)
        row["bezug_w"] = max(0, g)
    return row


FIELDS = (["ts", "pac_time", "grid_w", "einspeisung_w", "bezug_w",
           "import_kwh", "export_kwh", "today_kwh", "pv_wr34_w", "pv_wr34_kwh"]
          + sum([["b_%s_w" % n, "b_%s_kwh" % n] for n in BOILERS], [])
          + ["boiler_total_w"])


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--hours", type=float, default=None)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--csv", default=None)
    args = ap.parse_args(argv)

    if args.once:
        row = collect()
        for k in FIELDS:
            print("%-16s %s" % (k, row.get(k)))
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    path = args.csv or os.path.join(
        LOG_DIR, "ptheat_%s.csv" % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    new = not os.path.exists(path)
    stop = None if args.hours is None else time.time() + args.hours * 3600
    print("Log -> %s  (alle %.0f s, Ctrl-C zum Stoppen)" % (path, args.interval))
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        while True:
            t0 = time.time()
            row = collect()
            w.writerow(row)
            fh.flush()
            print("%s  Netz=%+7s W  Einsp=%6s W  Boiler=%6s W"
                  % (row["ts"], row.get("grid_w"), row.get("einspeisung_w"),
                     row.get("boiler_total_w")))
            if stop and time.time() >= stop:
                break
            time.sleep(max(1.0, args.interval - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ngestoppt")
