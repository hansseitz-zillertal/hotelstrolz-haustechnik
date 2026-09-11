#!/usr/bin/env python3
"""Auswertung des TINETZ-Jahres-Lastgangs (15-min, 01.09.2025-31.08.2026).

Quelle: LP_KWH_MAYRHOFEN_DURST_279_01092025-31082026.xlsx -> lp.csv
  Spalte bezug_kwh_qh  = Netzbezug je Viertelstunde (Anlage 1754599, Zählpunkt ..230131)
  Spalte einsp_kwh_qh  = Einspeisung je Viertelstunde (Anlage 2086588, Zählpunkt ..419341)

Rechnet:
  - Monats-Spitzenleistung (hoechster 15-min-Mittelwert Bezug) -> Leistungspreis
  - Wann liegen die Spitzen (Tageszeit / Wochentag)
  - Peak-Shaving mit Batterie: was bringt Kappung, wieviel Energie noetig
  - Einspeise-Statistik (echte Zahlen jetzt) fuer die Speicher-Frage

Preise aus analyse/tarife.md (netto).
"""
import csv
import datetime as dt
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "lp.csv")

LEISTUNGSPREIS = 77.0      # EUR/kW/Jahr (Netzleistung 6,01 + EAG 0,44 EUR/kW/Monat)
ARBEIT_BEZUG = 0.150       # EUR/kWh marginale Arbeit
VERGUETUNG = 0.077         # EUR/kWh blended Einspeisung
ETA = 0.90


def load():
    out = []
    with open(CSV) as f:
        for row in csv.DictReader(f):
            out.append((dt.datetime.fromisoformat(row["ts"]),
                        float(row["bezug_kwh_qh"]), float(row["einsp_kwh_qh"])))
    return out


def main():
    d = load()
    n = len(d)
    span_days = (d[-1][0] - d[0][0]).days + 1
    tot_bezug = sum(x[1] for x in d)
    tot_einsp = sum(x[2] for x in d)

    print("=" * 70)
    print("LASTGANG  %s .. %s   (%d Tage, %d Viertelstunden)"
          % (d[0][0].date(), d[-1][0].date(), span_days, n))
    print("  Netzbezug gesamt:    %9.0f kWh" % tot_bezug)
    print("  Einspeisung gesamt:  %9.0f kWh" % tot_einsp)
    print("  -> Einspeisung ist %.1f %% vom Bezug" % (100 * tot_einsp / tot_bezug))

    # ---- Monats-Spitzenleistung (Leistungspreis) --------------------------
    # 15-min-Mittelleistung [kW] = kWh je Viertelstunde * 4
    mon_peak = {}          # (yyyy,mm) -> (kW, timestamp)
    for t, b, e in d:
        kw = b * 4.0
        key = (t.year, t.month)
        if key not in mon_peak or kw > mon_peak[key][0]:
            mon_peak[key] = (kw, t)
    print("\n" + "=" * 70)
    print("MONATS-SPITZENLEISTUNG (Basis Leistungspreis, %.0f EUR/kW/Jahr)" % LEISTUNGSPREIS)
    print("  %-9s %10s   %-16s   %10s" % ("Monat", "Spitze kW", "wann", "Kosten/Monat"))
    sum_year = 0.0
    for key in sorted(mon_peak):
        kw, ts = mon_peak[key]
        cost = kw * LEISTUNGSPREIS / 12.0
        sum_year += cost
        print("  %04d-%02d   %10.1f   %-16s   %9.0f EUR"
              % (key[0], key[1], kw, ts.strftime("%a %d.%m %H:%M"), cost))
    print("  " + "-" * 55)
    print("  Leistungspreis gesamt / Jahr: %.0f EUR" % sum_year)
    print("  (Jahres-Maximum: %.1f kW)" % max(v[0] for v in mon_peak.values()))

    # ---- Wann liegen die Spitzen ---------------------------------------
    # Top-50 Viertelstunden nach Bezug: Verteilung ueber Tageszeit / Wochentag
    top = sorted(d, key=lambda x: -x[1])[:50]
    hod = defaultdict(int)
    dow = defaultdict(int)
    for t, b, e in top:
        hod[t.hour] += 1
        dow[t.weekday()] += 1
    print("\n" + "=" * 70)
    print("WANN sind die 50 hoechsten Viertelstunden?")
    wd = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    print("  Tageszeit:", ", ".join("%02d:00=%d" % (h, hod[h]) for h in sorted(hod)))
    print("  Wochentag:", ", ".join("%s=%d" % (wd[k], dow[k]) for k in sorted(dow)))

    # ---- Peak-Shaving mit Batterie ------------------------------------
    print("\n" + "=" * 70)
    print("PEAK-SHAVING  (Batterie kappt die Monats-Spitze)")
    print("  Modell: Batterie deckt Bezug ueber Ziel-kW, solange Energie reicht.")
    print("  Pro Monat einzeln, dann aufsummiert.\n")
    print("  %-8s %14s %14s %12s" % ("Kappung", "Ersparnis/Jahr", "max Batt-kWh", "noetig fuer"))
    # gruppiere Viertelstunden je Monat
    by_month = defaultdict(list)
    for t, b, e in d:
        by_month[(t.year, t.month)].append(b * 4.0)  # kW
    for cap_kw in (5, 10, 15, 20, 30, 40):
        year_saving = 0.0
        max_batt = 0.0
        for key, kws in by_month.items():
            peak = max(kws)
            target = peak - cap_kw
            if target <= 0:
                continue
            # Energie ueber target in diesem Monat, laengste zusammenhaengende Spitze
            over = [(kw - target) * 0.25 for kw in kws if kw > target]  # kWh je qh
            # konservativ: die Batterie muss die groesste Tagesspitze schaffen ->
            # naeherung: summe der 8 groessten qh-Ueberschreitungen (=2h am Stueck)
            over.sort(reverse=True)
            batt_needed = sum(over[:8])
            max_batt = max(max_batt, batt_needed)
            year_saving += cap_kw * LEISTUNGSPREIS / 12.0
        print("  %2d kW   %13.0f EUR %13.1f kWh   (~2h Spitze abdecken)"
              % (cap_kw, year_saving, max_batt))

    # ---- Einspeisung: echte Zahlen fuer die Speicher-Frage ------------
    print("\n" + "=" * 70)
    print("EINSPEISUNG (echt, Zaehlpunkt 419341)")
    einsp_qh = sorted(x[2] for x in d)
    days_einsp = defaultdict(float)
    for t, b, e in d:
        days_einsp[t.date()] += e
    dvals = sorted(days_einsp.values())
    nd = len(dvals)
    print("  gesamt %.0f kWh/Jahr = im Schnitt %.1f kWh/Tag" % (tot_einsp, tot_einsp / nd))
    print("  Median %.1f  p90 %.1f  max %.1f kWh/Tag"
          % (dvals[nd // 2], dvals[int(nd * 0.9)], dvals[-1]))
    for thr in (10, 30, 60, 100):
        k = sum(1 for v in dvals if v > thr)
        print("  Tage mit Einspeisung > %3d kWh: %3d (%.0f %%)" % (thr, k, 100 * k / nd))
    # Batterie fuer Eigenverbrauch: min(Tages-Einspeisung, C) * eta * spread
    spread = ARBEIT_BEZUG - VERGUETUNG
    print("\n  Batterie fuer PV-Eigenverbrauch (Spread %.3f EUR/kWh):" % spread)
    print("  %-8s %14s %14s %8s" % ("nutzbar", "aufgef./Jahr", "Ersparnis/J", "Amort.*"))
    for C in (10, 20, 30, 50):
        cap = sum(min(v, C) for v in dvals) * ETA
        saving = cap * spread
        kosten = C * 600
        print("  %2d kWh  %13.0f kWh %11.0f EUR   %5.1f J"
              % (C, cap, saving, kosten / saving if saving else 0))
    print("  *nur Energie-Arbitrage, ohne Leistungspreis-Effekt, 600 EUR/kWh")


if __name__ == "__main__":
    main()
