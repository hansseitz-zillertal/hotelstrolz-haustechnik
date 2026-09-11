#!/usr/bin/env bash
# Einmal-Setup auf dem frisch aufgesetzten Raspberry Pi 5 (RasPi OS Lite 64-bit,
# Bookworm). Installiert InfluxDB 2 + Grafana + den Solar-Collector als Service.
#
#   scp -r pi/  hans@192.168.40.58:~/solar-pi
#   ssh hans@192.168.40.58
#   cd ~/solar-pi && sudo bash setup.sh
#
# Danach: Grafana unter http://192.168.40.58:3000  (admin / <gesetztes PW>)
set -euo pipefail

INFLUX_ORG=strolz
INFLUX_BUCKET=solar
INFLUX_USER=admin
: "${INFLUX_PASS:=strolz-$(date +%s)}"          # via Umgebung ueberschreibbar
: "${INFLUX_TOKEN:=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40)}"
: "${GRAFANA_PASS:=$INFLUX_PASS}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ">>> System aktualisieren + Basiswerkzeuge"
apt-get update -q
apt-get install -y -q curl gnupg chrony libsnap7-1
# python-snap7: LOGO!8-Heizungstemperaturen via S7 (Collector faengt ImportError ab,
# laeuft also auch ohne). PEP668 -> --break-system-packages.
pip install --quiet --break-system-packages --root-user-action=ignore python-snap7 || true

mkdir -p /usr/share/keyrings
rm -f /tmp/influx.key /tmp/grafana.key

echo ">>> InfluxDB 2 Repo"
curl -fsSL https://repos.influxdata.com/influxdata-archive.key \
  | gpg --batch --yes --no-tty --dearmor -o /usr/share/keyrings/influxdata-archive.gpg
echo "deb [signed-by=/usr/share/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/debian stable main" \
  > /etc/apt/sources.list.d/influxdata.list

echo ">>> Grafana Repo"
curl -fsSL https://apt.grafana.com/gpg.key \
  | gpg --batch --yes --no-tty --dearmor -o /usr/share/keyrings/grafana.gpg
echo "deb [signed-by=/usr/share/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
  > /etc/apt/sources.list.d/grafana.list

apt-get update -q
apt-get install -y -q influxdb2 influxdb2-cli grafana

echo ">>> InfluxDB: Datenpfad fixieren + starten"
# Debian-Paket-config.toml zeigt auf /var/lib/influxdb/, influxd's Erststart aber
# oft auf ~/.influxdbv2/ -> nach einem Reboot laufen die auseinander (Token weg).
# Deshalb EINEN Pfad erzwingen und influxd frisch mit dieser Config starten.
mkdir -p /var/lib/influxdb/.influxdbv2/engine
chown -R influxdb:influxdb /var/lib/influxdb/.influxdbv2
cat > /etc/influxdb/config.toml <<'EOF'
bolt-path = "/var/lib/influxdb/.influxdbv2/influxd.bolt"
engine-path = "/var/lib/influxdb/.influxdbv2/engine"
sqlite-path = "/var/lib/influxdb/.influxdbv2/influxd.sqlite"
EOF
systemctl daemon-reload
systemctl enable influxdb
systemctl restart influxdb
for i in $(seq 1 40); do curl -sf http://localhost:8086/health >/dev/null && break; sleep 1; done

if ! influx org list --host http://localhost:8086 --token "$INFLUX_TOKEN" >/dev/null 2>&1; then
  echo ">>> InfluxDB einrichten (org=$INFLUX_ORG bucket=$INFLUX_BUCKET, Retention unbegrenzt)"
  influx setup --host http://localhost:8086 \
    --org "$INFLUX_ORG" --bucket "$INFLUX_BUCKET" \
    --username "$INFLUX_USER" --password "$INFLUX_PASS" \
    --token "$INFLUX_TOKEN" --retention 0 --force
else
  echo ">>> InfluxDB schon eingerichtet - ueberspringe setup"
fi

echo ">>> Collector installieren"
id solar >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin solar
install -d /opt/solar-collector
install -m 0755 "$SRC_DIR/collector.py" /opt/solar-collector/collector.py
cat > /etc/solar-collector.env <<EOF
INFLUX_URL=http://localhost:8086
INFLUX_ORG=$INFLUX_ORG
INFLUX_BUCKET=$INFLUX_BUCKET
INFLUX_TOKEN=$INFLUX_TOKEN
INTERVAL=30
EOF
chown root:solar /etc/solar-collector.env
chmod 640 /etc/solar-collector.env
install -m 0644 "$SRC_DIR/solar-collector.service" /etc/systemd/system/solar-collector.service
systemctl daemon-reload
systemctl enable --now solar-collector

echo ">>> Grafana: Datasource + Dashboard provisionieren"
install -d /etc/grafana/provisioning/datasources /etc/grafana/provisioning/dashboards /var/lib/grafana/dashboards
cat > /etc/grafana/provisioning/datasources/influx.yaml <<EOF
apiVersion: 1
datasources:
  - name: InfluxDB
    type: influxdb
    access: proxy
    url: http://localhost:8086
    jsonData:
      version: Flux
      organization: $INFLUX_ORG
      defaultBucket: $INFLUX_BUCKET
    secureJsonData:
      token: $INFLUX_TOKEN
    isDefault: true
EOF
cat > /etc/grafana/provisioning/dashboards/haustechnik.yaml <<EOF
apiVersion: 1
providers:
  - name: haustechnik
    folder: Haustechnik
    type: file
    options:
      path: /var/lib/grafana/dashboards
EOF
rm -f /etc/grafana/provisioning/dashboards/solar.yaml
install -m 0644 "$SRC_DIR/grafana-uebersicht.json"   /var/lib/grafana/dashboards/uebersicht.json
install -m 0644 "$SRC_DIR/grafana-dashboard.json"    /var/lib/grafana/dashboards/solar.json
install -m 0644 "$SRC_DIR/grafana-heizung.json"      /var/lib/grafana/dashboards/heizung.json
install -m 0644 "$SRC_DIR/grafana-temperaturen.json" /var/lib/grafana/dashboards/temperaturen.json
install -m 0644 "$SRC_DIR/grafana-kuehlraeume.json"  /var/lib/grafana/dashboards/kuehlraeume.json

grafana-cli admin reset-admin-password "$GRAFANA_PASS" >/dev/null 2>&1 || true
systemctl enable --now grafana-server
systemctl restart grafana-server

IP=$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -1)
echo
echo "============================================================"
echo "  FERTIG"
echo "  Grafana : http://$IP:3000    admin / $GRAFANA_PASS"
echo "  InfluxDB: http://$IP:8086    $INFLUX_USER / $INFLUX_PASS"
echo "  InfluxDB-Token (in /etc/solar-collector.env): $INFLUX_TOKEN"
echo "  Logs    : journalctl -u solar-collector -f"
echo "============================================================"
