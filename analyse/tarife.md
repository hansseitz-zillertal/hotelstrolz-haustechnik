# Strom-Tarife Hotel Strolz (aus Rechnungen 2026 RE/gesendet, Stand 06.09.2026)

Alle Preise **netto** (Hotel = Unternehmen, USt. durchlaufend).

## Stromkauf — Gutmann GmbH (Ökostrom & Erdgas)
Kundennr. 235931 · Anlage 5084010 · Zählpunkt AT..230131 · Zähler 686813 (Faktor 60)
Quelle: `Gutmann_235931_5084010_888904_20260531_849.pdf` (Mai 2026, 3.196 kWh)

| Position | Preis | Art |
|---|---|---|
| Energie-Arbeitspreis | **10,75 ct/kWh** | Arbeit |
| Netznutzung | 2,95 ct/kWh | Arbeit |
| Netzverlust | 0,293 ct/kWh | Arbeit |
| EAG-Förderbeitrag (Netznutzung) | 0,198 + 0,037 ct/kWh | Arbeit |
| Elektrizitätsabgabe | 0,82 ct/kWh | Arbeit |
| **Summe Arbeit (marginale kWh)** | **≈ 15,0 ct/kWh** | |
| Netzleistung (Leistungspreis) | **6,01 €/kW/Monat** | Leistung |
| EAG-Förderbeitrag (Leistung) | 0,4377 €/kW/Monat | Leistung |
| **Summe Leistung** | **≈ 6,45 €/kW/Monat ≈ 77 €/kW/Jahr** | |
| Messpreis | 5,60 €/Monat | fix |
| EAG-Pauschale | 46,11 €/Monat | fix |

Abgerechnete Spitzenleistung Mai 2026: **49,10 kWpeak** → Leistungskosten ~3.170 €/Jahr

## Einspeisung — Zählpunkt AT..419341 ("Hauptzähler", separater Einspeisezähler!)
Die PV-Einspeisung läuft NICHT über den PAC2200/Gutmann-Zähler, sondern über
diesen eigenen Zählpunkt. April 2026: **2.170,55 kWh** Gesamteinspeisung, aufgeteilt auf:

| Abnehmer | Menge (Apr 2026) | Tarif | Betrag |
|---|---|---|---|
| REG Raiffeisen EG Region Mayrhofen-Bösdornau | 586,01 kWh | **8,00 ct/kWh** | 46,88 € |
| BEG Bürgerenergiegen. Raiffeisen Tirol | 1.355,81 kWh | **7,70 ct/kWh** | 104,40 € |
| OeMAG Marktpreis Öko (Rest) | ~230 kWh | 6,77 ct/kWh (Apr); 5,72 (Mär); 8,84 (Jän) | ~15 € |
| **blended** | 2.170 kWh | **≈ 7,7 ct/kWh** | ~166 € |

OeMAG-Monatswerte (Zählpunkt 419341): Jän 0 kWh · Mär 54 kWh · Apr 2.399 kWh
(OeMAG rechnet zunächst voll ab, die EGs holen ihren Anteil per Teilnahmefaktor
nachträglich zurück — netto bleibt der blended-Wert).

## Netzbetreiber — TINETZ (Tiroler Netze GmbH, TIWAG-Gruppe)
Quelle: `Netzzugangs vertrag 250916.pdf` (Rechtsnachfolge, 16.09.2025)
- Kundennummer TINETZ: **677341**
- Verbrauchsstellennummer: **9228420** ("A) Lieferung Hotel")
- Anschlussobjekt 5199754 · Netz-Anlagennummer 1754599
- Zählpunkt: **AT005000 00000 00000000000000230131**
- Zähler 686813, Zählwerke 1.8.1 (Bezug T1) / 1.8.2 (Bezug T2), Wandler 511800-802 (Faktor 60)
- Ableseeinheit SSAM071 · Lastprofil **LPZ** · Netznutzungsebene 06 · Netzverlustebene 07
- **Netznutzungsrecht: 117,3 kW** (vertraglich) — aktuell nur ~49 kWpeak abgerechnet
  → evtl. Netznutzungsrecht reduzierbar? (eigene Kostenposition prüfen)
- Kontakt: Service Center +43 (0)50708 190, sc@tinetz.at

### 15-min-Werte (Viertelstunden-Lastgang) besorgen
- TINETZ-Kundenportal: Viertelstundenwerte müssen ggf. erst freigeschaltet werden
  ("Zustimmung zur Übermittlung von Viertelstundenwerten"). Danach als CSV export.
- ODER direkt anfragen: Mail an sc@tinetz.at mit Kundennr. 677341 + Zählpunkt,
  "Lastgang / Viertelstundenwerte der letzten 12 Monate als CSV" — muss lt. ElWOG
  kostenlos bereitgestellt werden.
- ODER über EDA: die Energiegemeinschaften bekommen bereits einen "EDA-Datenauszug"
  (via team4.energy / Enlion Innovation GmbH) — dort ggf. die 15-min-Rohdaten anfragen.

## Fürs Batterie-Rechnen
- Wert einer selbst verbrauchten statt eingespeisten kWh = **15,0 − 7,7 ≈ 7,3 ct/kWh**
  (viel weniger als die 18 ct aus der ersten Überschlagsrechnung — die EGs zahlen gut!)
- Eigener Hebel: **Leistungspreis 77 €/kW/Jahr**. Wenn eine Batterie die
  Monats-Spitzenleistung kappt, bringt jedes gekappte kW 77 €/Jahr — unabhängig
  von der Energiearbitrage. Braucht aber Ladung zur richtigen Zeit (Abend-/Winter-
  spitzen, wo keine Sonne lädt → ggf. Netzladung).
- Offen: echte Jahres-Einspeisemenge am Zählpunkt 419341 (aus allen OeMAG+EG-
  Abrechnungen zusammenrechnen) — die erste Rechnung nahm PAC2200-Export, das
  ist der falsche Zähler.
