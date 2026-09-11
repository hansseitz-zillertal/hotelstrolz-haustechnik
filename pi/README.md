# Solar-Pi (Raspberry Pi 5)

Zentrale Erfassung der PV-/Power-to-Heat-Anlage: InfluxDB 2 + Grafana + ein
Python-Collector, der alle 30 s alle Quellen abfragt.

## Zugang (Stand 06.09.2026 – im Keller, LAN)
- Hostname `solar-pi`. PW `2Hundebellen5`, Mac-Key hinterlegt (`ssh solar-pi` → .45).
- **LAN (eth0):** feste IP **192.168.40.45**, Metrik 100 – primär (Keller-Switch, VLAN 40). ✓
- **WLAN (wlan0, "Stroxx"):** **192.168.40.46**, Metrik 600 – Fallback, aktiv.
- **Hard-Reset:** der Pi hängt an einem **Shelly Plug S Gen3 (192.168.40.230)**.
  `pi/hardreset.sh cycle` schaltet ihn per RPC aus/ein (wenn SSH tot ist).
- **Grafana:** <http://192.168.40.45:3000> (LAN) bzw. `:46` (WLAN) – admin / `strolz-solar-2026`
  · Küchen-Anzeige: User `kueche` / `kuehlraum-2026` (nur Viewer)
- **InfluxDB:** Port 8086, gleiche Zugangsdaten
- Keller-Umzug: Pi ans Kabel (VLAN 40!), kommt bei .45 hoch. WLAN bleibt als .46 aktiv;
  bei Bedarf abschalten: `sudo nmcli con mod Stroxx connection.autoconnect no && sudo nmcli con down Stroxx`.
  ssh-config auf dem Mac dann wieder auf .45 stellen.
  (org `strolz`, bucket `solar`, Retention unbegrenzt)
- InfluxDB-Token: in `/etc/solar-collector.env`
- Dashboard: „Solar / Power-to-Heat" (Ordner Solar), uid `solar-main`

## Quellen -> InfluxDB
| Measurement | Tag | Quelle |
|---|---|---|
| `grid` | – | PAC2200 .73 (Hotel-Netzzähler): `power_w` (- = Einspeisung), `einspeisung_w`, `bezug_w`, `import_kwh`, `export_kwh` |
| `pv` | `src=wr1..wr4` | SolarEdge SunSpec Modbus, alle 4 WR: wr1 .35 u2 (SE12.5K + Zähler), wr2 .42 u1, wr3 .51 u1, wr4 .37 u1 (je SE25K). PAC .72 (wr3+4 kombiniert) nicht mehr gepollt – HTTP-Reserve, `PAC_WR34` in `/etc/solar-collector.env` setzen zum Reaktivieren |
| `se_meter` | `src=wr1` | SolarEdge-Zähler am WR1-Modbus |
| `boiler` | `name=haupthaus/villa/gartenhaus` | Shelly Pro 3EM |
| `consumer` | `name=…` | weitere gemessene Verbraucher (Config in `collector.py`): **klima_privat** (Klima Privatwohnung) + **klima_wr34** (Klima WR3+4-Raum) = Shelly Pro EM 50 `192.168.40.140` Kanal 0/1 (verifiziert 06.09.) · **kuehlung** = Shelly 3EM `192.168.40.59` (Kühlanlage gesamt) · **eismaschine** = Plug S `192.168.40.36` · **bierkuehler** = Plug S `192.168.40.121` · **kuehlung_begleit** `192.168.40.192` + **kuehlung_luefter** `192.168.40.133` = Unterzähler HINTER dem kuehlung-3EM (schon in dessen Summe → nie zusätzlich aufsummieren, nur Aufschlüsselung) |
| `summary` | – | `boiler_total_w`, `pv_modbus_w` (nur jeden 2. Zyklus / 60 s), **`house_w` = Hausverbrauch = PV + Netz** und `pv_w` (jeden Zyklus / 30 s – PV-Wert wird zwischen den Modbus-Abfragen weitergetragen, max 300 s alt, sonst kein Schreiben). Ersetzt die alte Grafana-`union/pivot`-Rechnung, die riss, weil PV (60 s) und Netz (30 s) beim `pivot` selten auf denselben Zeitstempel fielen. History per Flux-`to()` nachgefüllt (1-min). |
| `pv` (Feld `temp_c`) | `src=wrN` | Wechselrichter-Kühlkörper-Temp (SunSpec 103 Offset 32) |
| `heizung` | `stelle=…` | Temperaturen aus den **Siemens LOGO!8** über **S7** (`logo_temps()`, `python-snap7`, LOGO-VM = DB1, `VWn` = `DB1.DBWn`). Config `LOGO_S7` in `collector.py`: `{ip: {slot, vw:{byteadr: name}}}`, `rack=0 slot=2`. Rohwert × `LOGO_VW_SCALE` (0,1 → °C, LOGO-Programm legt Int ×10 °C ab). Haupt-LOGO `192.168.40.153`, `VW0` = Außentemperatur. Braucht in der LOGO eine **S7-Server-Verbindung** (passiv, „nur dieses Gerät" **aus**). snap7 fehlt → `logo_temps()` fängt `ImportError` ab, Rest läuft weiter. |
| `lastabwurf` | – | `ist_kw` = Netzbezug live, `soll_kw` = dyn. Abwurf-Sollwert. Der Collector **schreibt** per S7 (`write_lastabwurf`, snap7 `db_write`) in die Abwurf-LOGO `LOGO_LASTABWURF["ip"]` (= **`192.168.40.71`**): `VW10` = Netzbezug, `VW12` = Sollwert, beide **kW × `scale` (=10)**. **Sollwert = `max(min_kw=40, höchstes 15-min-Mittel Netzbezug im lfd. Monat)`** (`lastabwurf_setpoint()` → `_month_peak_bezug_kw()` Flux-Query, alle 5 min; Reset am Monats­anfang automatisch). LOGO vergleicht selbst **PAC-Netzbezug (Modbus, schnell)** > `VW12` → Abwurf, Hysterese 10 kW im LOGO-Programm. |
| `system` | `host=solar-pi` | `cpu_temp_c` – Pi-CPU-Temperatur |
| `weather` | `ort=mayrhofen` | `cloud_cover` / `pressure_hpa` (+temp/humidity/wind) – Open-Meteo `current`, alle ~10 min, als Prognose-Kontext |
| `forecast` | `ort=mayrhofen` | `pressure_hpa` – Open-Meteo stündliche Luftdruck-Kurve (`past_days=1&forecast_days=2`): letzte ~30 h **+** 48 h voraus, jeder Zyklus neu geschrieben → self-correcting. Dashboard „Temperaturen": gestrichelte Linie im Luftdruck-Panel; Default-Zeitfenster `now-24h … now+9h`. NB: Station liegt ~5–6 hPa über der Open-Meteo-Kurve (Kalibrierung/Höhenannahme) – nur die **Steigung** vergleichen |
| `sensor` | `name=aussen / wr_raum / rezeption / vorkuehlraum / milchkuehlraum / fleischkuehlraum / kuehltechnik` | **BLU-Wettersensoren** über den BLE-Cloud-Relay des Shelly `.140` (`/rpc/BLE.CloudRelay.ListInfos`, BTHome v2, `_BLU_STATE` sammelt je Messwert – Außenstation rotiert!). `aussen`: temp_c/humidity/pressure_hpa/illuminance_lux/dewpoint_c/precip_mm/battery. **`precip_mm` = roher Kippwaagen-Zähler** (monoton steigend, ~105/Nacht); Dashboard „Außen jetzt" zeigt `Regen 24 h` = `difference(nonNegative) |> sum() * 0.2` mm (0,2 mm/Kippung – deckt sich mit Open-Meteo ~21 vs 17 mm; Faktor ggf. anpassen). `innen`: temp_c/humidity. **`rezeption` = Shelly H&T Gen3 `192.168.40.145`** (`shelly_ht()`, ein `Shelly.GetStatus`: temp_c/humidity/battery). Batteriebetrieb → Deep-Sleep, meldet nur ~alle 2 h bzw. bei Tastendruck; **für Live-Anzeige per USB-C dauerhaft versorgen** (dann alle 30 s). Timeout ist Normalfall → `rezeption_err` erst nach >3 h Stille. (vorher Shelly Wall Display `.90`, jetzt ungenutzt.) Alle Werte als float geschrieben (sonst InfluxDB-Typkonflikt). BLU-Gateways in `BLU_GATEWAYS` (.140 = Wetter/wr_raum; **.49 Outdoor Plug = die 3 Kühlräume, schwaches WLAN → Lücken**; **.133 Plug S G3 = `kuehltechnik`**, BLU H&T `fc:4d:6a:39:69:e8` im Kälteanlagen-Technikraum – Plug S G3 kann keinen Kabelfühler, nur BLE-Relay; **.90 Wall Display (Rezeption) = `aussen_nord`**, BLU H&T `7c:c6:b6:65:1f:fd` Außentemperatur Nordseite/Schatten; **.34 Shelly Plus 1PM (Pavillon) = `pavillon`**, BLU H&T `f8:44:77:2b:2c:7e` Sonnenterrasse unter Dach – hat KEINEN eigenen Fühler, `switch:0.temperature` wäre nur Elektronik-Eigenwärme). .49 schaltet auch den Kondensator-Lüfter → `consumer name=luefter_kondensator` |

## Betrieb
- `journalctl -u solar-collector -f` – Collector-Log (loggt nur WARN bei Teilausfall)
- `systemctl status influxdb grafana-server solar-collector` – alle 3 sind `enabled`
- Nach Änderung an `collector.py`:
  `scp pi/collector.py solar-pi:~ && ssh solar-pi 'sudo install -m755 ~/collector.py /opt/solar-collector/ && sudo systemctl restart solar-collector'`
- Konfig: `/etc/solar-collector.env` (Intervall, Token). Läuft als User `solar`.
- Neuaufsetzen: `scp -r pi solar-pi:~/solar-pi && ssh solar-pi 'cd solar-pi && sudo bash setup.sh'`

## Bekannte Baustellen
- **Boiler Villa (192.168.2.139) vom Pi NICHT erreichbar** – VLAN 40 → 192.168.2.x
  ist per Firewall/Routing gesperrt (vom Mac aus ging es). → UniFi-Regel:
  VLAN 40 → 192.168.2.139 (oder .2.0/24) TCP 80 erlauben. Solange das fehlt,
  loggt der Collector nur Haupthaus + Gartenhaus (Villa: `no route to host`,
  wird sauber uebersprungen). Nach dem Keller-Umzug (eth0) evtl. neu pruefen.
- ~2 % der wr1-Modbus-Reads laufen in Timeout (wr1 = Leader + Zaehler, am meisten
  Last). Egal – Grafana interpoliert, kWh-Zaehler sind exakt.

## Reboot-fest (getestet 06.09.)
2× durchgestartet: alle Dienste kommen automatisch hoch, InfluxDB-Daten + Token
bleiben. `cmdline.txt` ist sauber (kein `systemd.run`/`systemd.unit`-Rest).

## Setup-Historie / Stolpersteine (falls nochmal)
- Image: RPi OS **Trixie** (Debian 13), Desktop-Variante. Provisionierung lief über
  ein selbst geschriebenes `firstrun.sh` + `systemd.run`-Hook in `cmdline.txt`
  (Imager-Einstellungen wurden 2x nicht übernommen). WICHTIG: die firstrun-Aufräumzeile
  muss `sed -i 's| systemd.run.*||g'` sein (mit `.*`), sonst bleibt
  `systemd.unit=kernel-command-line.target` stehen → Rescue-Mode-Loop.
- Harte Ausschalter beim Debuggen → dpkg-Dateilisten korrupt (libpython!, libqt6widgets6,
  gvfs*) → Python-SIGILL. Fix: `apt install --reinstall python3.13-minimal
  libpython3.13-* python3-minimal` + betroffene Pakete. `dmesg` zeigte KEINE
  echten SD-/FS-Fehler, PSU ok (`vcgencmd get_throttled` = 0x0).
- InfluxData hatte apt-Signaturschlüssel rotiert: `influxdata-archive.key` +
  `gpg --batch --no-tty --dearmor` (Debian 13 `sqv` ist streng).
- InfluxDB-Datenpfad: influxd's Erststart nutzte `~/.influxdbv2/`, `/etc/influxdb/
  config.toml` (Debian) zeigt aber auf `/var/lib/influxdb/` → nach Reboot frische
  leere Instanz, Token weg. Fix: config.toml fest auf `.influxdbv2`-Pfade +
  `daemon-reload && restart influxdb` VOR `influx setup` (in setup.sh drin).
- Collector als `User=nobody` scheiterte an `/etc/solar-collector.env` (600 root).
  → eigener System-User `solar`, Datei `640 root:solar`, `_env()` faengt OSError ab.
- `apt-listchanges` crasht auf Trixie → in setup.sh nicht relevant, ggf. purgen
  (Hook unter `/etc/apt/apt.conf.d/20listchanges` vorher wegmoven).

## Collector-Tuning (SolarEdge Modbus)
SolarEdge-WR sind langsam und zickig, wenn 4 Stück nacheinander gepollt werden.
`collector.py`:
- cacht die SunSpec-Modell-Offsets nach dem ersten Walk (`_MODEL_CACHE`)
- `_walk_models` prüft `mlen`/`addr`-Grenzen (kein `struct.pack`-Crash bei Müll-
  Antworten); `_mb_read` prüft Funktionscode + „Verbindung zu"
- `MB_TIMEOUT=15`, `MB_GAP=0.2` s, 1× Retry bei Fehler
- **WR nur jeden 2. Zyklus** (`INV_EVERY=2` → alle 60 s), Netz/Shelly bleiben 30 s.
  Env `INV_EVERY` in `/etc/solar-collector.env`.
- Vereinzelte `wrX_err: timed out` sind ok (Grafana interpoliert, kWh exakt).
- WR-Kühlkörper-Temp (`pv` Feld `temp_c`, SunSpec 103 Offset 32): **WR1 (SE12.5K)
  meldet im SLEEP `0`** (die SE25K wr2/3/4 melden weiter ~30 C). Collector wertet
  raw `0x0000` + `0x8000` als "kein Wert"; Dashboard-Query filtert zusätzlich
  `_value > 1.0`, sonst 0-Linie nachts.

## Dashboards (5 Stück, provisioniert aus `/var/lib/grafana/dashboards/`, Ordner **„Haustechnik"**)
Provider-YAML: `/etc/grafana/provisioning/dashboards/haustechnik.yaml` (`folder: Haustechnik`).
Org-Home-Dashboard = **Übersicht**.

| Datei | `pi/`-Quelle | uid | Inhalt |
|---|---|---|---|
| `uebersicht.json` | `grafana-uebersicht.json` | `htk-uebersicht` | **Startseite**: Strom/PV/Netz/Haus jetzt, Kessel/Boiler/Pool, Kühlräume, Außen+Luftdruck. Nav-Links oben rechts. |
| `solar.json` | `grafana-dashboard.json` | `solar-main` | **Strom & PV** (Energie / Power-to-Heat) |
| `heizung.json` | `grafana-heizung.json` | `htk-heizung` | **Heizung**: alle LOGO!8-Temps – Heizung, Schwimmbad, Lüftung (+Ein/Aus), Villa, Gartenhaus |
| `temperaturen.json` | `grafana-temperaturen.json` | `solar-temp` | **Sensoren**: Kühlräume, Gebäude-Temps, Wetterstation, BLU-Batterien |
| `kuehlraeume.json` | `grafana-kuehlraeume.json` | `kuehlraeume` | **Kühlräume Küche** – Wandanzeige, `?kiosk`. Login `kueche` (Viewer), Home = dieses. |

**Änderungen NUR in der Datei** (API-Edit blockiert Grafana bei provisionierten Dashboards):
`scp pi/grafana-*.json solar-pi:/tmp/ && ssh solar-pi 'for m in uebersicht:uebersicht dashboard:solar heizung:heizung temperaturen:temperaturen kuehlraeume:kuehlraeume; do sudo install -m644 /tmp/grafana-${m%:*}.json /var/lib/grafana/dashboards/${m#*:}.json; done'` (Reload ~10 s).
Anzeigenamen (Umlaute/Groß-Klein) werden per `map()` in den Flux-Queries gesetzt – die
InfluxDB-Tag-Werte bleiben ASCII (`vorkuehlraum` etc.).


## PAC → Modbus-TCP-Gateway (`pac_gateway.py`, Service `pac-gateway`)
Der PAC2200 (.73) nimmt nur ~3 Modbus-TCP-Clients. Der Gateway liest den PAC per
HTTP (kein Limit) und stellt Netz-/PV-Daten als Modbus-Register auf **Pi:502**
bereit → beliebig viele LOGOs können lesen, PAC hat alle Modbus-Slots frei.
- LOGO-Master → 192.168.40.45:502, Unit 1, FC3. Register-Map: Kopf von `pac_gateway.py`.
- Reg 0 = Netzleistung ×10 W (neg = Einspeisung), Reg 1 = Einspeisung W, Reg 6 = VALID (fail-safe bei 0).
- Läuft als User `solar` mit `CAP_NET_BIND_SERVICE` (Port 502). `journalctl -u pac-gateway -f`.

## NTP-Server für VLAN 40 (Bonus)
Der Pi synct selbst per chrony gegen externes NTP (VLAN 40 -> WAN UDP 123 ist offen)
und ist via `/etc/chrony/conf.d/allow-vlan40.conf` (`allow 192.168.40.0/24`) selbst
**NTP-Server** auf 192.168.40.45. → an den beiden PAC2200 den SNTP-Server auf
192.168.40.45 stellen (am Gerät oder mit SENTRON powerconfig aus dem .40-Netz),
dann laufen deren Uhren wieder richtig. `sudo chronyc clients` zeigt die Nutzer.

## Später
- IP evtl. auf .58 (wenn geklärt was da ist) oder UniFi-DHCP-Reservierung.
- PAC #2 (.72) Uhr auf +01:00 – korrigieren.
- WR3/WR4 per Modbus einzeln, wenn String-Details gebraucht.
- LOGO-PLCs (Modbus TCP) für Boiler-Steuerzustände.
- 15-min-Netzbezug → Alarm bei neuer Monatsspitze (Leistungspreis).
- NAS-Backup der InfluxDB (`influxd backup`).
- Eigenverbrauch/Autarkie-Panel (PV − Einspeisung), Grafana-Alert bei Lastspitze.
