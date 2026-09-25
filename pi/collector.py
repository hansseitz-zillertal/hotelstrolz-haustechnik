#!/usr/bin/env python3
"""Zentraler Poller fuer die Solar-/Power-to-Heat-Anlage -> InfluxDB.

Quellen (alle lokal im 192.168.40.x-Netz, keine Cloud):
  - PAC2200 .73  "Hauptzaehler"   : Netzbezug/-einspeisung des Hotels
  - PAC2200 .72  "WR3+4"          : AC-Produktion Wechselrichter 3 + 4
  - SolarEdge WR .35 / .42        : SunSpec Modbus TCP (WR1 = SE12.5K + Zaehler, WR2 = SE25K)
  - 3x Shelly Pro 3EM            : Boiler-Verbrauch Haupthaus / Villa / Gartenhaus

Schreibt Line Protocol per HTTP an InfluxDB 2.x. Konfiguration: /etc/solar-collector.env
(oder Umgebungsvariablen). Nur Python-Standardbibliothek.

    python3 collector.py --once        # einmal messen, Line Protocol nach stdout
    python3 collector.py               # Dauerlauf (INTERVAL s, default 30)
"""
import argparse
import json
import os
import socket
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- Konfig
def _env(path="/etc/solar-collector.env"):
    # Als systemd-Service kommen die Variablen schon via EnvironmentFile; dieses
    # Nachlesen ist nur fuer den Standalone-Aufruf. Fehlt/verschlossen -> egal.
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


_env()

INFLUX_URL = os.environ.get("INFLUX_URL", "http://localhost:8086")
INFLUX_ORG = os.environ.get("INFLUX_ORG", "strolz")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "solar")
INFLUX_TOKEN = os.environ.get("INFLUX_TOKEN", "")
INTERVAL = float(os.environ.get("INTERVAL", "30"))

PAC_GRID = os.environ.get("PAC_GRID_HOST", "192.168.40.73")
# PAC .72 (WR3+4 kombiniert) wird nicht mehr gepollt - alle 4 WR jetzt einzeln
# per Modbus. PAC .72 bleibt als HTTP-Reserve, falls Modbus wr3/wr4 zickt.
PAC_WR34 = os.environ.get("PAC_WR34_HOST", "")

INVERTERS = [
    {"name": "wr1", "ip": "192.168.40.35", "unit": 2, "meter": True},   # SE12.5K + Zaehler
    {"name": "wr2", "ip": "192.168.40.42", "unit": 1, "meter": False},  # SE25K
    {"name": "wr3", "ip": "192.168.40.51", "unit": 1, "meter": False},  # SE25K
    {"name": "wr4", "ip": "192.168.40.37", "unit": 1, "meter": False},  # SE25K
]
BOILERS = {                          # Shelly Pro 3EM (EM.GetStatus)
    "haupthaus": "192.168.40.159",
    "villa": "192.168.2.139",
    "gartenhaus": "192.168.40.66",
}

# Weitere gemessene Verbraucher -> measurement "consumer".
CONSUMERS_3EM = {                     # Shelly 3EM / Pro 3EM (EM.GetStatus)
    "kuehlung": "192.168.40.59",
}
CONSUMERS_PLUG = {                    # Shelly Plug S Gen3 (Switch.GetStatus)
    "eismaschine": "192.168.40.36",
    "bierkuehler": "192.168.40.121",
    # Unterzaehler: sitzen HINTER dem kuehlung-3EM (.59), also schon in dessen
    # Summe enthalten -> nur zur Aufschluesselung, nie zusaetzlich aufsummieren.
    "kuehlung_begleit": "192.168.40.192",
    "kuehlung_luefter": "192.168.40.133",
}
EM_METERS = {                        # Shelly Pro EM 50 (2 CT-Kanaele), ip -> {kanal: name}
    "192.168.40.140": {0: "klima_privat", 1: "klima_wr34"},   # verifiziert 06.09. (Klima-Test)
}

# BLU-Sensoren (BTHome v2) ueber die BLE-Cloud-Relays mehrerer Shellys.
# Die Aussenstation schickt nur EINEN Messwert pro Advertisement (rotierend) ->
# _BLU_STATE sammelt je Geraet+Messwert den letzten Wert + Zeit.
BLU_GATEWAYS = {
    "192.168.40.140": {                       # Shelly Pro EM 50
        "c0:2c:ed:9b:c3:09": "aussen",
        "7c:c6:b6:72:ad:df": "wr_raum",
    },
    "192.168.40.49": {                        # Shelly Outdoor Plug (schwaches WLAN!)
        "f8:44:77:21:33:ed": "vorkuehlraum",
        "f8:44:77:2c:c8:e3": "milchkuehlraum",
        "f8:44:77:3a:da:3b": "fleischkuehlraum",
    },
    "192.168.40.133": {                       # Shelly Plug S G3 (Kondensator-Luefter, Kaeltetechnik-Raum)
        "fc:4d:6a:39:69:e8": "kuehltechnik",
    },
    "192.168.40.123": {                       # Shelly Wall Display (Rezeption), BLE-Gateway (20.09.: feste UniFi-Reservierung auf .123)
        "7c:c6:b6:65:1f:fd": "aussen_nord",   # BLU H&T aussen Nordseite (Schattentemperatur)
        "f8:44:77:21:39:f6": "hausgang",      # BLU H&T Hausgang (Innentemperatur)
    },
    "192.168.40.34": {                        # Shelly Plus 1PM am Pavillon, BLE-Gateway
        "f8:44:77:2b:2c:7e": "pavillon",      # BLU H&T Sonnenterrasse/Pavillon (unter Dach, sonnig)
    },
    "192.168.40.158": {                       # Shelly Plug S G3 (Kueche), BLE-Gateway
        "fc:4d:6a:39:24:32": "kuehlschrank_patisserie",
    },
}
BLU_MAX_AGE = 1800                    # s, aeltere Einzelwerte verwerfen

# Siemens LOGO!8 via S7 (python-snap7). LOGO-VM = DB1, VWn = DB1.DBWn.
# Werte im LOGO-Programm als Integer x10 degC ablegen (z.B. 634 -> 63,4 degC).
# rack/slot fuer LOGO!8 = 0 / 2. Messstelle -> Anzeigename im Dashboard-map.
# "meas" = InfluxDB-Measurement (default "heizung"), fuer eigene Dashboard-Bereiche.
LOGO_S7 = {
    "192.168.40.153": {              # Haupt-LOGO (Heizung)
        "slot": 2,
        "vw": {                     # VW-Byteadresse -> Messstelle
            0: "aussen",
            2: "kessel",
            4: "kessel_soll",
            6: "boiler",
        },
        "bits": {
            "8.0": "boiler",        # NQ: Boiler-Ladepumpe ein/aus
        },
    },
    "192.168.40.155": {              # LOGO 2 (Vorlauf Wohnungen)
        "slot": 2,
        "vw": {
            4: "vl_1og_ost",
            6: "vl_3og",
        },
    },
    "192.168.40.150": {              # LOGO 3 (Vorlauf Steigstraenge)
        "slot": 2,
        "vw": {
            # ACHTUNG: Namen = VW-Kennung (Historie in InfluxDB). Echte Bedeutung (Dashboard, 25.09.):
            # VW4 = Dachgeschoss, VW6 = KG-2.OG OST, VW8 = KG-2.OG WEST
            4: "vl_kg_2og_west",
            6: "vl_kg_2og_ost",
            8: "vl_dg",
        },
    },
    "192.168.40.154": {              # LOGO 4 (Lueftung Kueche) -> eigenes Measurement
        "slot": 2,
        "meas": "lueftung",
        "vw": {
            2: "kueche",
            6: {"name": "klappe", "field": "percent", "scale": 0.1},  # 1000 = 100 %
        },
        "bits": {                   # "VByte.Bit" -> Messstelle, Feld "on" (0/1)
            "12.0": "kueche",       # NQ1 Schaltzustand Lueftung Kueche
            "4.0": "pumpe",         # Pumpe ein/aus
        },
    },
    "192.168.40.157": {              # LOGO 5 (Schwimmbad) -> eigenes Measurement
        "slot": 2,
        "meas": "schwimmbad",
        "vw": {
            4: "becken",
            6: "einlauf",
        },
        "bits": {                   # 3-Punkt-Regelventil Beckenheizung
            "8.0": "ventil_auf",
            "8.1": "ventil_zu",
        },
    },
    "192.168.40.160": {              # LOGO 6 (Villa) -> eigenes Measurement
        "slot": 2,
        "meas": "villa",
        "vw": {
            10: "kessel",
            12: "boiler1",
            14: "boiler2",
            18: "hk1",
            20: "hk2",
        },
        "bits": {
            "22.0": "boiler",       # 1 = beide Boiler ein
            "22.1": "brenner",      # Brenner ein/aus
            "22.2": "ladepumpe",    # Boiler-Ladepumpe ein/aus
        },
    },
    "192.168.40.156": {              # LOGO 7 (Gartenhaus) -> eigenes Measurement
        "slot": 2,
        "meas": "gartenhaus",
        "vw": {
            10: "aussen",
            12: "kessel",
            14: "boiler",
            16: "hk_keller",
            18: "hk_eg",
            20: "hk_og",
        },
        "bits": {
            "22.0": "brenner",
            "22.1": "boilerpumpe",
        },
    },
}
LOGO_VW_SCALE = 0.1                   # VW-Rohwert * SCALE = degC

# --- Lastabwurf: Pi SCHREIBT per S7 in eine LOGO ---------------------------
# vw_ist  <- aktueller Netzbezug (PAC2200 "Leistung Bezug"), in kW * VW_SCALE
# vw_soll <- Abwurf-Sollwert, in kW * VW_SCALE
# LOGO vergleicht selbst (mit Hysterese) und wirft Waschmaschine/Trockner ab.
LOGO_LASTABWURF = {
    "ip": "192.168.40.71",           # Abwurf-LOGO (Waschmaschine/Trockner)
    "slot": 2,
    "vw_ist": 10,
    "vw_soll": 12,
    "scale": 10,                     # 62,3 kW -> 623 (0,1-kW-Aufloesung; wie die PAC-Werte in der LOGO)
    "min_kw": 40,                    # Mindest-Sollwert; darueber = bisherige Monatsspitze (Ratschet)
    "status_bits": {                 # LOGO schreibt zurueck, Pi liest: "VByte.Bit" -> Feld (0/1)
        "14.0": "trockner",
        "14.1": "waschmaschine",
    },
}

# --- Brenner-Stoerungserkennung (Villa/Gartenhaus) --------------------------
# Brenner laeuft (bit "on"=1), aber Kesseltemperatur steigt ueber ein rollierendes
# Fenster nicht ausreichend -> vermutlich Stoerabschaltung/Verriegelung am Brenner,
# waehrend die Waermeanforderung (Brenner-Freigabe) weiter ansteht.
BRENNER_WATCH = {
    "villa": "kessel",
    "gartenhaus": "kessel",
}
BRENNER_WATCH_MIN_ON_S = 20 * 60     # Fensterlaenge: so lange Dauerlauf, bevor bewertet wird
BRENNER_WATCH_MIN_RISE = 0.5         # muss im Fenster mind. so viel gestiegen sein (degC)
_brenner_watch_state = {}            # meas -> {"on_since": ts, "temp0": float, "stoerung": 0}


def check_brenner_stoerung(meas, kessel_temp, brenner_on):
    st = _brenner_watch_state.setdefault(meas, {"on_since": None, "temp0": None, "stoerung": 0})
    now = time.time()
    if not brenner_on:
        st["on_since"] = None
        st["temp0"] = None
        st["stoerung"] = 0
        return 0
    if st["on_since"] is None:
        st["on_since"] = now
        st["temp0"] = kessel_temp
        return st["stoerung"]
    if now - st["on_since"] >= BRENNER_WATCH_MIN_ON_S:
        if kessel_temp is not None and st["temp0"] is not None:
            st["stoerung"] = 0 if (kessel_temp - st["temp0"]) >= BRENNER_WATCH_MIN_RISE else 1
        st["on_since"] = now          # rollierendes Fenster: neu baselinen
        st["temp0"] = kessel_temp
    return st["stoerung"]


REZEPTION_IP = "192.168.40.145"      # Shelly H&T Gen3 (Rezeption): Temp/Feuchte/Batterie.
                                     # Batteriebetrieb -> Deep-Sleep, nur beim Aufwachen
                                     # (Default alle 2 h, oder per USB-C dauerhaft wach) erreichbar.

HTTP_TIMEOUT = 6


# ---------------------------------------------------------------- BLU-Sensoren
_BTHOME = {
    0x00: ("packet_id", 1, 1, False), 0x01: ("battery", 1, 1, False),
    0x02: ("temp_c", 2, 0.01, True), 0x03: ("humidity", 2, 0.01, False),
    0x04: ("pressure_hpa", 3, 0.01, False), 0x05: ("illuminance_lux", 3, 0.01, False),
    0x08: ("dewpoint_c", 2, 0.01, True), 0x0C: ("voltage", 2, 0.001, False),
    0x2E: ("humidity", 1, 1, False), 0x45: ("temp_c", 2, 0.1, True),
    0x46: ("uv_index", 1, 0.1, False), 0x44: ("wind_ms", 2, 0.01, False),
    0x5E: ("wind_dir", 2, 0.01, False), 0x5F: ("precip_mm", 2, 1, False),
    0x57: ("temp_c", 1, 1, True), 0x3F: ("rotation", 2, 0.1, True),
    0x56: ("conductivity", 2, 1, False), 0x60: ("channel", 1, 1, False),
}
_BLU_STATE = {}   # mac -> {metric: (value, ts)}


def _decode_bthome(raw):
    w, i = {}, 1
    while i < len(raw):
        oid = raw[i]
        i += 1
        if oid not in _BTHOME:
            break
        nm, ln, fac, sg = _BTHOME[oid]
        chunk = raw[i:i + ln]
        i += ln
        if len(chunk) < ln:
            break
        v = round(int.from_bytes(chunk, "little", signed=sg) * fac, 3)
        if nm != "packet_id":
            w[nm] = float(v)          # immer float -> keine Typkonflikte in InfluxDB
    return w


def blu_sensors():
    """Liest die BLU-Advertisements von allen Gateways, mergt in _BLU_STATE,
    gibt je Geraet die aktuellen (frischen) Werte zurueck. Ein nicht
    erreichbarer Gateway (z.B. .49 mit schwachem WLAN) blockiert die anderen
    nicht - die gesammelten Werte altern nach BLU_MAX_AGE aus."""
    import base64
    now = time.time()
    errs = []
    for gw, devices in BLU_GATEWAYS.items():
        try:
            with urllib.request.urlopen(
                    "http://%s/rpc/BLE.CloudRelay.ListInfos" % gw,
                    timeout=HTTP_TIMEOUT) as r:
                infos = json.loads(r.read().decode())
        except Exception as e:
            errs.append("%s:%s" % (gw, e))
            continue
        seen = {}
        for entry in infos.get("devices", []):
            for mac, d in entry.items():
                seen[mac.lower()] = d
        for mac in devices:
            d = seen.get(mac)
            if not d:
                continue
            fcd2 = (d.get("sdata") or {}).get("fcd2")
            if fcd2:
                st = _BLU_STATE.setdefault(mac, {})
                for k, v in _decode_bthome(base64.b64decode(fcd2)).items():
                    st[k] = (v, now)

    out = {}
    for gw, devices in BLU_GATEWAYS.items():
        for mac, name in devices.items():
            st = _BLU_STATE.get(mac, {})
            for k in list(st):
                if now - st[k][1] > BLU_MAX_AGE:
                    del st[k]
            if st:
                out[name] = {k: v for k, (v, _) in st.items()}
    return out, errs


def shelly_ht(ip):
    """Shelly H&T Gen3 (S3SN-0U12A). Ein einziger GetStatus-Call; wirft bei Schlaf."""
    with urllib.request.urlopen("http://%s/rpc/Shelly.GetStatus" % ip, timeout=3) as r:
        s = json.loads(r.read().decode())
    out = {}
    t = s.get("temperature:0", {}).get("tC")
    if t is not None:
        out["temp_c"] = float(t)
    h = s.get("humidity:0", {}).get("rh")
    if h is not None:
        out["humidity"] = float(h)
    b = s.get("devicepower:0", {}).get("battery", {}).get("percent")
    if b is not None:
        out["battery"] = float(b)
    if "temp_c" not in out:
        raise ValueError("keine Temperatur im Status")
    return out


_s7_clients = {}     # ip -> snap7 Client (persistent, reconnect bei Fehler)


def logo_temps():
    """Werte aus allen LOGO!8 (S7/DB1). ({meas: {name: {field: val}}}, errs).
    vw -> Feld temp_c (degC), bits -> Feld on (0/1). Braucht python-snap7."""
    import snap7                       # optionale Abhaengigkeit
    out, errs = {}, []
    for ip, cfg in LOGO_S7.items():
        meas = cfg.get("meas", "heizung")
        bits = cfg.get("bits", {})
        try:
            c = _s7_clients.get(ip)
            if c is None or not c.get_connected():
                c = snap7.client.Client()
                c.connect(ip, 0, cfg.get("slot", 2))
                _s7_clients[ip] = c
            nbytes = max([a + 2 for a in cfg["vw"]]
                         + [int(b.split(".")[0]) + 1 for b in bits] + [2])
            raw = c.db_read(1, 0, nbytes)
            for addr, spec in cfg["vw"].items():
                if isinstance(spec, str):
                    name, field, scale = spec, "temp_c", LOGO_VW_SCALE
                else:
                    name = spec["name"]
                    field = spec.get("field", "temp_c")
                    scale = spec.get("scale", LOGO_VW_SCALE)
                v = struct.unpack_from(">h", raw, addr)[0]
                if v == 0 and field == "temp_c":   # Fuehler/AI noch nicht aktiv
                    continue
                out.setdefault(meas, {}).setdefault(name, {})[field] = \
                    round(v * scale, 1)
            for ba, name in bits.items():
                byte_i, bit_i = (int(x) for x in ba.split("."))
                on = (raw[byte_i] >> bit_i) & 1
                out.setdefault(meas, {}).setdefault(name, {})["on"] = on
        except Exception as e:
            errs.append("%s: %s" % (ip, e))
            cc = _s7_clients.pop(ip, None)
            if cc is not None:
                try:
                    cc.destroy()
                except Exception:
                    pass
    return out, errs


def _influx_query(flux):
    url = "%s/api/v2/query?org=%s" % (INFLUX_URL, urllib.parse.quote(INFLUX_ORG))
    req = urllib.request.Request(url, data=flux.encode(), method="POST")
    req.add_header("Authorization", "Token " + INFLUX_TOKEN)
    req.add_header("Content-Type", "application/vnd.flux")
    req.add_header("Accept", "application/csv")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode()


def _month_peak_bezug_kw():
    """Hoechstes 15-min-Mittel des Netzbezugs im laufenden Kalendermonat (kW)."""
    flux = ('import "date"\n'
            'from(bucket: "%s") |> range(start: date.truncate(t: now(), unit: 1mo)) '
            '|> filter(fn: (r) => r._measurement == "grid" and r._field == "bezug_w") '
            '|> aggregateWindow(every: 15m, fn: mean, createEmpty: false) '
            '|> max() |> keep(columns: ["_value"])' % INFLUX_BUCKET)
    for line in _influx_query(flux).splitlines():
        p = line.split(",")
        if len(p) >= 4 and p[0] == "" and p[1] == "_result":
            try:
                return float(p[-1]) / 1000.0
            except ValueError:
                pass
    return 0.0


_setpoint = {"kw": None, "ts": 0.0}


def lastabwurf_setpoint(cycle=0):
    """Sollwert = max(min_kw, bisherige Monats-15min-Spitze). Ratschet hoch,
    Reset automatisch am Monatsanfang (Query-Range = lfd. Kalendermonat).
    Monatsspitze alle ~5 min neu aus InfluxDB, sonst letzter Wert."""
    base = float(LOGO_LASTABWURF["min_kw"])
    if time.time() - _setpoint["ts"] > 300 or _setpoint["kw"] is None:
        try:
            _setpoint["kw"] = _month_peak_bezug_kw()
            _setpoint["ts"] = time.time()
        except Exception:
            pass
    return max(base, _setpoint["kw"] or base)


def write_lastabwurf(bezug_w, soll_kw):
    """Netzbezug (VW_IST) + Sollwert (VW_SOLL) per S7 in die Abwurf-LOGO schreiben."""
    import snap7
    cfg = LOGO_LASTABWURF
    sc = cfg["scale"]
    ist = max(-32768, min(32767, int(round(bezug_w / 1000.0 * sc))))
    soll = max(-32768, min(32767, int(round(soll_kw * sc))))
    lo = min(cfg["vw_ist"], cfg["vw_soll"])
    hi = max(cfg["vw_ist"], cfg["vw_soll"])
    buf = bytearray(hi - lo + 2)
    struct.pack_into(">h", buf, cfg["vw_ist"] - lo, ist)
    struct.pack_into(">h", buf, cfg["vw_soll"] - lo, soll)
    ip = cfg["ip"]
    c = _s7_clients.get(ip)
    if c is None or not c.get_connected():
        c = snap7.client.Client()
        c.connect(ip, 0, cfg.get("slot", 2))
        _s7_clients[ip] = c
    c.db_write(1, lo, bytes(buf))
    status = {}
    sb = cfg.get("status_bits", {})
    if sb:
        nb = max(int(k.split(".")[0]) for k in sb) + 1
        raw = c.db_read(1, 0, nb)
        for k, name in sb.items():
            bi, bit = (int(x) for x in k.split("."))
            status[name] = (raw[bi] >> bit) & 1
    return status


# ---------------------------------------------------------------- Pi + Wetter
def pi_cpu_temp():
    with open("/sys/class/thermal/thermal_zone0/temp") as f:
        return int(f.read().strip()) / 1000.0


_WEATHER_URL = ("https://api.open-meteo.com/v1/forecast?latitude=47.162"
                "&longitude=11.859&current=temperature_2m,relative_humidity_2m,"
                "cloud_cover,wind_speed_10m,surface_pressure"
                "&hourly=surface_pressure&past_days=1&forecast_days=2"
                "&timeformat=unixtime")
_weather_cache = {}
_weather_ts = 0.0


def weather():
    """Aussenwerte fuer Mayrhofen; nur alle ~10 min neu holen.
    'forecast' = [(unix_s, surface_pressure_hpa), ...] fuer die naechsten ~48 h."""
    global _weather_ts
    if time.time() - _weather_ts > 570 or not _weather_cache:
        with urllib.request.urlopen(_WEATHER_URL, timeout=8) as r:
            d = json.loads(r.read().decode())
        c = d.get("current", {})
        h = d.get("hourly", {})
        fc = [(int(t), float(p))
              for t, p in zip(h.get("time") or [], h.get("surface_pressure") or [])
              if p is not None]
        _weather_cache.clear()
        _weather_cache.update(
            temp_c=c.get("temperature_2m"),
            humidity=c.get("relative_humidity_2m"),
            cloud_cover=c.get("cloud_cover"),
            wind_ms=c.get("wind_speed_10m"),
            pressure_hpa=c.get("surface_pressure"),
            forecast=fc)
        _weather_ts = time.time()
    return dict(_weather_cache)


# ---------------------------------------------------------------- PAC2200
def pac(host):
    url = "http://%s/data.json?type=OVERVIEW" % host
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as r:
        ov = json.loads(r.read().decode())["OVERVIEW"]

    def v(k):
        x = ov.get(k)
        return x["value"] if isinstance(x, dict) else x

    p = v("P_SUM")
    if p is None:
        p = sum(v("P_L%d" % i) or 0.0 for i in (1, 2, 3))
    return {
        "p_w": p * 1000.0,
        "import_kwh": v("Import_T1"),
        "export_kwh": v("Export_T1"),
        "today_kwh": v("TODAY_T1"),
    }


# ---------------------------------------------------------------- Shelly Pro EM 50
def em_channel(ip, ch):
    """Ein Kanal eines Shelly Pro EM 50 (EM1 / EM1Data)."""
    def rpc(m):
        u = "http://%s/rpc/%s?id=%d" % (ip, m, ch)
        with urllib.request.urlopen(u, timeout=HTTP_TIMEOUT) as r:
            return json.loads(r.read().decode())

    st, dt = rpc("EM1.GetStatus"), rpc("EM1Data.GetStatus")
    return {
        "p_w": st.get("act_power", 0.0),
        "pf": st.get("pf", 0.0),
        "current_a": st.get("current", 0.0),
        "energy_kwh": dt.get("total_act_energy", 0.0) / 1000.0,
    }


# ---------------------------------------------------------------- Shelly Plug S Gen3
def plug(ip):
    u = "http://%s/rpc/Switch.GetStatus?id=0" % ip
    with urllib.request.urlopen(u, timeout=HTTP_TIMEOUT) as r:
        d = json.loads(r.read().decode())
    return {
        "p_w": d.get("apower", 0.0),
        "current_a": d.get("current", 0.0),
        "energy_kwh": d.get("aenergy", {}).get("total", 0.0) / 1000.0,
        "on": d.get("output", False),
    }


# ---------------------------------------------------------------- Shelly Pro 3EM
def shelly(ip):
    def rpc(m):
        u = "http://%s/rpc/%s?id=0" % (ip, m)
        with urllib.request.urlopen(u, timeout=HTTP_TIMEOUT) as r:
            return json.loads(r.read().decode())

    em, emd = rpc("EM.GetStatus"), rpc("EMData.GetStatus")
    return {
        "p_w": em.get("total_act_power", 0.0),
        "current_a": em.get("total_current", 0.0),
        "energy_kwh": emd.get("total_act", 0.0) / 1000.0,
    }


# ---------------------------------------------------------------- SunSpec Modbus
# SolarEdge-Modbus ist langsam und erlaubt nur eine Verbindung. Modell-Offsets
# aendern sich nie -> nach dem ersten erfolgreichen Walk cachen.
_MODEL_CACHE = {}          # (ip, unit) -> {"inv": addr, "meter": addr|None}
MB_TIMEOUT = 12.0
MB_GAP = 0.2               # Pause zwischen Requests auf derselben Verbindung


def _mb_read(sock, unit, start, count):
    if not (0 <= start <= 0xFFFF and 1 <= count <= 125):
        raise IOError("modbus arg out of range (%s/%s)" % (start, count))
    pdu = struct.pack(">BHH", 3, start & 0xFFFF, count)
    sock.sendall(struct.pack(">HHHB", 1, 0, len(pdu) + 1, unit) + pdu)
    buf = b""
    while len(buf) < 9:
        chunk = sock.recv(2048)
        if not chunk:
            raise IOError("modbus: Verbindung zu")
        buf += chunk
    if buf[7] & 0x80:
        raise IOError("modbus exc %d" % buf[8])
    if buf[7] != 3:
        raise IOError("modbus: unerwartete Antwort fc=%d" % buf[7])
    n = buf[8]
    while len(buf) < 9 + n:
        chunk = sock.recv(2048)
        if not chunk:
            raise IOError("modbus: kurze Antwort")
        buf += chunk
    time.sleep(MB_GAP)
    return buf[9:9 + n]


def _u16(b, i):
    return struct.unpack(">H", b[i * 2:i * 2 + 2])[0]


def _s16(b, i):
    x = _u16(b, i)
    return x - 0x10000 if x >= 0x8000 else x


def _acc32(b, i):
    x = struct.unpack(">I", b[i * 2:i * 2 + 4])[0]
    return None if x in (0, 0xFFFFFFFF) else x


def _sc(v, sf):
    return None if v is None else v * (10 ** sf)


def _walk_models(s, unit):
    if _mb_read(s, unit, 40000, 2)[:4] != b"SunS":
        raise IOError("no SunSpec")
    addr, inv_a, m_a = 40002, None, None
    for _ in range(20):
        mid, mlen = struct.unpack(">HH", _mb_read(s, unit, addr, 2))
        if mid in (0, 0xFFFF) or mlen > 500:
            break
        if 101 <= mid <= 113 and inv_a is None:
            inv_a = addr
        elif 201 <= mid <= 214 and m_a is None:
            m_a = addr
        addr += 2 + mlen
        if addr > 42000:            # SunSpec-Kette endet lange davor
            break
    if inv_a is None:
        raise IOError("kein Inverter-Modell")
    return {"inv": inv_a, "meter": m_a}


def _inverter_once(ip, unit, want_meter):
    key = (ip, unit)
    out = {}
    with socket.create_connection((ip, 502), timeout=MB_TIMEOUT) as s:
        s.settimeout(MB_TIMEOUT)
        m = _MODEL_CACHE.get(key) or _walk_models(s, unit)
        _MODEL_CACHE[key] = m
        b = _mb_read(s, unit, m["inv"], 2 + 52)[4:]
        out["ac_w"] = _sc(_s16(b, 12), _s16(b, 13))
        out["dc_w"] = _sc(_s16(b, 29), _s16(b, 30))
        out["wh_life"] = _sc(_acc32(b, 22), _s16(b, 24))
        out["hz"] = _sc(_u16(b, 14), _s16(b, 15))
        out["state"] = _u16(b, 36)
        tsnk = _u16(b, 32)          # Kuehlkoerper-Temp (SunSpec 103, Offset 32)
        # 0x8000 = nicht implementiert; 0x0000 = SE12.5K meldet das im Schlaf
        # (echte 0,0 C waere im Gebaeude unplausibel) -> beides als "kein Wert"
        out["temp_c"] = None if tsnk in (0x8000, 0x0000) else _sc(
            tsnk - 0x10000 if tsnk >= 0x8000 else tsnk, _s16(b, 35))
        if want_meter and m["meter"]:
            mb = _mb_read(s, unit, m["meter"], 2 + 105)[4:]
            out["m_w"] = _sc(_s16(mb, 16), _s16(mb, 20))
            out["m_wh_exp"] = _sc(_acc32(mb, 36), _s16(mb, 52))
            out["m_wh_imp"] = _sc(_acc32(mb, 44), _s16(mb, 52))
    return out


def inverter(ip, unit, want_meter):
    try:
        return _inverter_once(ip, unit, want_meter)
    except (OSError, IOError):
        _MODEL_CACHE.pop((ip, unit), None)   # evtl. war der Cache schuld
        time.sleep(1.0)
        return _inverter_once(ip, unit, want_meter)   # ein Retry


# ---------------------------------------------------------------- InfluxDB
def _lp(measurement, tags, fields, ts_ns):
    def esc(s):
        return str(s).replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")

    tagstr = "".join(",%s=%s" % (esc(k), esc(v)) for k, v in tags.items())
    fs = []
    for k, val in fields.items():
        if val is None:
            continue
        if isinstance(val, bool):
            fs.append("%s=%s" % (k, "true" if val else "false"))
        elif isinstance(val, int):
            fs.append("%s=%di" % (k, val))
        else:
            fs.append("%s=%s" % (k, float(val)))
    if not fs:
        return None
    return "%s%s %s %d" % (measurement, tagstr, ",".join(fs), ts_ns)


def write_influx(lines):
    body = "\n".join(x for x in lines if x).encode()
    if not body:
        return
    url = "%s/api/v2/write?org=%s&bucket=%s&precision=ns" % (
        INFLUX_URL, urllib.parse.quote(INFLUX_ORG), urllib.parse.quote(INFLUX_BUCKET))
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", "Token " + INFLUX_TOKEN)
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


# ---------------------------------------------------------------- Sammellauf
# SolarEdge-Modbus ist zickig, wenn 4 WR nacheinander gepollt werden. Die WR
# alle INV_EVERY Zyklen abfragen (Netz/Shelly bleiben bei jedem Zyklus).
INV_EVERY = int(os.environ.get("INV_EVERY", "2"))


_last_pv = {"w": None, "ts": 0.0}     # letzter bekannter PV-Gesamtwert (fuer Hausverbrauch)
_last_rez = {"ts": time.time()}       # letzter erfolgreicher Rezeptions-Abruf (Deep-Sleep-Sensor)


def collect(cycle=0):
    ts = time.time_ns()
    lines, dbg = [], {}

    def add(meas, tags, fields):
        lines.append(_lp(meas, tags, fields, ts))
        dbg[meas + str(tags)] = fields

    grid_w = None
    try:
        g = pac(PAC_GRID)
        grid_w = g["p_w"]
        add("grid", {}, {
            "power_w": round(g["p_w"]),
            "einspeisung_w": round(max(0.0, -g["p_w"])),
            "bezug_w": round(max(0.0, g["p_w"])),
            "import_kwh": g["import_kwh"], "export_kwh": g["export_kwh"],
            "today_import_kwh": g["today_kwh"],
        })
    except Exception as e:
        add("collector_error", {"src": "grid"}, {"up": 0})
        dbg["grid_err"] = str(e)

    if PAC_WR34:                 # nur wenn wieder aktiviert (Modbus-Reserve)
        try:
            w = pac(PAC_WR34)
            add("pv", {"src": "wr34"}, {
                "power_w": round(-w["p_w"]), "energy_kwh": w["export_kwh"]})
        except Exception as e:
            dbg["wr34_err"] = str(e)

    pv_total, pv_ok = 0.0, 0
    for inv in (INVERTERS if cycle % INV_EVERY == 0 else []):
        try:
            d = inverter(inv["ip"], inv["unit"], inv["meter"])
            add("pv", {"src": inv["name"]}, {
                "power_w": round(d["ac_w"] or 0), "dc_w": round(d["dc_w"] or 0),
                "energy_kwh": (d["wh_life"] or 0) / 1000.0,
                "hz": d["hz"], "state": int(d["state"]), "temp_c": d.get("temp_c")})
            pv_total += d["ac_w"] or 0
            pv_ok += 1
            if "m_w" in d:
                add("se_meter", {"src": inv["name"]}, {
                    "power_w": round(d["m_w"] or 0),
                    "exp_kwh": (d["m_wh_exp"] or 0) / 1000.0,
                    "imp_kwh": (d["m_wh_imp"] or 0) / 1000.0})
        except Exception as e:
            dbg["%s_err" % inv["name"]] = str(e)

    # Hausverbrauch = PV + Netz (Bezug pos. / Einspeisung neg.). PV wird nur jeden
    # 2. Zyklus gemessen -> letzten Wert weitertragen, damit die Linie nicht reisst.
    if pv_ok == len(INVERTERS):
        _last_pv["w"], _last_pv["ts"] = pv_total, time.time()

    boiler_total = 0.0
    for name, ip in BOILERS.items():
        try:
            d = shelly(ip)
            add("boiler", {"name": name}, {
                "power_w": round(d["p_w"]), "current_a": d["current_a"],
                "energy_kwh": d["energy_kwh"]})
            boiler_total += d["p_w"]
        except Exception as e:
            dbg["boiler_%s_err" % name] = str(e)

    for name, ip in CONSUMERS_3EM.items():
        try:
            d = shelly(ip)
            add("consumer", {"name": name}, {
                "power_w": round(d["p_w"]), "current_a": d["current_a"],
                "energy_kwh": d["energy_kwh"]})
        except Exception as e:
            dbg["consumer_%s_err" % name] = str(e)

    for name, ip in CONSUMERS_PLUG.items():
        try:
            d = plug(ip)
            add("consumer", {"name": name}, {
                "power_w": round(d["p_w"]), "current_a": d["current_a"],
                "energy_kwh": d["energy_kwh"], "on": d["on"]})
        except Exception as e:
            dbg["consumer_%s_err" % name] = str(e)

    for ip, chans in EM_METERS.items():
        for ch, name in chans.items():
            try:
                d = em_channel(ip, ch)
                add("consumer", {"name": name}, {
                    "power_w": round(d["p_w"]), "pf": d["pf"],
                    "current_a": d["current_a"], "energy_kwh": d["energy_kwh"]})
            except Exception as e:
                dbg["consumer_%s_err" % name] = str(e)

    summ = {"boiler_total_w": round(boiler_total)}
    if cycle % INV_EVERY == 0:
        summ["pv_modbus_w"] = round(pv_total)
    if (grid_w is not None and _last_pv["w"] is not None
            and time.time() - _last_pv["ts"] < 300):
        summ["house_w"] = round(_last_pv["w"] + grid_w)
        summ["pv_w"] = round(_last_pv["w"])
    add("summary", {}, summ)

    try:
        add("system", {"host": "solar-pi"}, {"cpu_temp_c": round(pi_cpu_temp(), 1)})
    except Exception as e:
        dbg["cpu_temp_err"] = str(e)
    try:
        w = weather()
        wf = {"temp_c": w["temp_c"], "humidity": w["humidity"],
              "cloud_cover": w["cloud_cover"], "wind_ms": w["wind_ms"]}
        if w.get("pressure_hpa") is not None:
            wf["pressure_hpa"] = w["pressure_hpa"]
        add("weather", {"ort": "mayrhofen"}, wf)
        now_s = ts // 1_000_000_000
        for t_s, p in w.get("forecast", []):
            if now_s - 30 * 3600 <= t_s <= now_s + 48 * 3600:
                lines.append(_lp("forecast", {"ort": "mayrhofen"},
                                 {"pressure_hpa": p}, t_s * 1_000_000_000))
    except Exception as e:
        dbg["weather_err"] = str(e)
    try:
        blu, blu_errs = blu_sensors()
        for name, vals in blu.items():
            add("sensor", {"name": name}, vals)
        if blu_errs:
            dbg["blu_err"] = "; ".join(blu_errs)
    except Exception as e:
        dbg["blu_err"] = str(e)
    try:
        add("sensor", {"name": "rezeption"}, shelly_ht(REZEPTION_IP))
        _last_rez["ts"] = time.time()
    except Exception as e:
        # H&T Gen3 schlaeft im Batteriebetrieb -> Timeout ist Normalfall.
        # Nur meckern, wenn seit >3 h gar kein Wert mehr kam (Sensor wirklich weg).
        gap = time.time() - _last_rez["ts"]
        if gap > 3 * 3600:
            dbg["rezeption_err"] = "%s (%.0f min kein Wert)" % (e, gap / 60)
    try:
        d = plug("192.168.40.49")          # Shelly Outdoor Plug -> Kondensator-Luefter
        add("consumer", {"name": "luefter_kondensator"}, {
            "power_w": round(d["p_w"]), "current_a": d["current_a"],
            "energy_kwh": d["energy_kwh"], "on": d["on"]})
    except Exception as e:
        dbg["luefter_kondensator_err"] = str(e)
    if LOGO_S7:
        try:
            lt, lt_errs = logo_temps()
            for meas, kessel_stelle in BRENNER_WATCH.items():
                if meas in lt:
                    kt = lt[meas].get(kessel_stelle, {}).get("temp_c")
                    on = lt[meas].get("brenner", {}).get("on")
                    if on is not None:
                        st = check_brenner_stoerung(meas, kt, bool(on))
                        lt[meas].setdefault("brenner", {})["stoerung"] = st
            for meas, stellen in lt.items():
                for name, fields in stellen.items():
                    add(meas, {"stelle": name}, fields)
            if lt_errs:
                dbg["logo_err"] = "; ".join(lt_errs)
        except ImportError:
            pass                           # python-snap7 nicht installiert -> LOGO ueberspringen
        except Exception as e:
            dbg["logo_err"] = str(e)
    if LOGO_LASTABWURF and grid_w is not None:
        try:
            bezug_w = max(0.0, grid_w)
            soll_kw = lastabwurf_setpoint(cycle)
            status = write_lastabwurf(bezug_w, soll_kw)
            f = {"ist_kw": round(bezug_w / 1000.0, 1), "soll_kw": round(soll_kw, 1)}
            f.update(status)
            add("lastabwurf", {}, f)
        except ImportError:
            pass
        except Exception as e:
            dbg["lastabwurf_err"] = str(e)
            _s7_clients.pop(LOGO_LASTABWURF["ip"], None)
    return lines, dbg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    if args.once:
        lines, dbg = collect()
        print("\n".join(x for x in lines if x))
        if dbg.get("grid_err") or any(k.endswith("_err") for k in dbg):
            print("# Fehler:", {k: v for k, v in dbg.items() if k.endswith("err")},
                  file=sys.stderr)
        return

    print("collector: Intervall %.0fs -> %s (bucket %s), WR jeden %d. Zyklus" %
          (INTERVAL, INFLUX_URL, INFLUX_BUCKET, INV_EVERY))
    cycle = 0
    while True:
        t0 = time.time()
        try:
            lines, dbg = collect(cycle)
            cycle += 1
            write_influx(lines)
            errs = {k: v for k, v in dbg.items() if k.endswith("err")}
            if errs:
                print("WARN", errs, flush=True)
        except Exception as e:
            print("collect/write failed:", e, flush=True)
        time.sleep(max(1.0, INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
