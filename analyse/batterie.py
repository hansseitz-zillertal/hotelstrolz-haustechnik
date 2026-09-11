#!/usr/bin/env python3
"""Batterie-Sinnhaftigkeit aus den PAC2200-Lastprofilen abschaetzen.

Grundgedanke: die Boiler (Power-to-Heat) fressen den Grossteil des PV-Ueber-
schusses schon weg. Was am Netzzaehler noch als *Einspeisung* uebrig bleibt,
ist die einzige Energie, die eine Batterie zusaetzlich noch verschieben koennte.

Modell (bewusst einfach):
  - pro Tag kann die Batterie hoechstens ihre nutzbare Kapazitaet C aufnehmen
    und wird ueber Nacht sicher wieder leer (Grundlast >> C, s. Ausgabe).
  - jaehrlich aufgefangen ~ Summe ueber alle Tage von min(Einspeisung_Tag, C) * eta
  - Ersparnis = aufgefangen * (Bezugspreis - Einspeisurverguetung)

Preise unten anpassen.
"""
import json
import os
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- Annahmen (aus analyse/tarife.md, Rechnungen 2026) ---------------------
PREIS_BEZUG = 0.150    # EUR/kWh, marginale Arbeit Gutmann (Energie+Netz+Abgaben, netto)
VERGUETUNG = 0.077     # EUR/kWh, blended Einspeisung (REG 8,0 / BEG 7,7 / OeMAG ~6,8)
ETA = 0.90             # Round-trip-Wirkungsgrad der Batterie
BATT_KOSTEN = 600.0    # EUR pro kWh nutzbar, installiert (grobe Hausnummer)
KAPAZITAETEN = [10, 20, 30, 50, 75, 100]   # kWh nutzbar
LEISTUNGSPREIS = 77.0  # EUR/kW/Jahr (Netzleistung + EAG), separater Hebel


def load(name):
    return json.load(open(os.path.join(HERE, name)))


def daily():
    p = load("dailyprofile.json")
    out = []
    for r in p["data"]:
        d = dt.date.fromisoformat(r["TS"][:10])
        out.append((d, r["import"], abs(r["export"])))
    out.sort()
    return out


def monthly():
    p = load("monthlyprofile.json")
    # Entry-TS ist der Snapshot am Periodenende -> "import" gehoert zum Vormonat.
    out = []
    for r in p["data"]:
        end = dt.date.fromisoformat(r["TS"][:10])
        month = (end.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
        out.append((month, r["import"], abs(r["export"])))
    out.sort()
    return out


def main():
    dd = daily()
    mm = monthly()

    print("=" * 64)
    print("DATENBASIS")
    print("  Tagesprofil: %d Tage  %s .. %s" % (len(dd), dd[0][0], dd[-1][0]))
    print("  Monatsprofil: %s .. %s" % (mm[0][0], mm[-1][0]))

    # Grundlast-Check: kleinster Tagesbezug -> Nacht-Entladung gesichert?
    min_day_imp = min(x[1] for x in dd)
    print("\nGRUNDLAST")
    print("  kleinster Tagesbezug im Zeitraum: %.0f kWh  (~%.1f kW im Schnitt)"
          % (min_day_imp, min_day_imp / 24))
    print("  -> jede realistische Batterie wird nachts sicher wieder leer.")

    # Jahres-Uebersicht aus Monatsprofil (volle Kalendermonate)
    print("\nJAHRES-BILANZ (aus Monatsprofil, kWh)")
    years = {}
    for m, imp, exp in mm:
        y = years.setdefault(m.year, [0.0, 0.0, 0])
        y[0] += imp
        y[1] += exp
        y[2] += 1
    for y in sorted(years):
        imp, exp, n = years[y]
        tag = "" if n == 12 else "  (%d Monate)" % n
        print("  %d:  Bezug %8.0f   Einspeisung %7.0f%s" % (y, imp, exp, tag))

    # Einspeise-Statistik pro Tag
    exps = sorted(x[2] for x in dd)
    n = len(exps)
    total_exp = sum(exps)
    print("\nEINSPEISUNG PRO TAG (im Tagesprofil-Zeitraum)")
    print("  Summe %.0f kWh in %d Tagen  ->  %.1f kWh/Tag im Mittel"
          % (total_exp, n, total_exp / n))
    print("  Median %.1f   p90 %.1f   Maximum %.1f kWh"
          % (exps[n // 2], exps[int(n * 0.9)], exps[-1]))
    for thr in (5, 20, 50, 100, 150):
        k = sum(1 for e in exps if e > thr)
        print("  Tage mit Einspeisung > %3d kWh: %3d  (%.0f%%)"
              % (thr, k, 100 * k / n))

    # Hochrechnung aufs Jahr: Tagesprofil deckt 2026-01-29 .. 2026-09-06, also
    # die komplette einspeisestarke Zeit (Mai-Aug). Fehlt: die schwachen Monate
    # Sep-Rest bis Jan. Deren Einspeisung ist klein und pro Tag << Batterie ->
    # eine Batterie faengt davon ~75 % ab, unabhaengig von der Groesse.
    ref = {m.month: exp for m, imp, exp in mm if m.year == 2025}  # 2025 als Muster
    missing = 0.5 * ref.get(9, 900) + ref.get(10, 650) + ref.get(11, 2000) + \
        ref.get(12, 850) + 0.0  # Jan ~0
    missing_captured = 0.75 * missing
    print("\n  einspeise-schwache Restmonate (Sep-Rest..Jan, Muster 2025):"
          " ~%.0f kWh Einspeisung -> Batterie faengt davon ~%.0f kWh ab"
          % (missing, missing_captured))

    # Batterie-Szenarien
    print("\n" + "=" * 64)
    print("BATTERIE-SZENARIEN  (Jahreswert)")
    print("  Preise: Bezug %.2f  Einspeisung %.2f  Spread %.2f EUR/kWh"
          % (PREIS_BEZUG, VERGUETUNG, PREIS_BEZUG - VERGUETUNG))
    print("  eta %.0f%%   Kosten %.0f EUR/kWh nutzbar" % (ETA * 100, BATT_KOSTEN))
    spread = PREIS_BEZUG - VERGUETUNG
    max_capturable = total_exp * (365.0 / n) * 0.0 + (total_exp + missing)
    print("  theoretisches Maximum (unendlich grosse Batterie): ~%.0f kWh/Jahr\n"
          % (max_capturable * ETA))
    print("  %-8s %13s %13s %10s %9s" %
          ("kWh nutz", "aufgef./Jahr", "Ersparnis/Jahr", "Kosten", "Amort."))
    for C in KAPAZITAETEN:
        captured = (sum(min(e, C) for e in exps) + missing_captured) * ETA
        ersparnis = captured * spread
        kosten = C * BATT_KOSTEN
        amort = kosten / ersparnis if ersparnis > 0 else float("inf")
        print("  %-8d %13.0f %13.0f %10.0f %8.1f J"
              % (C, captured, ersparnis, kosten, amort))

    print("\nLESART")
    print("  'aufgefangen/Jahr' = PV-Strom, der heute eingespeist wird und mit")
    print("  Batterie stattdessen selbst verbraucht wuerde. Mehr geht nicht -")
    print("  die Boiler haben den Rest vorher schon geholt.")


if __name__ == "__main__":
    main()
