#!/usr/bin/env python3
"""
wait_for_pmc.py — wait for the PMC to appear, then say what is on it.

    python src/wait_for_pmc.py

Written because an upload that fails between the 1200-baud touch and the DFU
handshake leaves the board enumerating as NEITHER a serial port nor a DFU
device, which looks exactly like a dead board and is not one. Flash is
untouched in that state: the transfer never began.
"""
import glob
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(timeout=90):
    print(f"\n  waiting up to {timeout}s for a PMC serial port...")
    print(f"  → unplug the USB, wait 5 s, plug it back in\n")
    t0 = time.monotonic()
    port = None
    while time.monotonic() - t0 < timeout:
        found = sorted(glob.glob("/dev/cu.usbmodem*"))
        if found:
            port = found[0]
            break
        time.sleep(0.5)
    if not port:
        print(f"  ✗ nothing appeared in {timeout}s.\n")
        print(f"    Try a different USB port or cable — a charge-only cable "
              f"powers the\n    board without enumerating it, which looks "
              f"identical to this.\n")
        print(f"    If the port still never appears, double-tap the Portenta's "
              f"RESET.\n    The green LED fading slowly in and out means it is "
              f"in the bootloader,\n    and an upload will then take.\n")
        return 1

    print(f"  ✓ {port} appeared after {time.monotonic()-t0:.1f}s")
    time.sleep(2.0)                       # let the sketch finish booting
    try:
        import serial
        s = serial.Serial(port, 115200, timeout=2.0)
        time.sleep(2.0)
        s.reset_input_buffer()
        for cmd in ("ID", "RPM?"):
            s.write((cmd + "\n").encode())
            time.sleep(0.5)
            out = []
            while s.in_waiting:
                out.append(s.readline().decode(errors="ignore").strip())
                time.sleep(0.05)
            reply = " | ".join(x for x in out if x) or "(no reply)"
            print(f"    {cmd:<5} -> {reply}")
        s.close()
    except Exception as e:
        print(f"    could not talk to it: {e}")
        return 1

    print(f"\n  If ID says 3.0, flash is intact and the failed upload cost "
          f"nothing.\n  If it says 5.0, the upload actually succeeded.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
