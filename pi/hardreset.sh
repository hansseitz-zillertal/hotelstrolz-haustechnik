#!/usr/bin/env bash
# Hard-Reset des solar-pi über den Shelly-Stecker davor (192.168.40.230,
# Shelly Plug S Gen3, keine Auth). Nur nutzen, wenn der Pi per SSH tot ist.
#   ./hardreset.sh          # aus -> 8 s warten -> ein
#   ./hardreset.sh status   # nur Status zeigen
set -eu
PLUG=${SHELLY_PLUG:-192.168.40.230}

case "${1:-cycle}" in
  status)
    curl -s "http://$PLUG/rpc/Switch.GetStatus?id=0" \
      | python3 -c 'import sys,json;d=json.load(sys.stdin);print("output=%s  %.1f W  %.1f V" % (d["output"],d["apower"],d["voltage"]))'
    ;;
  cycle)
    echo "Pi-Strom AUS ..."
    curl -s "http://$PLUG/rpc/Switch.Set?id=0&on=false" >/dev/null
    sleep 8
    echo "Pi-Strom EIN ..."
    curl -s "http://$PLUG/rpc/Switch.Set?id=0&on=true" >/dev/null
    echo "Pi bootet jetzt (~40-60 s bis SSH)."
    ;;
  *) echo "usage: $0 [cycle|status]"; exit 1 ;;
esac
