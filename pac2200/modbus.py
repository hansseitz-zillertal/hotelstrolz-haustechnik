#!/usr/bin/env python3
"""Minimal Modbus/TCP client for the Siemens SENTRON PAC2200 main meter.

No external dependencies. Modbus/TCP is a thin wrapper around the PDU:
  MBAP header = transaction(2) protocol(2)=0 length(2) unit(1)

Relevant PAC2200 registers (Modbus offset == register address, 0-based):
  799   RW  2 reg  Date/time (UTC)          Unix_ts (uint32, seconds since 1970)
  545   R   2 reg  Time stamp current period (UTC)  Unix_ts
  62993 RW  2 reg  SNTP server IP address   uint32
  62995 RW  2 reg  SNTP client mode         0=off 1=active-client 2=broadcast
  62991 RW  2 reg  DHCP on/off
  63001 RW  2 reg  device IP address        uint32
Status bits (FC 0x02, read discrete inputs; offset == bit address):
  122  SNTP not synchronized
  128  Date/time inaccurate
  130  Device is hardware write-protected
  131  Modbus communication is write-protected

Values are big-endian, high register first.
"""
import argparse
import datetime as dt
import socket
import struct
import sys

HOST = "192.168.40.73"
PORT = 502
UNIT = 1


class ModbusError(Exception):
    pass


def _txn(sock, unit, pdu):
    req = struct.pack(">HHHB", 1, 0, len(pdu) + 1, unit) + pdu
    sock.sendall(req)
    head = _recvn(sock, 7)
    _, _, length, _ = struct.unpack(">HHHB", head)
    body = _recvn(sock, length - 1)
    if body[0] & 0x80:
        raise ModbusError(f"exception code {body[1]} on FC {body[0] & 0x7f:#x}")
    return body


def _recvn(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ModbusError("connection closed")
        buf += chunk
    return buf


def connect(host=HOST, port=PORT, timeout=5):
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(timeout)
    return s


def read_holding(sock, addr, count, unit=UNIT):
    body = _txn(sock, unit, struct.pack(">BHH", 0x03, addr, count))
    nbytes = body[1]
    return body[2:2 + nbytes]


def read_discrete(sock, addr, count, unit=UNIT):
    body = _txn(sock, unit, struct.pack(">BHH", 0x02, addr, count))
    nbytes = body[1]
    bits = []
    for i in range(count):
        bits.append((body[2 + i // 8] >> (i % 8)) & 1)
    return bits


def write_holding(sock, addr, regs, unit=UNIT):
    data = b"".join(struct.pack(">H", r) for r in regs)
    pdu = struct.pack(">BHHB", 0x10, addr, len(regs), len(data)) + data
    body = _txn(sock, unit, pdu)
    return struct.unpack(">HH", body[1:5])


def u32(raw):
    return struct.unpack(">I", raw)[0]


def u32_regs(value):
    return [(value >> 16) & 0xFFFF, value & 0xFFFF]


def ip_str(value):
    return ".".join(str(b) for b in struct.pack(">I", value))


def diagnose(unit=UNIT, host=HOST):
    s = connect(host=host)
    try:
        dev_utc = u32(read_holding(s, 799, 2, unit))
        period_ts = u32(read_holding(s, 545, 2, unit))
        sntp_ip = u32(read_holding(s, 62993, 2, unit))
        sntp_mode = u32(read_holding(s, 62995, 2, unit))
        dhcp = u32(read_holding(s, 62991, 2, unit))
        dev_ip = u32(read_holding(s, 63001, 2, unit))
        bits = {}
        for off, name in [(122, "SNTP not synchronized"),
                          (128, "Date/time inaccurate"),
                          (130, "HW write-protected"),
                          (131, "Modbus write-protected")]:
            try:
                bits[name] = read_discrete(s, off, 1, unit)[0]
            except ModbusError as e:
                bits[name] = f"?({e})"
    finally:
        s.close()

    now = dt.datetime.now(dt.timezone.utc)
    dev_dt = dt.datetime.fromtimestamp(dev_utc, dt.timezone.utc)
    skew = (dev_dt - now).total_seconds()
    modes = {0: "OFF", 1: "active client", 2: "broadcast client"}
    print(f"device clock (UTC) : {dev_dt:%Y-%m-%d %H:%M:%S}  (unix {dev_utc})")
    print(f"real time    (UTC) : {now:%Y-%m-%d %H:%M:%S}")
    print(f"skew              : {skew:+.0f} s  ({skew/60:+.1f} min)")
    print(f"last period ts    : {dt.datetime.fromtimestamp(period_ts, dt.timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
    print(f"SNTP client mode  : {sntp_mode} ({modes.get(sntp_mode, '?')})")
    print(f"SNTP server IP    : {ip_str(sntp_ip)}")
    print(f"DHCP              : {'on' if dhcp else 'off'}")
    print(f"device IP         : {ip_str(dev_ip)}")
    for k, v in bits.items():
        print(f"status: {k:<24}: {v}")


def ip_u32(s):
    parts = [int(p) for p in s.split(".")]
    return struct.unpack(">I", bytes(parts))[0]


def set_sntp(host, ip, unit=UNIT):
    s = connect(host=host)
    try:
        write_holding(s, 62993, u32_regs(ip_u32(ip)), unit)
        new_ip = ip_str(u32(read_holding(s, 62993, 2, unit)))
        print(f"{host} -> SNTP server IP set to {new_ip}")
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=UNIT)
    ap.add_argument("--host", default=HOST)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diagnose")
    r = sub.add_parser("read"); r.add_argument("addr", type=int); r.add_argument("count", type=int, nargs="?", default=2)
    sn = sub.add_parser("set-sntp", help="write SNTP server IP (register 62993); only reachable from the meter's own subnet (192.168.40.x), not routed from the Mac")
    sn.add_argument("ip")
    args = ap.parse_args()

    if args.cmd == "diagnose":
        diagnose(args.unit, args.host)
    elif args.cmd == "read":
        s = connect(host=args.host)
        try:
            raw = read_holding(s, args.addr, args.count, args.unit)
        finally:
            s.close()
        print("raw   :", raw.hex())
        print("u16   :", [struct.unpack(">H", raw[i:i+2])[0] for i in range(0, len(raw), 2)])
        if len(raw) >= 4:
            print("u32   :", struct.unpack(">I", raw[:4])[0])
            print("float :", struct.unpack(">f", raw[:4])[0])
    elif args.cmd == "set-sntp":
        set_sntp(args.host, args.ip, args.unit)


if __name__ == "__main__":
    main()
