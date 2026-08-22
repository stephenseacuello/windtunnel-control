#!/usr/bin/env python3
"""
rpm.py — type an RPM, the fan goes there. That's it.

    pip install pymodbus pyserial
    python rpm.py

    rpm> 600      set 600 rpm
    rpm> 0        stop
    rpm> q        quit (always stops the fan)

Standalone: no other files needed.
"""

import threading
import time

from pymodbus.client import ModbusSerialClient

# ── settings ──────────────────────────────────────────────────────────────
PORT        = "/dev/ttyVFD"   # or COM3 on Windows
BAUD        = 19200
UNIT        = 1               # drive parameter 5302
RPM_MAX     = 1700            # soft limit — top of the tested band
RPM_PER_HZ  = 29.17           # 1750 rpm nameplate / 60 Hz, direct drive
REF1_MAX_HZ = 60.0            # drive parameter 1105
MPS_PER_RPM, MPS_OFFSET = 0.02132, -0.424   # measured Feb 13

# ── Modbus register addresses (zero-based; manual's 40001 is address 0) ────
CW, REF, SW, ACT = 0, 1, 3, 4
READY, RUN = 0x047E, 0x047F   # ABB Drives profile control words

client = ModbusSerialClient(port=PORT, baudrate=BAUD, parity="N",
                            stopbits=1, bytesize=8, timeout=1)
lock = threading.Lock()
kw = {"slave": UNIT}
target_cw, target_ref = READY, 0


def write(addr, value):
    with lock:
        client.write_register(addr, int(value) & 0xFFFF, **kw)


def read(addr, count=1):
    with lock:
        return client.read_holding_registers(addr, count=count, **kw).registers


def keepalive():
    """
    Re-send the command twice a second.

    The drive faults and stops the fan if it stops hearing from us (parameters
    3018/3019). That watchdog is what makes it safe to run a 15 HP fan from a
    laptop — but it means we have to keep talking while you sit at the prompt.
    """
    while True:
        try:
            write(CW, target_cw)
            write(REF, target_ref)
        except Exception:
            pass          # bus is down; let the drive's watchdog stop the fan
        time.sleep(0.5)


def set_rpm(rpm):
    global target_cw, target_ref
    rpm = max(0, min(rpm, RPM_MAX))
    hz = rpm / RPM_PER_HZ
    target_ref = int(hz / REF1_MAX_HZ * 20000)

    if rpm == 0:
        target_cw = READY
        write(CW, READY)
    else:
        # Reference first, or the fan accelerates toward whatever setpoint was
        # left over from last time. Then READY→RUN, because the drive latches
        # on the rising edge of the run bit.
        write(REF, target_ref)
        write(CW, READY)
        time.sleep(0.05)
        target_cw = RUN
        write(CW, RUN)
    return rpm


def actual():
    hz = read(ACT)[0] / 10.0
    rpm = hz * RPM_PER_HZ
    return hz, rpm, MPS_PER_RPM * rpm + MPS_OFFSET


if not client.connect():
    raise SystemExit(f"could not open {PORT}")

try:                                  # pymodbus renamed this kwarg; probe once
    read(SW)
except TypeError:
    kw = {"device_id": UNIT}

threading.Thread(target=keepalive, daemon=True).start()

print(f"connected on {PORT} · limit {RPM_MAX} rpm · 'q' to quit")
try:
    while True:
        s = input("rpm> ").strip().lower()
        if s in ("q", "quit", "exit"):
            break
        if s in ("", "?"):
            hz, rpm, mps = actual()
            print(f"     {rpm:.0f} rpm · {hz:.1f} Hz · {mps:.1f} m/s")
            continue
        try:
            want = set_rpm(float(s))
        except ValueError:
            print("     type a number, ? for status, or q to quit")
            continue
        print(f"     -> {want:.0f} rpm · {want / RPM_PER_HZ:.1f} Hz · "
              f"{MPS_PER_RPM * want + MPS_OFFSET:.1f} m/s")
finally:
    # Always ramp down, however we got here — including Ctrl-C.
    print("\nstopping")
    target_cw, target_ref = READY, 0
    try:
        write(REF, 0)
        write(CW, READY)
    except Exception:
        pass
    client.close()
