#!/usr/bin/env python3
"""
probe_load.py — find the Chroma and work out how it is connected.

    python probe_load.py                    # scan USB and serial
    python probe_load.py --host 192.168.1.50   # also try Ethernet
    python probe_load.py --verify           # then check every SCPI command

Run this the first time the instrument is plugged in. It reports which
transport works, and `--verify` then checks that the driver's SCPI mnemonics
are the ones this particular model accepts.

Both matter. A transport that does not connect fails loudly; a mode command
the instrument silently ignores does not, and produces a log full of
resistances that were never set.

Nothing here energises the load or touches the drive.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chroma_load import ChromaLoad, discover


def main():
    p = argparse.ArgumentParser(description="find and check the Chroma load")
    p.add_argument("--host", help="also try SCPI over TCP at this address")
    p.add_argument("--port", type=int, default=5025)
    p.add_argument("--baud", type=int, help="serial baud rate to try first")
    p.add_argument("--verify", action="store_true",
                   help="check every SCPI command the driver uses")
    p.add_argument("--show-failures", action="store_true",
                   help="print every port that did not answer")
    p.add_argument("--save", help="write the working transport to a JSON file")
    p.add_argument("--skip", nargs="*", default=[],
                   help="ports to leave alone, e.g. the PMC's")
    a = p.parse_args()

    found = discover({"host": a.host, "port": a.port, "baud": a.baud,
                      "show_failures": a.show_failures,
                      "skip_ports": a.skip})
    chroma = [(t, idn) for t, idn in found if "chroma" in idn.lower()]

    if not chroma:
        import platform
        print("\n  No Chroma found.\n")
        print("  Ports that exist right now:")
        import glob
        pats = (["/dev/cu.usbmodem*", "/dev/cu.usbserial*"]
                if sys.platform == "darwin" else
                ["/dev/ttyACM*", "/dev/ttyUSB*", "/dev/usbtmc*"])
        seen = [x for pat in pats for x in sorted(glob.glob(pat))]
        for x in seen:
            print(f"    {x}")
        if not seen:
            print("    (none — nothing is enumerating at all)")

        print("\n  Check in this order:")
        print("  1. Does a port appear when you plug the load in and vanish "
              "when you unplug it?")
        print("     If not, it is the cable (charge-only) or the instrument's "
              "USB port.")
        print("  2. On the load: Config/Mode → interface → USB. "
              "Shift+1 toggles Local.")
        if sys.platform == "darwin":
            print("  3. macOS has NO kernel USB-TMC driver. If the load "
                  "presents as TMC")
            print("     rather than a serial port, nothing will appear in "
                  "/dev at all and")
            print("     VISA is the only route:")
            print("       pip install pyvisa pyvisa-py pyusb")
            print("       python probe_load.py --verify")
        else:
            print("  3. USB-TMC needs a udev rule for non-root access — "
                  "see docs/06_chroma.md")
        print("  4. This unit has no Ethernet (GPIB/LAN slot is blanked), so "
              "--host will")
        print("     not help.")
        sys.exit(1)

    t, idn = chroma[0]
    print(f"\n  found: {idn}")
    print(f"  transport: {t.describe()}  (kind={t.kind})")

    spec = {"kind": t.kind}
    for attr in ("path", "port", "host", "resource", "baudrate"):
        if hasattr(t, attr) and getattr(t, attr) is not None:
            v = getattr(t, attr)
            # VISA resource strings can carry embedded NULs from the
            # instrument's serial-number field. They survive JSON and then
            # fail to match when the resource is reopened.
            if isinstance(v, str):
                v = v.replace("\x00", "")
            spec[attr] = v
    print(f"\n  record this in tunnel.json:\n    \"load\": {json.dumps(spec)}")

    if a.verify:
        print("\n  checking SCPI commands (load stays OFF)...")
        load = ChromaLoad(t)
        load.identity = idn
        load.verify_commands()

    if a.save:
        Path(a.save).write_text(json.dumps({"load": spec}, indent=2))
        print(f"\n  wrote {a.save}")

    t.close()


if __name__ == "__main__":
    main()
