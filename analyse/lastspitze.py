#!/usr/bin/env python3
"""15-Minuten-Mittelwerte + Lastspitzen aus einem PAC2200-INST-Log rechnen.

Der Leistungspreis (Netzleistung) wird auf den hoechsten 15-min-Mittelwert des
Netzbezugs im Abrechnungsmonat berechnet (77 EUR/kW/Jahr, s. analyse/tarife.md).
Dieses Script bildet echte 15-min-Fenster (an :00/:15/:30/:45 ausgerichtet) und
zeigt, wie hoch die Spitze ist und wie viel eine Batterie kappen koennte.

    python3 lastspitze.py ~/pac2200-log/pac2200_XXXX.csv
    python3 lastspitze.py <csv> --kappung 15   # was bringt 15 kW Kappung

Erwartet Spalten: LOCAL_TIME (oder ts) und P_SUM (kW, + = Bezug, - = Einspeisung).
"""
import argparse
import csv
import datetime as dt
import sys
from collections import defaultdict

LEISTUNGSPREIS = 77.0  # EUR/kW/Jahr


def parse_ts(s):
    s = s.strip().replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def load(path):
    rows = list(csv.DictReader(open(path)))
    tkey = next((k for k in rows[0]
                 if k.lower() in ("local_time", "ts", "pac_time", "ts_local", "ts_meter")
                 or k.lower().startswith("ts")), None)
    pkey = "P_SUM" if "P_SUM" in rows[0] else next(k for k in rows[0] if "P_SUM" in k)
    out = []
    for r in rows:
        try:
            out.append((parse_ts(r[tkey]), float(r[pkey])))
        except (ValueError, KeyError, TypeError):
            pass
    return out


def quarter_means(samples):
    """Mittelwert je echtem Viertelstundenfenster."""
    buckets = defaultdict(list)
    for t, p in samples:
        q = t.replace(minute=(t.minute // 15) * 15, second=0, microsecond=0)
        buckets[q].append(p)
    return sorted((q, sum(v) / len(v), len(v)) for q, v in buckets.items())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--kappung", type=float, default=0.0, help="kW Spitzenkappung")
    args = ap.parse_args(argv)

    s = load(args.csv)
    if not s:
        sys.exit("keine Daten")
    qm = quarter_means(s)
    span_h = (s[-1][0] - s[0][0]).total_seconds() / 3600
    print("Zeitraum: %s .. %s  (%.1f h, %d Roh-Samples, %d Viertelstunden)"
          % (s[0][0], s[-1][0], span_h, len(s), len(qm)))

    bezug = [(q, m) for q, m, n in qm if m > 0]
    if not bezug:
        print("Im Zeitraum kein Netzbezug (nur Einspeisung) - keine Lastspitze.")
        return

    bezug.sort(key=lambda x: -x[1])
    peak_q, peak = bezug[0]
    print("\nHoechster 15-min-Bezug: %.1f kW  am %s" % (peak, peak_q))
    print("Top 5 Viertelstunden:")
    for q, m in bezug[:5]:
        print("   %s   %6.1f kW" % (q, m))

    # Tages-Spitzen
    daymax = {}
    for q, m in bezug:
        d = q.date()
        daymax[d] = max(daymax.get(d, 0), m)
    print("\nTages-Spitzen (15-min-Bezug):")
    for d in sorted(daymax):
        print("   %s   %6.1f kW" % (d, daymax[d]))

    if args.kappung:
        gekappt = min(args.kappung, peak)
        print("\nKappung um %.0f kW: Spitze %.1f -> %.1f kW"
              % (args.kappung, peak, peak - gekappt))
        print("Ersparnis Leistungspreis: %.0f EUR/Jahr" % (gekappt * LEISTUNGSPREIS))
        # grobe Batterie-Energie: wie lange liegt der Bezug ueber (peak - kappung)?
        over = [(q, m) for q, m in bezug if m > peak - gekappt]
        energie = sum((m - (peak - gekappt)) * 0.25 for q, m in over)
        print("dafuer noetige Batterie-Energie (nur dieser Zeitraum): ~%.0f kWh"
              % energie)

    print("\nHINWEIS: Fuer eine belastbare Aussage braucht es einen vollen Monat")
    print("15-min-Daten - am besten der EDA/Smart-Meter-Auszug vom Netzbetreiber")
    print("(TINETZ/Netz Tirol Kundenportal, Zaehler 686813).")


if __name__ == "__main__":
    main()
