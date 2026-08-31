#!/usr/bin/env python3
"""
tunnel_node.py — the Nano 33 BLE Sense node: ambient air, and tower vibration.

    python src/tunnel_node.py read              temperature, pressure, density
    python src/tunnel_node.py imu               one accel + gyro sample
    python src/tunnel_node.py burst 2000        capture, save CSV, report peaks
    python src/tunnel_node.py rate              what the board actually achieves

The board runs `firmware/tunnel_node/tunnel_node.ino`. Its line protocol is
deliberately the same shape as the PMC's, so the host treats both the same
way: one line in, one line out, diagnostics prefixed '#'.

═══════════════════════════════════════════════════════════════════════════
WHY THIS NEVER PROBES THE PMC'S PORT
═══════════════════════════════════════════════════════════════════════════
On macOS a /dev/cu.* device can be opened by more than one process at a time.
Scanning every serial port for the node would therefore open the PMC's port
WHILE the dashboard holds it, and the two readers would take each other's
replies — a Modbus master receiving the answer to somebody else's question,
mid-sweep, with a 15 HP fan running.

So autodetection is deliberately narrow: it skips the port `data/tunnel.json`
names for the drive, and it refuses rather than guessing when that leaves it
with nothing. A missing ambient reading costs a line in a CSV. A disturbed
drive link costs the session.

═══════════════════════════════════════════════════════════════════════════
WHAT THE NUMBERS ARE AND ARE NOT
═══════════════════════════════════════════════════════════════════════════
**Density is dry-air.** The Lite board omits the HTS221, so there is no
humidity, and `rho = p / (287.05 * T)` reads about 1% high on a humid day.
Recorded as a known bias, not corrected by a guess.

**Burst is accelerometer only.** The firmware writes the gyro columns as zero:
the LSM9DS1 gyro saturates at 2000 dps and a blade passing at 333 rpm exceeds
it, so the channel is meaningless here. Tower motion is an accelerometer
measurement anyway.

**Burst is unpaced.** The firmware runs the capture loop flat out and records
the true timestamp of each sample, because pacing to a nominal interval adds
jitter rather than removing it. That means the samples are NOT on a uniform
grid, and anything spectral has to resample first — `spectrum()` below does,
and says so.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BAUD = 115200


class NodeError(RuntimeError):
    pass


def _drive_port():
    """The port the drive is on, which must never be probed."""
    try:
        cfg = json.loads((ROOT / "data" / "tunnel.json").read_text())
        return (cfg.get("transport") or {}).get("port")
    except Exception:
        return None


def resolve_port(explicit=None):
    """
    Find the node without touching the drive.

    Order: explicit flag, then `tunnel_node.port` in tunnel.json, then the one
    remaining USB serial port once the drive's is excluded. Refuses when that
    is ambiguous — opening the wrong device here means opening the drive link.
    """
    if explicit:
        return explicit
    try:
        cfg = json.loads((ROOT / "data" / "tunnel.json").read_text())
        p = (cfg.get("tunnel_node") or {}).get("port")
        if p and Path(p).exists():
            return p
    except Exception:
        pass

    drive = _drive_port()
    found = [p for p in sorted(glob.glob("/dev/cu.usbmodem*")) if p != drive]
    if len(found) == 1:
        return found[0]
    if not found:
        raise NodeError(
            "no candidate port for the tunnel node.\n"
            f"  The drive is on {drive or 'an unknown port'} and is excluded.\n"
            "  Plug the Nano in, or record its port as tunnel_node.port in "
            "data/tunnel.json.")
    raise NodeError(
        f"several candidate ports: {', '.join(found)}\n"
        f"  Pass --port. Guessing risks opening the drive link, and on macOS a "
        f"/dev/cu.* device\n  can be opened by two processes at once — the "
        f"dashboard would start losing replies.")


class TunnelNode:
    """One line in, one line out. Same shape as the PMC transport."""

    def __init__(self, port=None, baud=DEFAULT_BAUD, timeout=2.0):
        self.port = resolve_port(port)
        self.baud, self.timeout = baud, timeout
        self.ser = None
        self.identity = None

    # ── connection ───────────────────────────────────────────────────────

    def connect(self, settle=2.5):
        import serial
        self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        time.sleep(settle)                 # the board reboots on DTR

        # LISTEN BEFORE SPEAKING, for two separate reasons.
        #
        # The first is real and was observed: the very first connect returned
        # `ERR unknown command \x01\x03\x04P\x00\x01+ID` — stale bytes sitting
        # in the node's input buffer, concatenated with the ID that had just
        # been sent, so the board saw one nonsense line. Draining before
        # writing removes that.
        #
        # The second has not happened and is the one worth guarding: on macOS
        # a /dev/cu.* device can be opened by more than one process, so
        # probing for the node can open the DRIVE's port while the dashboard
        # holds it, and the two readers take each other's replies. Excluding
        # it by config is not enough — transport.port has gone stale four
        # times in two weeks. What can be relied on is what a port says
        # unprompted: the PMC streams `T,` telemetry and Modbus binary, and
        # neither looks like anything this node emits.
        sniff = b""
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1.2:
            chunk = self.ser.read(self.ser.in_waiting or 1)
            if chunk:
                sniff += chunk
            if len(sniff) > 512:
                break
        looks_like_drive = (
            b"T," in sniff or b"acs550" in sniff.lower() or
            any(b > 127 for b in sniff))
        if looks_like_drive:
            self.close()
            raise NodeError(
                f"{self.port} is the DRIVE link, not the node — it is "
                f"streaming\n  PMC telemetry. Nothing was written to it.\n"
                f"  Fix transport.port in data/tunnel.json, or pass --port.")

        self.ser.reset_input_buffer()
        self.identity = self.command("ID")
        if "tunnel-node" not in self.identity:
            self.close()
            raise NodeError(
                f"{self.port} answered {self.identity!r} — that is not the "
                f"tunnel node.\n  If it says 'acs550-pmc' you have just "
                f"opened the DRIVE link; unplug nothing and check "
                f"tunnel_node.port in data/tunnel.json.")
        return self

    def close(self):
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self.ser = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()
        return False

    # ── protocol ─────────────────────────────────────────────────────────

    def command(self, line, timeout=None):
        """Send one line, return the first non-comment reply."""
        if self.ser is None:
            raise NodeError("not connected")
        self.ser.reset_input_buffer()
        self.ser.write((line + "\n").encode())
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            raw = self.ser.readline().decode(errors="ignore").strip()
            if not raw or raw.startswith("#"):
                continue                   # board diagnostics, not a reply
            return raw
        raise NodeError(f"no reply to {line!r} within {timeout or self.timeout}s")

    def ambient(self):
        """(temp_c, pressure_pa, density_kg_m3). Density is DRY air."""
        r = self.command("READ")
        if not r.startswith("OK READ"):
            raise NodeError(r)
        t, p, rho = r.split()[2:5]
        return float(t), float(p), float(rho)

    def imu(self):
        """(ax, ay, az) in g and (gx, gy, gz) in dps, one sample."""
        r = self.command("IMU")
        if not r.startswith("OK IMU"):
            raise NodeError(r)
        v = [float(x) for x in r.split()[2:8]]
        return tuple(v[:3]), tuple(v[3:])

    def mark(self, label):
        """
        Pin the board's clock to the host's.

        The two crystals are unrelated — 50 ppm is 60 ms over 20 minutes,
        about 30 samples at burst rate, enough to smear the phase between
        "gust arrived" and "tower responded", which IS the measurement. Two
        marks bracketing a run give a linear mapping.

        Returns (host_unix, board_micros).
        """
        host = time.time()
        r = self.command(f"MARK {label}")
        if not r.startswith("OK MARK"):
            raise NodeError(r)
        return host, int(r.split()[-1])

    def rate(self):
        """What the board MEASURES itself achieving, not what it was set to."""
        r = self.command("RATE?")
        if not r.startswith("OK RATE"):
            raise NodeError(r)
        f = r.split()
        return {f[i]: f[i + 1] for i in range(2, len(f) - 1, 2)}

    def burst(self, n=2000, timeout=60.0):
        """
        Capture n accelerometer samples flat out and return them.

        Returns (rate_hz, rows) where each row is
        (us, ax_g, ay_g, az_g, gx_dps, gy_dps, gz_dps). The gyro columns are
        ZERO by design — see the module docstring.
        """
        if self.ser is None:
            raise NodeError("not connected")
        self.ser.reset_input_buffer()
        self.ser.write(f"BURST {int(n)}\n".encode())
        deadline = time.monotonic() + timeout
        hz, rows, in_csv = None, [], False
        while time.monotonic() < deadline:
            raw = self.ser.readline().decode(errors="ignore").strip()
            if not raw:
                continue
            if raw.startswith("ERR"):
                raise NodeError(raw)
            if raw.startswith("OK BURST"):
                hz = float(raw.split()[-1])
                continue
            if raw.startswith("us,"):
                in_csv = True
                continue
            if raw.startswith("END BURST"):
                return hz, rows
            if in_csv:
                try:
                    parts = raw.split(",")
                    rows.append((int(parts[0]), *[float(x) for x in parts[1:7]]))
                except (ValueError, IndexError):
                    continue
        raise NodeError(f"burst did not finish within {timeout}s "
                        f"({len(rows)} rows received)")


# ── analysis ──────────────────────────────────────────────────────────────

def spectrum(rows, axis="mag", nfft=None):
    """
    Amplitude spectrum of a burst.

    The capture is UNPACED — the firmware runs flat out and timestamps each
    sample, because pacing adds jitter rather than removing it. So the samples
    are not on a uniform grid and an FFT of them straight would smear every
    line. This resamples onto a uniform grid at the mean rate first.

    Returns (freqs_hz, amplitude, fs, note).
    """
    import numpy as np
    if len(rows) < 32:
        return [], [], 0.0, "too few samples"
    t = np.array([r[0] for r in rows], float) * 1e-6
    ax = np.array([r[1] for r in rows], float)
    ay = np.array([r[2] for r in rows], float)
    az = np.array([r[3] for r in rows], float)
    sig = {"x": ax, "y": ay, "z": az}.get(
        axis, np.sqrt(ax ** 2 + ay ** 2 + az ** 2))

    span = t[-1] - t[0]
    if span <= 0:
        return [], [], 0.0, "timestamps did not advance"
    fs = (len(t) - 1) / span
    grid = np.linspace(t[0], t[-1], len(t))
    sig = np.interp(grid, t, sig)

    sig = sig - sig.mean()                 # DC is 1 g of gravity, not signal
    n = int(nfft or len(sig))
    win = np.hanning(len(sig))
    # Coherent gain of a Hann window is 0.5; without it every amplitude reads
    # half what it is.
    amp = np.abs(np.fft.rfft(sig * win, n=n)) * 2.0 / (len(sig) * 0.5)
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    jitter = float(np.std(np.diff(t)) / np.mean(np.diff(t)))
    return (freqs.tolist(), amp.tolist(), float(fs),
            f"resampled onto a uniform grid; sample-interval jitter "
            f"{100 * jitter:.1f}% of the mean")


def blade_pass_hz(rotor_rpm, blades=3):
    """
    The frequency a tower sees from a passing blade.

    Worth naming on any spectrum from this rig: a peak at rotor_rpm/60 is
    imbalance, a peak at that times the blade count is blade passing, and they
    are different faults with different fixes.
    """
    return rotor_rpm / 60.0 * blades


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("mode", choices=["read", "imu", "burst", "rate", "id"])
    ap.add_argument("n", nargs="?", type=int, default=2000)
    ap.add_argument("--port", default=None)
    ap.add_argument("--csv", default=None, help="write a burst here")
    a = ap.parse_args()

    try:
        node = TunnelNode(a.port).connect()
    except NodeError as e:
        raise SystemExit(f"\n  {e}\n")

    try:
        if a.mode == "id":
            print(f"  {node.identity}")
        elif a.mode == "read":
            t, p, rho = node.ambient()
            print(f"  {t:.2f} °C   {p:,.0f} Pa   rho {rho:.4f} kg/m³")
            print(f"  (dry air — the Lite has no humidity sensor, so this "
                  f"reads ~1% high on a humid day)")
        elif a.mode == "imu":
            acc, gyr = node.imu()
            print(f"  accel  {acc[0]:+.4f} {acc[1]:+.4f} {acc[2]:+.4f}  g")
            print(f"  gyro   {gyr[0]:+.2f} {gyr[1]:+.2f} {gyr[2]:+.2f}  dps")
        elif a.mode == "rate":
            for k, v in node.rate().items():
                print(f"  {k:<18} {v}")
        elif a.mode == "burst":
            print(f"  capturing {a.n} samples…")
            hz, rows = node.burst(a.n)
            print(f"  {len(rows)} samples at {hz:.1f} Hz measured")
            out = Path(a.csv) if a.csv else (
                ROOT / "logs" / f"burst_{time.strftime('%Y%m%d_%H%M%S')}.csv")
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["us", "ax_g", "ay_g", "az_g",
                            "gx_dps", "gy_dps", "gz_dps"])
                w.writerows(rows)
            print(f"  wrote {out}")
            fr, am, fs, note = spectrum(rows)
            if fr:
                import numpy as np
                a_ = np.array(am); f_ = np.array(fr)
                band = (f_ > 1.0)
                top = np.argsort(a_[band])[-4:][::-1]
                print(f"\n  fs {fs:.0f} Hz — {note}")
                print(f"  strongest lines above 1 Hz:")
                for i in top:
                    print(f"    {f_[band][i]:7.1f} Hz   {a_[band][i]*1000:7.2f} mg")
    finally:
        node.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
