#!/usr/bin/env python3
"""Modbus-TCP-Gateway: liest den PAC2200 (.73) per HTTP und stellt die
Netz-/PV-Daten als Modbus-Holding-Register bereit.

Zweck: der PAC2200 nimmt nur ~3 gleichzeitige Modbus-TCP-Clients. Statt dass
jeder LOGO direkt den PAC pollt, liest NUR dieser Gateway den PAC (per HTTP,
kein Modbus-Limit) und die LOGOs lesen vom Pi. -> beliebig viele LOGOs, PAC
sieht 0 Modbus-Clients.

LOGO-Konfiguration:  Modbus-Master -> 192.168.40.45 : 502, Unit-ID 1,
                     "Holding Register lesen" (FC 3), Startadresse siehe unten.

=== REGISTER-MAP (16-bit Holding Register, FC 3, Unit 1) ===
  Adr  Typ     Inhalt
  0    int16   Netzleistung in 10-W-Schritten  (± , negativ = Einspeisung)
                 -> Wert * 10 = Watt.  ±32760 -> ±327 kW
  1    uint16  Einspeisung  [W]   = max(0, -Netzleistung), geklemmt auf 65535
  2    uint16  Netzbezug    [W]   = max(0,  Netzleistung)
  3    int16   Netzleistung in 100-W-Schritten (grob, falls 10-W zu fein)
  4    uint16  PV-Produktion WR3+4 [W] (aus PAC .72), geklemmt
  5    uint16  Netzbezug heute [0,1 kWh]  (PAC TODAY_T1)  -> Wert / 10 = kWh
  6    uint16  VALID: 1 = Daten frisch (< 20 s), 0 = veraltet/Fehler
  7    uint16  Alter der Daten [s] seit letzter erfolgreicher PAC-Lesung
  8    int16   Netzleistung high word  (int32, Adr 8/9, W, big-endian)
  9    int16   Netzleistung low word
 10    uint16  PAC-Uhr Stunde   (LOCAL_TIME)
 11    uint16  PAC-Uhr Minute

=== Siemens-PAC-kompatibler Passthrough (fuer LOGOs, die schon fix auf das
    native PAC2200-Registerlayout programmiert sind, z.B. .71 Lastabwurf) ===
  1/2  float32 U L1-N [V]  (big-endian, 2 Register) -- PAC-Adresse "2" (1-basiert)
 65/66 float32 Netzleistung gesamt [W], signiert, + = Bezug, - = Einspeisung
                 (big-endian, 2 Register) -- PAC-Adresse "66" (1-basiert)
  Diese 2 Bloecke spiegeln exakt das native Siemens-Registerlayout, damit ein
  bereits am PAC .73 konfigurierter Modbus-Client NUR die IP auf den Pi
  (192.168.40.45) umstellen muss -- Register/Laenge/Typ bleiben gleich.
  (PAC2200 haengt an einem ~3-Client-Modbus-Limit; direkte Verbindungen
  zusaetzlicher LOGOs werden dort mit "Connection reset" abgewiesen.)

Bei VALID=0 muessen die LOGOs fail-safe schalten (Boiler nur Thermostat,
Ladestation Minimalstrom/aus, Lastabwurf loesen).
"""
import http.server  # noqa: F401  (nur fuer Doku)
import json
import os
import socket
import socketserver
import struct
import threading
import time
import urllib.request

PAC_GRID = os.environ.get("PAC_GRID_HOST", "192.168.40.73")
PAC_PV = os.environ.get("PAC_WR34_HOST", "192.168.40.72")
LISTEN_PORT = int(os.environ.get("GATEWAY_PORT", "502"))
POLL_S = float(os.environ.get("GATEWAY_POLL", "3"))
STALE_S = 20

# 68 Register (bis Adresse 66 fuer den Siemens-Passthrough), thread-safe
# ueber die GIL fuer einzelne Zuweisungen
REGS = [0] * 68
_last_ok = 0.0


def _clamp_u16(v):
    return max(0, min(65535, int(round(v))))


def _s16(v):
    v = int(round(v))
    return max(-32768, min(32767, v))


def _put_f32(regs, addr, value):
    """Big-endian IEEE754 float32 auf 2 Register (addr, addr+1) schreiben."""
    hi, lo = struct.unpack(">HH", struct.pack(">f", value))
    regs[addr], regs[addr + 1] = hi, lo


def poll_pac():
    global _last_ok
    while True:
        t0 = time.time()
        try:
            with urllib.request.urlopen(
                    "http://%s/data.json?type=OVERVIEW" % PAC_GRID, timeout=5) as r:
                ov = json.loads(r.read().decode())["OVERVIEW"]

            def val(k):
                x = ov.get(k)
                return x["value"] if isinstance(x, dict) else x

            p = val("P_SUM")
            if p is None:
                p = sum(val("P_L%d" % i) or 0.0 for i in (1, 2, 3))
            grid_w = p * 1000.0
            today_kwh = val("TODAY_T1") or 0.0
            lt = ov.get("LOCAL_TIME", "")

            u_l1n = None
            try:
                with urllib.request.urlopen(
                        "http://%s/data.json?type=INST_VALUES" % PAC_GRID, timeout=4) as ri:
                    iv = json.loads(ri.read().decode())["INST_VALUES"]
                v1 = iv.get("V_L1")
                u_l1n = v1["value"] if isinstance(v1, dict) else v1
            except Exception:
                pass

            pv_w = 0
            try:
                with urllib.request.urlopen(
                        "http://%s/data.json?type=OVERVIEW" % PAC_PV, timeout=4) as r2:
                    ov2 = json.loads(r2.read().decode())["OVERVIEW"]
                pp = ov2.get("P_SUM")
                pp = pp["value"] if isinstance(pp, dict) else pp
                pv_w = max(0.0, -(pp or 0.0) * 1000.0)
            except Exception:
                pass

            REGS[0] = _s16(grid_w / 10.0)
            REGS[1] = _clamp_u16(max(0.0, -grid_w))
            REGS[2] = _clamp_u16(max(0.0, grid_w))
            REGS[3] = _s16(grid_w / 100.0)
            REGS[4] = _clamp_u16(pv_w)
            REGS[5] = _clamp_u16(today_kwh * 10.0)
            hi, lo = struct.unpack(">hh", struct.pack(">i", int(grid_w)))
            REGS[8], REGS[9] = hi & 0xFFFF, lo & 0xFFFF
            if len(lt) >= 16:
                REGS[10] = int(lt[11:13])
                REGS[11] = int(lt[14:16])
            if u_l1n is not None:
                _put_f32(REGS, 1, u_l1n)          # HR "2" (1-basiert): U L1-N [V]
            _put_f32(REGS, 65, grid_w)            # HR "66" (1-basiert): Netzleistung gesamt [W]
            _last_ok = time.time()
        except Exception as e:
            print("PAC-Lesung fehlgeschlagen:", e, flush=True)

        age = time.time() - _last_ok
        REGS[6] = 1 if age < STALE_S else 0
        REGS[7] = _clamp_u16(age)
        time.sleep(max(0.5, POLL_S - (time.time() - t0)))


# ----------------------------------------------------------- Modbus TCP Server
class ModbusHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(30)
        while True:
            try:
                hdr = self._recv_n(7)
                if not hdr:
                    return
                tid, pid, length, unit = struct.unpack(">HHHB", hdr)
                pdu = self._recv_n(length - 1)
                if not pdu:
                    return
                resp = self._process(pdu)
                self.request.sendall(
                    struct.pack(">HHHB", tid, 0, len(resp) + 1, unit) + resp)
            except (socket.timeout, ConnectionError, OSError):
                return

    def _recv_n(self, n):
        buf = b""
        while len(buf) < n:
            c = self.request.recv(n - len(buf))
            if not c:
                return None
            buf += c
        return buf

    def _process(self, pdu):
        fc = pdu[0]
        if fc in (3, 4):  # read holding / input registers
            start, count = struct.unpack(">HH", pdu[1:5])
            if count < 1 or count > 125 or start + count > len(REGS):
                return struct.pack(">BB", fc | 0x80, 2)  # illegal data address
            data = b"".join(struct.pack(">H", REGS[start + i] & 0xFFFF)
                            for i in range(count))
            return struct.pack(">BB", fc, len(data)) + data
        return struct.pack(">BB", fc | 0x80, 1)  # illegal function


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    threading.Thread(target=poll_pac, daemon=True).start()
    srv = Server(("0.0.0.0", LISTEN_PORT), ModbusHandler)
    print("pac-gateway: Modbus TCP auf :%d  (PAC %s per HTTP alle %.0fs)"
          % (LISTEN_PORT, PAC_GRID, POLL_S), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
