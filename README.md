# SOLAR

Auslesen und Auswerten der PV-Anlage (SolarEdge) und des Hauptzählers
(Siemens SENTRON PAC2200) am Standort.

## Komponenten

### `pac2200/` — Siemens SENTRON PAC2200 Hauptzähler
- Web-UI: <http://192.168.40.73> (im LAN, **keine Authentifizierung**)
- JSON-API: `GET http://192.168.40.73/data.json?type=<TYPE>` (nur GET)
- Firmware PAC2200 V3.2.2, Bestell-Nr. 7KM2200-2EA30-1EA1, Serie LQN/230314640090
- Stromwandler-Verhältnis ≈ 60:1 (primary/secondary aus COUNTER)
- **Achtung:** Zähler-Uhr läuft ~20 min vor der echten Zeit (Stand 06.09.2026)

Verfügbare `type`-Werte:
| Typ | Inhalt |
|-----|--------|
| `OVERVIEW` | Live-Übersicht: Zählerstände, heute/Monat, Leistung je Phase |
| `INST_VALUES` | Live-Momentanwerte: U, I, P, Q, S, PF, f je Phase |
| `COUNTER` | Energiezähler je Phase/Tarif — Wirk-, Blind-, Scheinenergie |
| `DAILYPROFILE` / `MONTHLYPROFILE` / `YEARLYPROFILE` | Historie (kWh je Periode), `&count=<n>` |
| `PRODUCT_INFO` / `DEVICE_INFO` / `LOGBOOK` | Geräte- und Ereignisdaten |
| `HARMONICS` / `WAVEFORM` / `EXTREME_VALUES` | Oberschwingungen, Kurvenform, Extremwerte |

`import` = Netzbezug (kWh), `export` = Einspeisung (kWh, negativ in Profilen).

#### `pac2200/log.py`
Pollt den Zähler und schreibt eine CSV-Zeile je Messung.
```
python3 log.py                 # dauerhaft, alle 120 s
python3 log.py --interval 60   # anderes Intervall
python3 log.py --hours 24      # nach N Stunden stoppen
python3 log.py --once          # eine Messung nach stdout
```
Logs landen unter `~/pac2200-log/` (**lokale Platte, nicht iCloud** — vermeidet
Sync-Last bei häufigem Anhängen).

### `solaredge/` — SolarEdge PV-Anlage
- Site ID **2447278**, 4 Wechselrichter, ~70 kWp, keine Batterie.

**Aktiver Weg: lokal über SunSpec Modbus TCP** (keine Cloud, keine Rechte nötig).
- `modbus_local.py` — pollt die WR direkt im LAN und loggt CSV nach
  `~/solaredge-log/`. CLI:
  `python3 modbus_local.py --once | --scan | [--interval N] [--hours H]`
- WR-Liste + Modbus-Unit-IDs stehen in `INVERTERS` oben in der Datei.
- Modbus TCP muss je WR aktiv sein (SetApp → Site Communication → Modbus TCP,
  Port 502). Stand: wr1 (.35) + wr2 (.42) ok; wr3 (.51) + wr4 (.37) noch offen.
- wr1 hat zusätzlich einen SolarEdge-Zähler (SunSpec-Modell 203) am Bus.

**Cloud-Weg (liegt brach):** `config.py` / `auth.py` / `client.py` — OAuth2 gegen
die neue Developer Platform. Blockiert, weil info@hotelstrolz.at im Monitoring-
Portal nur Betrachter ist und der Consent-Flow System-Owner-Rechte braucht.

### `shelly/` — Boiler-Verbrauch (Power-to-Heat)
- 3x Shelly Pro 3EM an den Boilern Haupthaus / Villa / Gartenhaus (IPs in
  `shelly/shelly.py`, keine Auth, lokale HTTP-RPC-API).
- `python3 shelly/shelly.py` — Momentanleistung + kWh je Boiler.

### `ueberschuss_log.py` — Kombi-Logger
- PAC2200 (Netz, .73) + 2. PAC2200 (Produktion WR3+4, .72) + alle 3 Boiler-
  Shellys in einem Takt → CSV nach `~/ptheat-log/`. Spalten u.a. `grid_w`
  (negativ = Einspeisung), `einspeisung_w`, `bezug_w`, `pv_wr34_w`,
  `pv_wr34_kwh`, `b_<boiler>_w`, `b_<boiler>_kwh`, `boiler_total_w`.
- `python3 ueberschuss_log.py --once | [--interval N] [--hours H]`

### Zwei PAC2200
- **.73** "Hauptzähler" — Netzbezug/-einspeisung des Hotels (= der Gutmann-/
  TINETZ-Abrechnungszähler, Zählpunkt AT..230131).
- **.72** — misst nur die AC-Produktion von WR3 + WR4 (Serie 2024). Ersetzt
  vorerst den Modbus-Zugriff auf diese beiden WR. Uhr steht auf +01:00.

## Status
Siehe `PLAN.md`.
