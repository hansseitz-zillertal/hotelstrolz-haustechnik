#!/usr/bin/env python3
"""Poll the Siemens SENTRON PAC2200 main meter and log measurements to CSV.

The PAC2200 web UI (http://192.168.40.73) exposes an unauthenticated JSON API:
    GET /data.json?type=<TYPE>
Types used here: INST_VALUES (live V/I/P/Q/PF/f) and OVERVIEW (energy counters).

Usage:
    python3 log.py                 # log forever, one sample every 120 s
    python3 log.py --interval 60   # custom interval in seconds
    python3 log.py --once          # print a single sample as CSV and exit
    python3 log.py --hours 24      # stop after N hours

Data is written to ~/pac2200-log/ (local disk, NOT iCloud) to avoid sync churn.
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.request

HOST = os.environ.get("PAC2200_HOST", "192.168.40.73")
BASE = f"http://{HOST}/data.json"
LOG_DIR = os.path.expanduser("~/pac2200-log")

# CSV columns: local wall-clock timestamp, meter clock, then measured values.
INST_FIELDS = [
    "V_L1", "V_L2", "V_L3", "V_L12", "V_L23", "V_L31",
    "I_L1", "I_L2", "I_L3", "I_N_SEL", "I_AVG",
    "P_L1", "P_L2", "P_L3", "P_SUM",
    "VARQ1_L1", "VARQ1_L2", "VARQ1_L3", "VARQ1_SUM",
    "VA_L1", "VA_L2", "VA_L3", "VA_SUM",
    "PF_L1", "PF_L2", "PF_L3", "PF_SUM",
    "FREQ", "V_LN_AVG", "V_LL_AVG",
]
OVERVIEW_FIELDS = [
    "P_SUM", "VA_SUM", "VARQ1_SUM", "PF_SUM",
    "Import_T1", "Export_T1", "TODAY_T1", "THISMONTH_T1", "ACTUAL_TARIFF",
]
COLUMNS = (
    ["ts_local", "ts_meter"]
    + INST_FIELDS
    + [f"ov_{k}" for k in OVERVIEW_FIELDS]
)


def fetch(dtype, timeout=10):
    url = f"{BASE}?type={dtype}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)[dtype]


def _val(node):
    """PAC values are {"value": x, "unit": "..."}; pass through plain values."""
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def sample():
    inst = fetch("INST_VALUES")
    ov = fetch("OVERVIEW")
    row = {
        "ts_local": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "ts_meter": inst.get("LOCAL_TIME", ""),
    }
    for k in INST_FIELDS:
        row[k] = _val(inst.get(k))
    for k in OVERVIEW_FIELDS:
        row[f"ov_{k}"] = _val(ov.get(k))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=120.0, help="seconds between samples")
    ap.add_argument("--hours", type=float, default=None, help="stop after N hours")
    ap.add_argument("--once", action="store_true", help="one sample to stdout, then exit")
    args = ap.parse_args()

    if args.once:
        w = csv.DictWriter(sys.stdout, fieldnames=COLUMNS)
        w.writeheader()
        w.writerow(sample())
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    start = dt.datetime.now()
    path = os.path.join(LOG_DIR, f"pac2200_{start:%Y%m%d_%H%M%S}.csv")
    deadline = start + dt.timedelta(hours=args.hours) if args.hours else None

    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        f.flush()
        print(f"logging to {path} every {args.interval:g}s"
              + (f" until {deadline:%Y-%m-%d %H:%M}" if deadline else " (until stopped)"),
              flush=True)
        n = 0
        while deadline is None or dt.datetime.now() < deadline:
            t0 = time.time()
            try:
                row = sample()
                w.writerow(row)
                f.flush()
                n += 1
                print(f"[{n}] {row['ts_local']}  P_sum={row['P_SUM']:>8} kW  "
                      f"Q_sum={row['VARQ1_SUM']:>8} kvar  PF={row['PF_SUM']}", flush=True)
            except Exception as e:  # noqa: BLE001 - keep logging through transient errors
                print(f"[err] {dt.datetime.now().isoformat(timespec='seconds')}: {e}", flush=True)
            time.sleep(max(0.0, args.interval - (time.time() - t0)))
    print(f"done: {n} samples in {path}", flush=True)


if __name__ == "__main__":
    main()
