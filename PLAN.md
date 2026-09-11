# SOLAR — Plan & Status

## Aktueller Fokus: Power-to-Heat / Ueberschuss-Erfassung
Bestehende Anlage: PAC2200 misst Netzueberschuss, mehrere LOGOs schalten
Heizstaebe in 3 Boilern, um Einspeisung in Warmwasser zu verheizen. Batterie
ist angedacht. Ziel: messen, wie viel Ueberschuss die Boiler abfangen und wie
viel noch ins Netz geht -> Grundlage fuer Batterie-Dimensionierung.
- Boiler-Verbrauch: 3x **Shelly Pro 3EM** (triphase, keine Auth), vom Mac erreichbar
  - Haupthaus  192.168.40.159   (lifetime ~24.200 kWh - groesster Verbraucher)
  - Villa      192.168.2.139     (~5.030 kWh)  <- anderes Subnetz, geht trotzdem
  - Gartenhaus 192.168.40.66     (~3.200 kWh)
- `shelly/shelly.py` - liest die 3EM (EM.GetStatus + EMData.GetStatus)
- `ueberschuss_log.py` - Kombi-Logger PAC2200 + 3 Boiler -> CSV nach ~/ptheat-log/
- Erster Testlauf 06.09.2026 15:35: 22 kW Einspeisung bei nur 12,6 kW Boilerlast
  -> viel ungenutzter Ueberschuss, Batterie/mehr Heizleistung lohnt sich.
- [x] **Zentraler Pi 5 laeuft** – `solar-pi` @ **192.168.40.45** (statisch, WLAN).
  InfluxDB 2 + Grafana + `solar-collector`-Service (alle enabled, Daten fliessen).
  - Grafana http://192.168.40.45:3000  admin / strolz-solar-2026
  - Collector pollt PAC .73 + PAC .72 + Shellys + WR1/2-Modbus alle 30 s -> bucket `solar`
  - Details + Stolpersteine + Deploy-Kommandos: `pi/README.md`
  - [x] Grafana-Dashboard "Solar / Power-to-Heat" (8 Panels: Leistung, PV je WR,
        Boiler je Standort, 15-min-Bezug mit 49,1-kW-Schwelle, Zaehlerstaende)
  - [x] **Keller-Umzug erledigt** (06.09. ~20:15): Pi am Keller-Switch, eth0 = .45
        (primär), WLAN .46 (Fallback, aktiv). Alle Quellen ausser Villa erreichbar.
        `ssh solar-pi` -> .45. Uhr synct, Dienste alle hoch.
  - **Hard-Reset:** Shelly Plug S Gen3 auf **192.168.40.230** vor dem Pi-Netzteil.
        `pi/hardreset.sh cycle` (vom Mac, kein Auth) falls SSH tot.
  - Erfasste Verbraucher (measurement `consumer`, Config in `collector.py`):
    klima_privat + klima_wr34 (Shelly Pro EM 50 .140), kuehlung (3EM .59),
    eismaschine (Plug .36), bierkuehler (Plug .121).
  - [ ] Villa-Shelly (192.168.2.139): Firewall VLAN40 -> 192.168.2.x erlauben (Antenne)
  - [ ] spaeter: Kueche + Waesche — Shellys noch nicht eingebaut; dann in
        CONSUMERS_PLUG/CONSUMERS_3EM eintragen
  - [ ] IP endgueltig: .45 (UniFi-Reservierung) oder .58 klaeren
  - [ ] Mac-Logger (`ueberschuss_log.py`, `pac2200/log.py` nohup) abschalten
- [ ] nach 1-2 Wochen Pi-Daten auswerten: Einspeise-Energie, die Boiler/Batterie abfangen koennten;
      **15-min-Bezug** ist jetzt im Dashboard (loest ggf. den TINETZ-Lastgang-Bedarf ab)
- WR3+4-Produktionsprofile in `analyse/wr34_*.json` gesichert (aus PAC .72)

### Batterie: Zeithorizont **Fruehjahr 2027** (Handwerker im Winter ausgelastet)
Bis dahin: Pi sammelt weiter -> im Fruehjahr ~6 Mon eigene 30-s-Daten + TINETZ-Jahr.

### Batterie-Analyse mit echtem TINETZ-Jahres-Lastgang (07.09.2026, `analyse/lastprofil.py`)
Datei `analyse/lp.csv` (35.040 Viertelstunden 01.09.25-31.08.26, Bezug + Einspeisung).
**Ergebnis: Batterie fuer PEAK-SHAVING lohnt sich (~11-15 J Amort.), NICHT fuer Solar-Eigenverbrauch.**
- Bezug 147.383 kWh/J · **Einspeisung 16.640 kWh/J** (echt, Zaehlpunkt 419341 = Anlage 2086588).
- **Leistungspreis real ~4.800 EUR/Jahr** (nicht die ~3.500 der Ueberschlagsrechnung).
  Monats-Spitzen: Dez 83,9 kW / Feb 82,1 / Jan 79,7 ... Mai 49,1 (= Gutmann-Rechnung, validiert).
- **Spitzen liegen 35/50 um 17:00-18:00** (Abend, Kueche+Gaeste, keine Sonne) + ein paar
  Morgenspitzen 07-08 Uhr (Fruehstueck). **Boiler helfen hier NULL** (laufen mittags).
- Peak-Shaving (aus lp.csv): 15 kW Kappung -> ~28 kWh Batterie, ~1.155 EUR/J Leistungspreis
  + ~350 EUR PV-Eigenverbrauch = ~1.500 EUR/J. 20 kW -> ~38 kWh, ~2.000 EUR/J.
- Kosten-Schaetzung turnkey netto: 30 kWh ~25-40k EUR, 50 kWh ~35-55k EUR (~700-1.000 EUR/kWh
  installiert). Minus Foerderung (~150-250 EUR/kWh) + AfA/IFB. Amort. ~11-15 J.
- [ ] 2-3 Angebote Fruehjahr 2027, jeweils mit `lp.csv` rechnen lassen; eines vom
      SolarEdge-Installateur (SE hat Gewerbe-Peak-Shaving). Notstrom-Option mitfragen.

### (aelter) Batterie-Vorabpruefung (06.09.2026, `analyse/batterie.py`)
PAC2200-Tagesprofil - durch die lastprofil.py-Analyse oben ueberholt, aber Tarif-Basis gilt.
- **Echte Tarife aus Rechnungen 2026 eingesetzt (s. `analyse/tarife.md`):**
  marginale Arbeit Bezug (Gutmann) ~15,0 ct/kWh netto; Einspeisung blended
  ~7,7 ct/kWh (REG 8,0 / BEG 7,7 / OeMAG ~6,8 - die Energiegemeinschaften
  zahlen ueberraschend gut). Spread nur **7,3 ct/kWh**.
- Damit Amortisation reine Energiearbitrage: 10 kWh ~22 J, 30 kWh ~43 J,
  50 kWh ~56 J. **Voellig unwirtschaftlich.**
- Einziger Hebel mit Substanz: **Leistungspreis 77 EUR/kW/Jahr** (Netzleistung
  6,01 + EAG 0,44 EUR/kW/Monat). Abgerechnete Spitze Mai 2026: 49,1 kWpeak.
  Batterie zur Lastspitzen-Kappung: pro gekapptem kW 77 EUR/J. 15 kW Kappung
  -> ~1.150 EUR/J. Braucht Ladung zur Abend-/Winterspitze (dann keine Sonne).
- **Metering-Falle:** PV-Einspeisung laeuft ueber EIGENEN Zaehler AT..419341
  ("Hauptzaehler"), NICHT ueber PAC2200 (AT..230131). Die batterie.py-Rechnung
  nutzt PAC2200-Export -> Groessenordnung ok (~14 MWh/J), aber fuer Genauigkeit
  echte Einspeisemenge aus OeMAG+REG+BEG-Abrechnungen summieren.
- [ ] Jahres-Einspeisemenge Zaehler 419341 aus allen 2026er OeMAG/REG/BEG-PDFs
- Leistungspreis = **hoechster 15-min-Mittelwert des Bezugs im Monat** (User bestaetigt).
  `analyse/lastspitze.py` bildet echte :00/:15/:30/:45-Fenster + Tagesspitzen +
  Kappungs-Rechnung. Braucht aber vollen Monat mit Morgen-/Abendspitzen.
  - PAC2200 hat KEIN Intervall-/Lastprofil-Endpoint (nur Tages-/Monats-kWh).
  - [ ] 15-min-Daten holen: EDA/Smart-Meter-Auszug vom Netzbetreiber
        (TINETZ/Netz Tirol Kundenportal, Zaehler 686813) ODER PAC-INST-Logger
        einen Monat 24/7 laufen lassen.
  - vorlaeufig (nur Mittag 06.09.): Spitze belanglos, Abend-/Morgenlast fehlt.

## Offen
- [x] **Cloud-API-Weg verworfen.** SolarEdge Developer Platform (developer.solaredge.com)
      ist rein OAuth2, kein API-Key-Bereich mehr. App "Strolz Solar" angelegt
      (Account info@hotelstrolz.at, Client ID/Secret in `solaredge/.env`,
      Redirect http://localhost:8765/callback). ABER: Consent-Flow braucht
      System-Owner-Rechte auf Site 2447278 — info@hotelstrolz.at ist im
      Monitoring-Portal nur Betrachter. `/v2/authorize` direkt aufrufen liefert
      "access token is missing". `auth.py`/`client.py`/`config.py` bleiben liegen,
      falls der Installateur mal Owner-Rechte gibt. Bis dahin: lokaler Modbus-Weg.
- [~] **SolarEdge lokal über SunSpec Modbus TCP** (`solaredge/modbus_local.py`).
      4 WR, ~70 kWp, keine Batterie. Mac erreicht 192.168.40.x (Modbus + PAC-HTTP).
      - wr1 192.168.40.35  unit 2  SE12.5K  + SolarEdge-Zähler (Modell 203,
        "Export+Import", TR-3Y-400V) — liefert m_w / m_wh_exp / m_wh_imp
      - wr2 192.168.40.42  unit 1  SE25K
      - [x] **wr3 .51 + wr4 .37: Modbus TCP jetzt aktiv** (07.09.), Port 502 Unit 1,
        beide **SE25K**. Alle 4 WR im Collector einzeln (`INVERTERS`), PAC .72
        nicht mehr gepollt (HTTP-Reserve, `PAC_WR34` env leer). Alte `pv src=wr34`-
        Daten aus InfluxDB geloescht. PAC-.72-Monats-/Tagesprofile bis 2024 sind
        in `analyse/wr34_*.json` archiviert.
      - `python3 solaredge/modbus_local.py --once` funktioniert für wr1+wr2 (Mac-Tool).
      - Achtung: PAC #2 (.72) Uhr laeuft auf +01:00 (keine Sommerzeit, 1 h zurueck).
      - [ ] Dauer-Logging starten (analog pac2200/log.py) + launchd
      - SolarEdge-Zähler (wr1, Modell 203) vs. PAC .73: **Momentanleistung deckt sich**
        (06.09. 18:37: SE-Zähler -32.331 W ~ PAC-Netz +32.264 W) → SE-Zähler sitzt
        praktisch am Netzanschluss wie PAC .73, nur andere Vorzeichen-Konvention.
        Die kWh-Differenz (SE 743k/38k vs PAC 427k/35k) ist wohl laengere Laufzeit /
        andere Wandler-Parametrierung, nicht anderer Messpunkt. Ueber Tage im
        Dashboard (`se_meter` vs `grid`) bestaetigen.
- [ ] **24-h-Blindleistungslog auswerten** (läuft, siehe unten). Frage: ist die
      ~14 kvar Blindleistung ein echter fester induktiver Verbraucher oder ein
      Mess-/Parametrierungsproblem der Wandler?
- [~] **Zähler-Uhr** (war ~+20 min vor). 06.09.2026 vor Ort am Gerät korrigiert →
      jetzt −27 s, stabil. Sieht manuell gestellt aus, nicht SNTP-diszipliniert.
      URSACHE der Abweichung: Router-NTP beim Netzwerk-Umbau vergessen; UCG-Fiber
      kann selbst keinen NTP-Server für Clients (nur alte USG konnte das) — bestätigt
      per Test: 192.168.10.1 / 192.168.40.1 antworten nicht auf UDP 123.
  - Zeitproblem lt. User "später lösen". SNTP im Zähler auf ACTIVE, Server = Google
    216.239.35.0 eingetragen (Trick: SNTP aus → einstellen → wieder ein). Trotzdem
    weiter −26 s stabil → SNTP diszipliniert die Uhr nicht (greift evtl. erst nach Reboot,
    oder VLAN 40 kommt nicht auf UDP 123 raus).
  - **GELÖST (Pi-Seite):** der solar-pi (192.168.40.45) synct selbst extern und ist
    jetzt NTP-Server für VLAN 40 (`allow 192.168.40.0/24`). → nur noch an beiden
    PAC2200 den SNTP-Server auf 192.168.40.45 stellen (Gerät / SENTRON powerconfig).
    Damit erledigt sich auch die PAC-.72-Uhr (+01:00).
  - [ ] in ein paar Tagen Zeitstempel nachprüfen (hält −27 s oder wandert er?).
      Fernzugriff nicht möglich: Web-UI ist read-only (pacwebui 4.0.2, kein Login/Config),
      Modbus TCP 502 verweigert Daten (Connection reset) — IP-Filter und/oder falsches
      Subnetz (Mac 192.168.10.x, Zähler 192.168.40.x). Fix am Gerät (Menü → Einstellungen →
      Datum/Uhrzeit + SNTP=ACTIVE + NTP-Server-IP) oder mit SENTRON powerconfig aus dem
      192.168.40.x-Netz. TZ/DST sind ok (Zähler meldet korrekt +02:00).
      Optional: Mac-IP in Modbus-IP-Filter freischalten → dann kann Claude Reg. 799
      (Date/time UTC) + 62993/62995 (SNTP) setzen und die Uhr überwachen.
- [ ] Entscheiden: dauerhaftes Logging (launchd/cron) + Dashboard?

## Laufend (Mac – kann jetzt weg, der Pi hat übernommen)
- `pac2200/log.py` nohup seit 06.09. ~11:18 (`~/pac2200-log/pac2200_20260906_111830.csv`) –
  Blindleistungs-24h-Log, danach beenden.
- `ueberschuss_log.py` NICHT als Dauerlauf gestartet.

## Erledigt
- **Zentraler solar-pi (Pi 5) + InfluxDB + Grafana + Collector** – erfasst PAC .73,
  PAC .72, 3 Shellys, WR1/2-Modbus alle 30 s. Dashboard fertig. Pi ist auch
  NTP-Server für VLAN 40. Details: `pi/README.md`.
- PAC2200 JSON-API erkundet, `pac2200/log.py` geschrieben und getestet.
- SolarEdge: Cloud-API-Weg (OAuth) verworfen, lokal über Modbus + 2. PAC gelöst.
- Strom-Tarife aus Rechnungen extrahiert (`analyse/tarife.md`), Batterie-Vorabrechnung
  (`analyse/batterie.py`): reine Energiespeicherung unwirtschaftlich, nur Leistungspreis-
  Kappung hätte Substanz.
- Langfrist-Leistungsfaktor aus COUNTER berechnet: tan φ ≈ 0,41 → cos φ ≈ 0,92
  induktiv (unkritisch). Momentan schlechter PF erklärt sich durch kleine
  Wirkleistung, wenn PV den Verbrauch deckt.

## Referenzdaten (Stand 06.09.2026)
- Zählerstand Netzbezug T1: 427.269 kWh · Einspeisung T1: 34.620 kWh
- Jahr 2026 bisher: Bezug 109.387 kWh · Einspeisung 13.220 kWh
- Jahr 2025 gesamt: Bezug 142.424 kWh · Einspeisung 14.306 kWh
