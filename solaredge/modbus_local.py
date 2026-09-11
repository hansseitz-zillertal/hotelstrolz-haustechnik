#!/usr/bin/env python3
"""Poll the SolarEdge inverters locally over SunSpec Modbus TCP and log to CSV.

No cloud, no API key, no OAuth - reads the inverters directly on the LAN.
Requires Modbus TCP enabled on each inverter (SetApp -> Site Communication ->
Modbus TCP, port 502) and a route to the 192.168.40.x network.

Discovered on site (06.09.2026):
    192.168.40.35  unit 2   SE12.5K  + SolarEdge grid meter (Export+Import)
    192.168.40.42  unit 1   SE25K
    192.168.40.51  ...      Modbus TCP NOT yet enabled
    192.168.40.37  ...      Modbus TCP NOT yet enabled

Usage:
    python3 modbus_local.py --once       # one sample, human readable + CSV line
    python3 modbus_local.py               # loop, one sample every 60 s
    python3 modbus_local.py --interval 30 --hours 24
    python3 modbus_local.py --scan        # walk the SunSpec model chain of each

CSV goes to ~/solaredge-log/ (local disk, NOT iCloud). Stdlib only.
"""
import argparse
import csv
import datetime as dt
import os
import socket
import struct
import sys
import time

LOG_DIR = os.path.expanduser("~/solaredge-log")
PORT = 502

INVERTERS = [
    {"name": "wr1", "ip": "192.168.40.35", "unit": 2, "meter": True},
    {"name": "wr2", "ip": "192.168.40.42", "unit": 1, "meter": False},
    {"name": "wr3", "ip": "192.168.40.51", "unit": 1, "meter": False},
    {"name": "wr4", "ip": "192.168.40.37", "unit": 1, "meter": False},
]

INV_MODELS = {101, 102, 103, 111, 112, 113}
METER_MODELS = {201, 202, 203, 204, 211, 212, 213, 214}

STATE = {1: "OFF", 2: "SLEEP", 3: "STARTING", 4: "MPPT", 5: "THROTTLED",
         6: "SHUTTING_DOWN", 7: "FAULT", 8: "STANDBY"}


# --- Modbus TCP (function 3 only) --------------------------------------------
class Modbus:
    def __init__(self, ip, unit, timeout=8.0):
        self.ip, self.unit, self.timeout = ip, unit, timeout
        self.sock = None

    def __enter__(self):
        self.sock = socket.create_connection((self.ip, PORT), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        return self

    def __exit__(self, *a):
        try:
            self.sock.close()
        except Exception:
            pass

    def read(self, start, count):
        pdu = struct.pack(">BHH", 3, start, count)
        self.sock.sendall(struct.pack(">HHHB", 1, 0, len(pdu) + 1, self.unit) + pdu)
        buf = b""
        while len(buf) < 9:
            buf += self.sock.recv(2048)
        if buf[7] & 0x80:
            raise IOError("modbus exception %d @%d" % (buf[8], start))
        nbytes = buf[8]
        while len(buf) < 9 + nbytes:
            buf += self.sock.recv(2048)
        time.sleep(0.15)  # SolarEdge Modbus is slow; don't hammer it
        return buf[9:9 + nbytes]


def _u16(b, i):
    return struct.unpack(">H", b[i * 2:i * 2 + 2])[0]


def _s16(b, i):
    v = _u16(b, i)
    return v - 0x10000 if v >= 0x8000 else v


def _s16_opt(b, i):
    """int16 that treats the SunSpec 'not implemented' value 0x8000 as None."""
    v = _u16(b, i)
    if v == 0x8000:
        return None
    return v - 0x10000 if v >= 0x8000 else v


def _acc32(b, i):
    v = struct.unpack(">I", b[i * 2:i * 2 + 4])[0]
    return None if v in (0, 0xFFFFFFFF) else v


def _scaled(val, sf):
    if val is None:
        return None
    r = val * (10 ** sf)
    return round(r, 2) if isinstance(r, float) else r


# --- SunSpec model discovery ------------------------------------------------
def find_models(mb):
    """Return {'inv': addr, 'meter': addr or None} of the SunSpec model headers."""
    hdr = mb.read(40000, 2)
    if hdr[:4] != b"SunS":
        raise IOError("no SunSpec marker at 40000")
    addr, out = 40002, {"inv": None, "meter": None}
    for _ in range(20):
        d = mb.read(addr, 2)
        mid, mlen = struct.unpack(">HH", d)
        if mid in (0, 0xFFFF):
            break
        if mid in INV_MODELS and out["inv"] is None:
            out["inv"] = addr
        elif mid in METER_MODELS and out["meter"] is None:
            out["meter"] = addr
        addr += 2 + mlen
    if out["inv"] is None:
        raise IOError("no inverter model found")
    return out


def read_inverter(mb, addr):
    d = mb.read(addr, 2 + 52)
    b = d[4:]
    return {
        "ac_w": _scaled(_s16(b, 12), _s16(b, 13)),
        "hz": _scaled(_u16(b, 14), _s16(b, 15)),
        "ac_va": _scaled(_s16(b, 16), _s16(b, 17)),
        "ac_var": _scaled(_s16(b, 18), _s16(b, 19)),
        "pf": _scaled(_s16(b, 20), _s16(b, 21)),
        "wh_life": _scaled(_acc32(b, 22), _s16(b, 24)),
        "dc_v": _scaled(_u16(b, 27), _s16(b, 28)),
        "dc_w": _scaled(_s16(b, 29), _s16(b, 30)),
        "temp": _scaled(_s16_opt(b, 33) if _s16_opt(b, 31) is None else _s16(b, 31),
                        _s16(b, 35)),
        "state": STATE.get(_u16(b, 36), str(_u16(b, 36))),
    }


def read_meter(mb, addr):
    d = mb.read(addr, 2 + 105)
    b = d[4:]
    return {
        "m_w": _scaled(_s16(b, 16), _s16(b, 20)),
        "m_hz": _scaled(_s16(b, 14), _s16(b, 15)),
        "m_pf": _scaled(_s16(b, 31), _s16(b, 35)),
        "m_wh_exp": _scaled(_acc32(b, 36), _s16(b, 52)),
        "m_wh_imp": _scaled(_acc32(b, 44), _s16(b, 52)),
    }


def sample_one(inv):
    row = {}
    with Modbus(inv["ip"], inv["unit"]) as mb:
        models = find_models(mb)
        row.update(read_inverter(mb, models["inv"]))
        if inv.get("meter") and models["meter"]:
            row.update(read_meter(mb, models["meter"]))
    return row


# --- CSV ------------------------------------------------------------------
def build_fields():
    f = ["ts"]
    inv_keys = ["ac_w", "dc_w", "dc_v", "hz", "ac_va", "ac_var", "pf",
                "wh_life", "temp", "state"]
    for inv in INVERTERS:
        f += ["%s_%s" % (inv["name"], k) for k in inv_keys]
        if inv.get("meter"):
            f += ["%s_%s" % (inv["name"], k)
                  for k in ("m_w", "m_hz", "m_pf", "m_wh_exp", "m_wh_imp")]
    f += ["total_ac_w", "n_ok"]
    return f


def collect():
    ts = dt.datetime.now().replace(microsecond=0).isoformat()
    out = {"ts": ts}
    total, n_ok = 0.0, 0
    for inv in INVERTERS:
        try:
            r = sample_one(inv)
            n_ok += 1
            if r.get("ac_w") is not None:
                total += r["ac_w"]
            for k, v in r.items():
                out["%s_%s" % (inv["name"], k)] = v
        except Exception as e:
            out["%s_state" % inv["name"]] = "ERR:%s" % e
    out["total_ac_w"] = round(total)
    out["n_ok"] = n_ok
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--hours", type=float, default=None)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--csv", default=None)
    args = ap.parse_args(argv)

    if args.scan:
        for inv in INVERTERS:
            print("=== %s %s unit %d ===" % (inv["name"], inv["ip"], inv["unit"]))
            try:
                with Modbus(inv["ip"], inv["unit"]) as mb:
                    addr = 40002
                    for _ in range(20):
                        d = mb.read(addr, 2)
                        mid, mlen = struct.unpack(">HH", d)
                        if mid in (0, 0xFFFF):
                            break
                        print("  model %-4d len %-4d @%d" % (mid, mlen, addr))
                        addr += 2 + mlen
            except Exception as e:
                print("  ERR %s" % e)
        return

    if args.once:
        row = collect()
        for k, v in row.items():
            print("%-20s %s" % (k, v))
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    path = args.csv or os.path.join(
        LOG_DIR, "solaredge_%s.csv" % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    fields = build_fields()
    new = not os.path.exists(path)
    stop = None if args.hours is None else time.time() + args.hours * 3600
    print("Logging to %s  (every %.0f s, Ctrl-C to stop)" % (path, args.interval))
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        while True:
            t0 = time.time()
            row = collect()
            w.writerow(row)
            fh.flush()
            print("%s  total=%6s W  ok=%d/%d"
                  % (row["ts"], row["total_ac_w"], row["n_ok"], len(INVERTERS)))
            if stop and time.time() >= stop:
                break
            time.sleep(max(1.0, args.interval - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped")
