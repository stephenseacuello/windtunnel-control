#!/usr/bin/env python3
"""
daq_integration.py — connecting Jeong lab's acquisition to the tunnel.

Three patterns, in increasing order of how much the two labs have to agree on.
Pick one; they are alternatives, not stages.

    python daq_integration.py --explain          # no hardware, prints the options

═══════════════════════════════════════════════════════════════════════════
READ THIS BEFORE PICKING ONE
═══════════════════════════════════════════════════════════════════════════
The question is not "how do I read a DAQ channel" — `velocity_source.py`
already does that. The question is **which lab owns which risk**, and the three
patterns divide it differently:

  A  one machine, one process     tightest sync, both labs share a codebase
  B  network service              Pi owns the fan, DAQ owns the measurement
  C  independent + post-align     no coupling at all, align on timestamps

Pattern B is usually right for a two-lab collaboration. Jeong's side never
installs pymodbus, never learns what a control word is, and cannot leave the
fan running. One team owns the hazard; the other owns the measurement; the
interface between them is four HTTP endpoints.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ══════════════════════════════════════════════════════════════════════════
# PATTERN A — one process, sample-synchronous
# ══════════════════════════════════════════════════════════════════════════
# The DAQ becomes a velocity source, and the player logs it in the same row as
# the commanded and measured frequency. Nothing to align afterwards: the rows
# are the alignment.
#
# Use when one person runs both halves and you want the tightest possible
# correspondence between command and measurement.

def pattern_a(port="/dev/ttyVFD", channel="cDAQ1Mod1/ai0"):
    import gusts
    from acs550 import ACS550
    from calibration import Calibration
    from config import TunnelConfig
    from player import ProfilePlayer
    from velocity_source import DaqSource, SensorCalibration

    cfg = TunnelConfig.load("tunnel.json")

    # The sensor calibration is NOT the drive calibration. One describes the
    # probe, the other the fan. Conflating them is how a swapped anemometer
    # silently corrupts a season of data.
    #
    # `form` matters more than the coefficients — see src/fit_sensor.py. The
    # value below is provisional pending the clean sweep described in
    # reference/README.md.
    sensor = SensorCalibration(a=115.0, b=1.5, form="linear",
                               source="March 2 cross-calibration, PROVISIONAL")

    src = DaqSource(channel, sensor,
                    rate=1000, samples=200,   # 0.2 s of data per poll
                    average_s=2.0,            # controller wants a smooth value
                    stale_after_s=5.0).start()

    t, u = gusts.one_minus_cosine(u_mean=25, u_gust=8, gust_length=20)

    try:
        with ACS550(port) as drive:
            drive.start_keepalive()
            drive.start(float(u[0]))
            time.sleep(4 * (cfg.tau or 5))     # settle: at least 4 tau

            player = ProfilePlayer(drive, log_path="logs/gust_with_daq.csv",
                                   hz_limit=cfg.hz_limit,
                                   velocity_source=src,
                                   metadata={"mode": "pattern_a",
                                             "daq_channel": channel,
                                             "sensor": sensor.to_dict()})
            summary = player.play(t, u, return_to=float(u[0]))
            print(f"  velocity coverage: {summary['velocity_coverage']:.0%}")
    finally:
        src.stop()


# ══════════════════════════════════════════════════════════════════════════
# PATTERN B — network service  (recommended for two labs)
# ══════════════════════════════════════════════════════════════════════════
# The Pi runs the dashboard; the DAQ machine drives it over HTTP and runs
# acquisition on its own clock. This is a client for that side — nothing here
# imports pymodbus or knows what a control word is, which is the point.

class TunnelClient:
    """
    Minimal client for the dashboard's API. Give this file to Jeong's lab.

    Deliberately has no way to bypass the soft limit, clear an E-stop, or
    write a drive parameter. Those live behind the dashboard, on the machine
    whose operator can see the tunnel.
    """

    def __init__(self, base="http://tunnel-pi:5000", timeout=10):
        self.base, self.timeout = base.rstrip("/"), timeout

    def _get(self, path, **params):
        import json
        import urllib.parse
        import urllib.request
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=self.timeout) as r:
            return json.load(r)

    def _post(self, path, payload):
        import json
        import urllib.request
        req = urllib.request.Request(
            f"{self.base}{path}", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def state(self):
        """Current Hz, RPM, m/s, current, status bits — and a timestamp."""
        return self._get("/api/state")

    def set_velocity(self, mps):
        return self._post("/api/setpoint", {"value": mps, "units": "mps"})

    def start(self):
        return self._post("/api/go", {})

    def stop(self):
        return self._post("/api/stop", {})

    def wait_settled(self, target_mps, tol=0.2, timeout=180, poll=2.0):
        """
        Block until the tunnel is at the target and steady.

        Two conditions, because either alone lies: close to target, AND not
        still moving. A tunnel passing through the setpoint on its way
        somewhere else satisfies the first and not the second.
        """
        t0, history = time.time(), []
        while time.time() - t0 < timeout:
            s = self.state()
            v = (s.get("measured") or {}).get("mps")
            if v is not None:
                history.append(v)
                recent = history[-4:]
                if (abs(v - target_mps) < tol and len(recent) == 4
                        and max(recent) - min(recent) < tol):
                    return v
            time.sleep(poll)
        raise TimeoutError(f"tunnel did not settle at {target_mps} m/s")


def pattern_b(base="http://tunnel-pi:5000"):
    """A sweep driven from the DAQ machine."""
    tunnel = TunnelClient(base)

    tunnel.set_velocity(10.0)
    tunnel.start()
    try:
        for target in (10, 14, 18, 22, 26):
            tunnel.set_velocity(target)
            actual = tunnel.wait_settled(target)
            print(f"  settled at {actual:.2f} m/s (asked {target})")

            # ─── ACQUIRE HERE, on your own clock ───
            # Record the tunnel state at the start and end of the window so the
            # two records can be aligned afterwards without trusting a
            # stopwatch:
            #
            #   before = tunnel.state()
            #   data   = daq_task.read(...)
            #   after  = tunnel.state()
            #
            # Both ends carry `t` (unix time). If both machines run NTP, the
            # alignment is good to milliseconds — far finer than anything the
            # tunnel does.
            time.sleep(15)
    finally:
        tunnel.stop()


# ══════════════════════════════════════════════════════════════════════════
# PATTERN C — independent, aligned afterwards
# ══════════════════════════════════════════════════════════════════════════
# Neither side talks to the other during the run. The tunnel logs what it did;
# the DAQ logs what it measured; you join them on timestamp.
#
# Least coupling and least to go wrong operationally — but it depends entirely
# on both clocks being right, and a clock that is wrong by ten seconds produces
# a dataset that looks fine and is not. Run NTP on both, and verify it, before
# choosing this.

def pattern_c_align(tunnel_csv, daq_csv, tunnel_t0_unix, daq_t0_unix):
    """
    Join a tunnel log to a DAQ log on wall-clock time.

    Both files use seconds-from-start, so you need each file's start time as a
    unix timestamp. The tunnel's is in its metadata sidecar (`recorded`).
    """
    import csv

    import numpy as np

    def load(path, tcol, vcols):
        rows = list(csv.DictReader(open(path)))
        t = np.array([float(r[tcol]) for r in rows])
        return t, {c: np.array([float(r[c]) if r[c] else np.nan
                                for r in rows]) for c in vcols}

    tt, tv = load(tunnel_csv, "t_s", ["cmd_hz", "meas_hz"])
    dt, dv = load(daq_csv, "t_s", [c for c in
                                   csv.DictReader(open(daq_csv)).fieldnames
                                   if c != "t_s"])

    # Onto a common absolute timeline, then resample the DAQ onto the tunnel's
    # samples — the tunnel's rate is the slower of the two and interpolating
    # down loses less than interpolating up invents.
    tt_abs = tt + tunnel_t0_unix
    dt_abs = dt + daq_t0_unix

    overlap = (tt_abs >= dt_abs[0]) & (tt_abs <= dt_abs[-1])
    if not overlap.any():
        raise ValueError(
            "no time overlap between the two files — check that both t0 values "
            "are unix timestamps and that the clocks agree")
    print(f"  overlap: {overlap.sum()} of {len(tt)} tunnel samples")

    out = {"t_s": tt[overlap]}
    out.update({k: v[overlap] for k, v in tv.items()})
    for name, series in dv.items():
        out[f"daq_{name}"] = np.interp(tt_abs[overlap], dt_abs, series)
    return out


# ══════════════════════════════════════════════════════════════════════════

EXPLAIN = """
  A · one process, sample-synchronous
      The DAQ is a velocity source; the player logs it in the same row as the
      command. Nothing to align — the rows are the alignment.
      Needs: both labs on one machine, sharing this codebase.

  B · network service                                        [recommended]
      Pi runs the dashboard. The DAQ machine drives it over HTTP and acquires
      on its own clock. Jeong's side never installs pymodbus, never learns
      what a control word is, and cannot leave the fan running.
      Needs: a network route and NTP on both machines.

  C · independent, aligned afterwards
      Neither side talks to the other. Join on timestamp after the fact.
      Least coupling — and entirely dependent on both clocks being right.
      A clock wrong by ten seconds gives you a dataset that looks fine.

  Whichever you pick, record the tunnel state at the START and END of every
  acquisition window. That is what lets the two records be aligned later
  without anyone trusting a stopwatch.
"""

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="DAQ integration patterns")
    p.add_argument("--explain", action="store_true")
    a = p.parse_args()
    print(__doc__ if not a.explain else EXPLAIN)
    if not a.explain:
        print("Run with --explain for a summary, or import the pattern you want.")
