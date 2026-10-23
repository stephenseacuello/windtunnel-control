#!/usr/bin/env python3
"""
section_balance_logger.py — record the blade-section force balance.

    python scripts/section_balance_logger.py --set Plain --session a090
    python scripts/section_balance_logger.py --simulate               no hardware
    python scripts/section_balance_logger.py --simulate --script runs.txt

The board runs firmware/section_balance/section_balance.ino: two HX711 load
cells (drag and lift) and the on-board accelerometer. This script records
dwells into one folder per session under logs/section_balance/:

    zero      wind OFF, slice mounted          the zero every wind dwell is taken against
    wind      wind ON at the current labels    the measurement
    support   wind ON, support only            the support's own force, subtracted later
    cal       a known mass on one axis         the calibration matrix, cross-talk included
    burst     accelerometer capture            vortex shedding (St about 0.22)

scripts/section_balance_analyze.py turns a session into Cd and Cl.

═══════════════════════════════════════════════════════════════════════════
IT DOES NOT TOUCH THE TUNNEL
═══════════════════════════════════════════════════════════════════════════
No fan command, no drive, no load. The operator sets the fan over the PMC
with `src/run.py jog` or the dashboard, under the usual rules (FIELD_CARD.md),
and tells this script what was set: `rpm 1100` labels the next dwells with
that set point and the wind speed the fan calibration gives. (Not
scripts/rpm.py: it needs the FTDI link, which is not landed while the PMC is,
and it stops at 1700 rpm.)
If the rotor is still in the test section, the turbine interlock applies
exactly as for a blade sweep; this script neither knows nor checks.

It never opens the drive's port. Autodetection excludes `transport.port` and
the tunnel node's port from data/tunnel.json, refuses rather than guesses
when that leaves more than one candidate, and listens before it writes: a
port streaming PMC telemetry or Modbus binary is closed untouched. Same rule,
same reasons, as src/tunnel_node.py.

═══════════════════════════════════════════════════════════════════════════
WHAT THE NUMBERS ARE
═══════════════════════════════════════════════════════════════════════════
**Raw counts are the record.** The firmware's live N columns use whatever K
it was last sent; they are for the operator. The analysis refits K from the
calibration dwells and takes zeros from wind-off dwells.

**Dwell time is the board's clock.** A 30 s dwell is 30 s of board micros(),
not of host scheduling. Every row also carries the host's wall clock, so the
record can be joined to a dashboard or sweep log.

**U_nom is the fan calibration**, v = 0.02132 x RPM - 0.424 (Test 1,
13 Feb 2026), measured to 700 rpm only and extrapolated above. It is a label,
not a measurement; a pitot reading, when there is one, goes in with `umeas`.

**Air temperature comes from a thermometer** (`air <degC>`). The board's
LPS22HB pressure is used; its temperature is the board's own and reads high
by about 20 C (seen on the tunnel node), which is 6.5 % of every Cd.

**K is kept on the host**, in data/section_balance.json, and re-sent on every
connect: the firmware holds it in RAM only (its header says why).
"""

from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "logs" / "section_balance"
DEFAULT_BALANCE_CFG = ROOT / "data" / "section_balance.json"
TUNNEL_CFG = ROOT / "data" / "tunnel.json"

LOGGER_VERSION = "1.0"
FW_NAME = "section-balance"
BAUD = 115200
G_STD = 9.80665                       # m/s^2; the firmware uses the same value

# The firmware's row format. tests/test_section_balance.py checks this string
# against the .ino, so a column change on one side cannot go unnoticed.
ROW_FIELDS = ("t_us", "seq", "alpha_deg", "drag_counts", "lift_counts",
              "drag_n", "lift_n", "flags")
HEADER_LINE = "H," + ",".join(ROW_FIELDS)
FLAG_DRAG_FRESH, FLAG_LIFT_FRESH, FLAG_DRAG_SAT, FLAG_LIFT_SAT = 1, 2, 4, 8

TRACE_COLUMNS = ("dwell", "t_s", "host_unix", "board_us", "seq", "alpha_deg",
                 "drag_counts", "lift_counts", "drag_n_live", "lift_n_live",
                 "flags")
RUNSHEET_COLUMNS = ("dwell", "kind", "set", "mount", "alpha_deg", "fan_rpm",
                    "U_nom_ms", "U_meas_ms", "t_start_s", "t_end_s", "duration_s",
                    "host_start", "n_rows", "n_stale", "n_sat", "axis",
                    "mass_g", "direction", "air_temp_ref_c", "pressure_ref_pa",
                    "board_temp_c", "board_pressure_pa", "rate_hz",
                    "burst_file", "notes", "use")
BURST_HEADER = "us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps"

# Fan calibration fallback: the README's formula. data/tunnel.json wins.
FAN_CAL_FALLBACK = (0.02132, -0.424)


class BalanceError(RuntimeError):
    pass


# ── small helpers ─────────────────────────────────────────────────────────

def _load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def fan_calibration():
    """(slope, intercept, source) for U = slope * rpm + intercept."""
    cal = (_load_json(TUNNEL_CFG).get("calibration") or {})
    c = cal.get("coeffs")
    if cal.get("domain") == "rpm" and c and len(c) == 2:
        return float(c[0]), float(c[1]), "data/tunnel.json calibration (Test 1, 13 Feb 2026)"
    return (*FAN_CAL_FALLBACK, "README formula (data/tunnel.json not readable)")


def wind_from_rpm(rpm, cal=None):
    """Nominal wind speed from a fan set point. 0 rpm is 0 m/s, not -0.42."""
    if rpm is None or rpm <= 0:
        return 0.0
    a, b, _ = cal or fan_calibration()
    return max(0.0, a * float(rpm) + b)


def parse_row(line):
    """One `F,` row from the firmware as a dict, or None if it is not one."""
    if not line.startswith("F,"):
        return None
    p = line.strip().split(",")
    if len(p) != len(ROW_FIELDS) + 1:
        return None
    try:
        return {"t_us": int(p[1]), "seq": int(p[2]), "alpha_deg": float(p[3]),
                "drag_counts": int(p[4]), "lift_counts": int(p[5]),
                "drag_n": float(p[6]), "lift_n": float(p[7]),
                "flags": int(p[8])}
    except ValueError:
        return None


def read_meta_csv(path):
    """(meta dict from leading '# key,value' lines, list of row dicts)."""
    meta, body = {}, []
    with open(path, newline="") as f:
        for line in f:
            if line.startswith("#"):
                parts = next(csv.reader([line[1:].strip()]), [])
                if parts:
                    meta[parts[0].strip()] = parts[1] if len(parts) > 1 else ""
            else:
                body.append(line)
    return meta, list(csv.DictReader(body))


def _write_meta(w, meta):
    for k, v in meta.items():
        w.writerow([f"# {k}", v])


def fit_k(points):
    """
    Least-squares calibration: counts = a + d*t + K F, per channel.

    `points` is a list of dicts with F_drag, F_lift (N), t_s, drag_counts,
    lift_counts (dwell means) and optionally `group` (the session). Each group
    gets its own offset a, because session clocks and zeros are unrelated.
    A group's drift term d is fitted only when it has at least two zero-load
    points far enough apart in time to see it; otherwise it is not
    identifiable and is left out rather than guessed.

    Returns a dict with K (counts per N, row = channel, column = force), the
    covariance of each row's (k_drag, k_lift), residuals in counts and in N,
    and whether drift was fitted. Raises BalanceError when an axis was never
    loaded, because then its column of K does not exist.
    """
    import numpy as np
    F = np.array([[p["F_drag"], p["F_lift"]] for p in points], float)
    t = np.array([p.get("t_s", 0.0) for p in points], float)
    R = np.array([[p["drag_counts"], p["lift_counts"]] for p in points], float)
    grp = [str(p.get("group", "")) for p in points]
    if len(points) < 3:
        raise BalanceError(f"calibration needs at least 3 dwells, has {len(points)}")
    for k, ax in enumerate(("drag", "lift")):
        if not np.any(np.abs(F[:, k]) > 0):
            raise BalanceError(f"no calibration load on the {ax} axis — its "
                               f"column of K cannot be fitted")
    cols, use_drift = [], False
    unloaded = np.all(np.abs(F) < 1e-12, axis=1)
    for gname in sorted(set(grp)):
        m = np.array([g == gname for g in grp])
        cols.append(m.astype(float))
        zt = t[m & unloaded]
        if len(zt) >= 2 and (zt.max() - zt.min()) > 1.0:
            cols.append(np.where(m, t - t[m].mean(), 0.0))
            use_drift = True
    X = np.column_stack(cols + [F[:, 0], F[:, 1]])
    p = X.shape[1]
    if len(points) <= p:
        raise BalanceError(f"calibration has {len(points)} dwells for {p} "
                           f"unknowns per channel — add loads")
    XtX_inv = np.linalg.inv(X.T @ X)
    K = np.zeros((2, 2))
    cov = []
    resid = np.zeros_like(R)
    s_res = []
    for ch in range(2):
        beta, *_ = np.linalg.lstsq(X, R[:, ch], rcond=None)
        r = R[:, ch] - X @ beta
        dof = len(points) - p
        s2 = float(r @ r) / dof
        c = s2 * XtX_inv
        K[ch] = beta[-2:]
        cov.append(c[-2:, -2:].tolist())
        resid[:, ch] = r
        s_res.append(math.sqrt(s2))
    # residuals in newtons: what a fitted K would call these loads
    resid_n = np.linalg.solve(K, resid.T).T
    span = float(np.max(np.abs(F))) or 1.0
    return {
        "K": K.tolist(), "cov_rows": cov, "drift_fitted": bool(use_drift),
        "n_points": len(points), "resid_counts_sd": s_res,
        "resid_n_max": float(np.max(np.abs(resid_n))),
        "resid_frac_of_span": float(np.max(np.abs(resid_n))) / span,
        "max_load_n": span,
        "crosstalk": {"lift_counts_per_drag_counts": float(K[1, 0] / K[0, 0]),
                      "drag_counts_per_lift_counts": float(K[0, 1] / K[1, 1])},
    }


# ── port selection: never the drive's ─────────────────────────────────────

def _usb_ports():
    return sorted(set(glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/ttyACM*")))


def resolve_port(explicit=None, balance_cfg=None, tunnel_cfg=None, ports=None):
    """
    Find the balance without touching the drive or the tunnel node.

    Order: explicit flag, then `port` in data/section_balance.json if it
    exists, then the one remaining USB serial port once the drive's port and
    the tunnel node's are excluded. Refuses when that is ambiguous.
    """
    if explicit:
        return explicit
    bal = balance_cfg if balance_cfg is not None else _load_json(DEFAULT_BALANCE_CFG)
    p = bal.get("port")
    found = list(ports) if ports is not None else _usb_ports()
    if p and p in found:
        return p
    cfg = tunnel_cfg if tunnel_cfg is not None else _load_json(TUNNEL_CFG)
    drive = (cfg.get("transport") or {}).get("port")
    node = (cfg.get("tunnel_node") or {}).get("port")
    found = [q for q in found if q != drive]
    others = [q for q in found if q != node]
    if len(others) == 1:
        return others[0]
    if not others and node in found:
        raise BalanceError(
            f"the only candidate is {node}, which data/tunnel.json records as "
            f"the TUNNEL NODE.\n  If section_balance was flashed onto that "
            f"board, pass --port {node}.\n  Not opened: the dashboard may "
            f"hold it.")
    if not others:
        raise BalanceError(
            "no candidate port for the section balance.\n"
            f"  The drive is on {drive or 'an unknown port'} and is excluded.\n"
            "  Plug the Nano in, or record its port as `port` in "
            "data/section_balance.json.")
    raise BalanceError(
        f"several candidate ports: {', '.join(others)}\n  Pass --port. "
        f"Guessing risks opening the drive link, and on macOS a /dev/cu.* "
        f"device can be opened by two processes at once.")


# ── the board ─────────────────────────────────────────────────────────────

class Balance:
    """
    The firmware's protocol: one line in, one OK/ERR line out, '#' comments,
    `F,` rows while streaming. `link` is a pyserial Serial or a
    SimulatedBalance; both offer write(), readline() and reset_input_buffer().
    """

    def __init__(self, link, port="?", out=print):
        self.link = link
        self.port = port
        self.out = out
        self.identity = None
        self.streaming = False
        self.diagnostics = []
        self._last_us = None
        self._last_host = None
        self._last_seq = None
        self.t_s = 0.0                   # session time on the board's clock
        self.reboots = 0

    @classmethod
    def open_serial(cls, port, settle=2.5, out=print):
        import serial
        ser = serial.Serial(port, BAUD, timeout=0.2)
        time.sleep(settle)               # the board may reboot when the port opens
        # LISTEN BEFORE SPEAKING (src/tunnel_node.py has the history). The
        # PMC streams `T,` telemetry and Modbus binary; this board streams
        # nothing unprompted but its own '#' banner or `F,` rows.
        sniff = b""
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1.2:
            chunk = ser.read(ser.in_waiting or 1)
            if chunk:
                sniff += chunk
            if len(sniff) > 512:
                break
        if b"T," in sniff or b"acs550" in sniff.lower() or any(b > 127 for b in sniff):
            ser.close()
            raise BalanceError(
                f"{port} is streaming PMC telemetry: it is the DRIVE link. "
                f"Nothing was written to it.\n  Fix the port and try again.")
        b = cls(ser, port, out)
        if b"F," in sniff:               # left streaming by a session that died
            b.command("STOP")
        ser.reset_input_buffer()
        return b

    def host_time(self):
        clock = getattr(self.link, "clock", None)
        return clock() if callable(clock) else time.time()

    def close(self):
        try:
            if self.streaming:
                self.stop()
        except Exception:
            pass
        try:
            self.link.close()
        except Exception:
            pass

    # protocol ---------------------------------------------------------------
    def _readline(self):
        raw = self.link.readline()
        if not raw:
            return None
        return raw.decode(errors="ignore").strip() if isinstance(raw, bytes) else raw.strip()

    def command(self, line, timeout=5.0):
        """Send one line, return the first OK/ERR reply. Rows in between are dropped."""
        if not self.streaming:
            self.link.reset_input_buffer()
        self.link.write((line + "\n").encode())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            s = self._readline()
            if s is None:
                continue
            if s.startswith("OK") or s.startswith("ERR"):
                return s
            if s.startswith("#"):
                self.diagnostics.append(s)
        raise BalanceError(f"no reply to {line!r} within {timeout:.0f} s")

    def checked(self, line, timeout=5.0):
        r = self.command(line, timeout)
        if not r.startswith("OK"):
            raise BalanceError(f"{line!r} -> {r}")
        return r

    def identify(self):
        self.identity = self.checked("ID")
        if FW_NAME not in self.identity:
            raise BalanceError(
                f"{self.port} answered {self.identity!r}: not the section "
                f"balance. If it says 'tunnel-node' or 'acs550-pmc', that "
                f"board is not this one.")
        return self.identity

    def set_scale(self, K):
        r = self.checked("SCALE " + " ".join(f"{float(v):.4f}" for row in K for v in row))
        return r

    def alpha(self, deg):
        return self.checked(f"ALPHA {float(deg):.2f}")

    def ambient(self):
        """(board_temp_c, pressure_pa) or (None, None) without a barometer."""
        try:
            r = self.command("AMB?")
        except BalanceError:
            return None, None
        if not r.startswith("OK AMB"):
            return None, None
        f = r.split()
        return float(f[2]), float(f[3])

    def rate(self):
        r = self.command("RATE?")
        f = r.split()
        return {f[i]: f[i + 1] for i in range(2, len(f) - 1, 2)} if r.startswith("OK") else {}

    def start(self):
        r = self.checked("START")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            s = self._readline()
            if s is None:
                continue
            if s.startswith("H,"):
                if s != HEADER_LINE:
                    self.link.write(b"STOP\n")
                    raise BalanceError(
                        f"the firmware's row format differs from this "
                        f"logger's:\n  board  {s}\n  logger {HEADER_LINE}\n"
                        f"  Flash firmware/section_balance/ from this repo.")
                self.streaming = True
                return r
            if s.startswith("#"):
                self.diagnostics.append(s)
        raise BalanceError("START gave no header line")

    def stop(self):
        self.link.write(b"STOP\n")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            s = self._readline()
            if s and s.startswith("OK STOP"):
                self.streaming = False
                return s
        self.streaming = False
        raise BalanceError("no reply to STOP")

    def _clock(self, row):
        """Unwrapped board time in seconds since the session began."""
        host = self.host_time()
        if self._last_us is None:
            self._last_us, self._last_host, self._last_seq = row["t_us"], host, row["seq"]
            return self.t_s
        if row["seq"] <= self._last_seq:
            # The counter went backwards: the board restarted. Its clock did
            # too, so bridge the gap with the host's clock and say so.
            self.reboots += 1
            self.t_s += max(0.0, host - self._last_host)
            self.out("  ⚠ the board restarted (seq went back). Re-send SCALE "
                     "and ALPHA, and take a new zero before trusting what follows.")
        else:
            d = (row["t_us"] - self._last_us) & 0xFFFFFFFF
            # A gap longer than the 71.6 min micros() period is counted from
            # the host clock to the nearest whole wrap.
            k = max(0, round(((host - self._last_host) * 1e6 - d) / 2 ** 32))
            self.t_s += (d + k * 2 ** 32) / 1e6
        self._last_us, self._last_host, self._last_seq = row["t_us"], host, row["seq"]
        return self.t_s

    def rows(self):
        """Yield (row, t_s, host_unix) while streaming. Times out after 3 s of silence."""
        last = time.monotonic()
        while self.streaming:
            s = self._readline()
            if s is None:
                if time.monotonic() - last > 3.0:
                    raise BalanceError("no rows for 3 s: is a load cell connected?")
                continue
            if s.startswith("#"):
                self.diagnostics.append(s)
                continue
            row = parse_row(s)
            if row is None:
                continue
            last = time.monotonic()
            yield row, self._clock(row), self.host_time()

    def burst(self, n, timeout=60.0):
        """(rate_hz, rows) from BURST n; rows are (us, ax, ay, az) in g."""
        self.link.reset_input_buffer()
        self.link.write(f"BURST {int(n)}\n".encode())
        deadline = time.monotonic() + timeout
        hz, rows, in_csv = None, [], False
        while time.monotonic() < deadline:
            s = self._readline()
            if not s:
                continue
            if s.startswith("ERR"):
                raise BalanceError(s)
            if s.startswith("OK BURST"):
                hz = float(s.split()[-1])
            elif s.startswith("us,"):
                in_csv = True
            elif s.startswith("END BURST"):
                return hz, rows
            elif in_csv:
                try:
                    p = s.split(",")
                    rows.append((int(p[0]), float(p[1]), float(p[2]), float(p[3])))
                except (ValueError, IndexError):
                    continue
        raise BalanceError(f"burst did not finish within {timeout:.0f} s")


# ── a board that is not there ─────────────────────────────────────────────

SIM_DEFAULTS = {
    "_what": "Known forces for rehearsal and tests. Coefficients use the CFD "
             "convention (cfd/section2d/README.md section 1).",
    "coefficients": {             # set -> alpha -> [Cd, Cl]
        "Plain":  {"0": [3.20, -0.60], "90": [0.38, 1.00], "180": [1.60, -1.10]},
        "FS0.20": {"0": [3.10, -0.55], "90": [0.46, 0.95], "180": [1.75, -1.20]},
    },
    "default_coefficients": [1.5, 0.0],
    "span_m": 0.100, "c_ref_m": 0.048,
    "air_temp_c": 18.0, "pressure_pa": 101000.0, "board_temp_c": 41.5,
    "lift_sign": -1,              # balance +lift axis = -CFD liftDir
    "section_area_m2": 0.30, "maskell_theta": 2.5,
    "support_drag_area_m2": 0.0018, "support_lift_area_m2": 0.0001,
    "K": [[2.2e5, 0.05e5], [-0.07e5, 1.9e5]],
    "r0": [150000.0, -90000.0],
    "zero_alpha_amp_counts": [2000.0, 1200.0],
    "drift_counts_per_s": [3.0, -2.0],
    "noise_counts": [60.0, 60.0],
    "turbulence_frac": 0.03, "turbulence_tau_s": 0.3,
    "rate_hz": 10.0, "stale_frac": 0.01,
    "gap_s": 20.0,
    "u_true_over_nominal": 1.0,
    "shedding_st": {"180": 0.2232}, "shedding_amp_g": 0.02,
    "imu_hz": 952.0,
}


class SimulatedBalance:
    """
    The firmware's protocol over a fake port, producing counts from known
    forces: calibration matrix with cross-talk, drifting zeros that move with
    alpha, support drag, Maskell-type blockage, turbulence and noise. Used by
    `--simulate` to rehearse a session and by the tests to check that the
    analysis recovers what went in.

    Board time is virtual: rows are generated as fast as they are read, so a
    30 s dwell takes milliseconds. `realtime=True` paces them to the wall
    clock for a rehearsal that feels like the rig.
    """

    def __init__(self, truth=None, seed=1, realtime=False, start_unix=None):
        import numpy as np
        self.np = np
        self.T = json.loads(json.dumps(SIM_DEFAULTS))
        for k, v in (truth or {}).items():
            self.T[k] = v
        self.rng = np.random.default_rng(seed)
        self.realtime = realtime
        self.t0_wall = time.time()
        self.start_unix = start_unix if start_unix is not None else time.time()
        self.board_s = 5.0                       # seconds since boot
        self.out = collections.deque()
        self.streaming = False
        self.seq = 0
        self.alpha = 0.0
        self.K_live = [[0.0, 0.0], [0.0, 0.0]]
        self.tare = [0.0, 0.0]
        self.have_tare = False
        self.turb = 0.0
        self.cond = {"kind": "zero", "set": "Plain", "U": 0.0,
                     "F_cal": (0.0, 0.0)}
        self.out.append(b"# section-balance 1.0 (SIMULATED)  drag ok  lift ok  imu LSM9DS1\n")

    # what the operator did --------------------------------------------------
    def set_conditions(self, kind, set_name, U_nom, alpha, F_cal=(0.0, 0.0)):
        """Called by the logger before each dwell; the real board has no such call."""
        if not self.realtime:
            # Fast mode has no idle time, so the operator's minutes between
            # dwells (and the zero drift over them) are added here.
            self.board_s += float(self.T["gap_s"])
        self.cond = {"kind": kind, "set": set_name,
                     "U": float(U_nom) * float(self.T["u_true_over_nominal"]),
                     "F_cal": tuple(F_cal)}
        self.alpha = float(alpha)

    def clock(self):
        return self.start_unix + self.board_s

    # physics ---------------------------------------------------------------
    def rho(self):
        return float(self.T["pressure_pa"]) / (287.05 * (float(self.T["air_temp_c"]) + 273.15))

    def coeffs(self, set_name, alpha):
        tab = (self.T["coefficients"].get(set_name) or {})
        for a, v in tab.items():
            if abs(((float(a) - alpha + 180.0) % 360.0) - 180.0) < 0.5:
                return float(v[0]), float(v[1])
        return tuple(float(x) for x in self.T["default_coefficients"])

    def true_forces(self):
        """(F_drag, F_lift) on the balance axes, N, before turbulence."""
        c = self.cond
        if c["kind"] == "cal":
            return c["F_cal"]
        if c["kind"] not in ("wind", "support") or c["U"] <= 0:
            return (0.0, 0.0)
        q = 0.5 * self.rho() * c["U"] ** 2
        Ds = q * float(self.T["support_drag_area_m2"])
        Ls = q * float(self.T["support_lift_area_m2"])
        if c["kind"] == "support":
            Dm = Lm = 0.0
        else:
            cd, cl = self.coeffs(c["set"], self.alpha)
            S = float(self.T["span_m"]) * float(self.T["c_ref_m"])
            Dm, Lm = q * S * cd, q * S * cl * float(self.T["lift_sign"])
        area = self.T.get("section_area_m2")
        f = 1.0
        if area:
            # Maskell's q_c/q = 1 + theta (D_measured/q)/C, solved for the
            # measured force given the true one: D_meas = D / (1 - theta D/(q C)).
            f = 1.0 / (1.0 - float(self.T["maskell_theta"]) * (Dm + Ds) / q / float(area))
        return (Dm + Ds) * f, (Lm + Ls) * f

    def counts(self):
        np, T = self.np, self.T
        F = np.array(self.true_forces(), float)
        if self.cond["kind"] in ("wind", "support") and self.cond["U"] > 0:
            dt = 1.0 / float(T["rate_hz"])
            a = math.exp(-dt / float(T["turbulence_tau_s"]))
            self.turb = a * self.turb + math.sqrt(1 - a * a) * self.rng.normal()
            F = F * (1.0 + float(T["turbulence_frac"]) * self.turb)
        K = np.array(T["K"], float)
        al = math.radians(self.alpha)
        amp = np.array(T["zero_alpha_amp_counts"], float)
        r0 = (np.array(T["r0"], float) + amp * np.array([math.cos(al), math.sin(al)])
              + np.array(T["drift_counts_per_s"], float) * self.board_s)
        r = r0 + K @ F + self.rng.normal(0.0, 1.0, 2) * np.array(T["noise_counts"], float)
        return [int(max(-8388608, min(8388607, round(v)))) for v in r]

    def _live(self, r):
        K = self.K_live
        det = K[0][0] * K[1][1] - K[0][1] * K[1][0]
        if not det:
            return float("nan"), float("nan")
        dd, dl = r[0] - self.tare[0], r[1] - self.tare[1]
        return ((K[1][1] * dd - K[0][1] * dl) / det, (-K[1][0] * dd + K[0][0] * dl) / det)

    def _step(self):
        self.board_s += 1.0 / float(self.T["rate_hz"])
        if self.realtime:
            # Like a real board: its clock ran on while the operator typed.
            wall = 5.0 + (time.time() - self.t0_wall)
            if wall > self.board_s + 0.5:
                self.board_s = wall
            elif self.board_s > wall:
                time.sleep(self.board_s - wall)
        return self.counts()

    def _row(self):
        r = self._step()
        self.seq += 1
        flags = FLAG_DRAG_FRESH | FLAG_LIFT_FRESH
        if self.rng.random() < float(self.T["stale_frac"]):
            flags = self.rng.choice([FLAG_DRAG_FRESH, FLAG_LIFT_FRESH])
        fd, fl = self._live(r)
        t_us = int(self.board_s * 1e6) & 0xFFFFFFFF
        return (f"F,{t_us},{self.seq},{self.alpha:.2f},{r[0]},{r[1]},"
                f"{fd:.5f},{fl:.5f},{flags}\n").encode()

    def _mean(self, n):
        np = self.np
        rs = np.array([self._step() for _ in range(n)], float)
        return rs.mean(axis=0), rs.std(axis=0, ddof=1) if n > 1 else np.zeros(2)

    # the port ----------------------------------------------------------------
    @property
    def in_waiting(self):
        return len(self.out)

    def reset_input_buffer(self):
        self.out.clear()

    def close(self):
        pass

    def readline(self):
        if self.out:
            return self.out.popleft()
        if self.streaming:
            return self._row()
        return b""

    def write(self, data):
        for line in data.decode().splitlines():
            if line.strip():
                self._handle(line.strip())

    def _reply(self, s):
        self.out.append((s + "\n").encode())

    def _handle(self, line):
        p = line.split()
        verb = p[0].upper()
        if verb == "ID":
            self._reply("OK ID section-balance 1.0 drag=ok lift=ok imu=LSM9DS1 "
                        "baro=LPS22HB sim=1")
        elif verb == "START":
            self.streaming = True
            self._reply("OK START")
            self._reply(HEADER_LINE)
        elif verb == "STOP":
            self.streaming = False
            self._reply(f"OK STOP rows {self.seq}")
        elif verb == "RAW?":
            r = self._step()
            self._reply(f"OK RAW {r[0]} {r[1]}")
        elif verb == "TARE":
            n = int(p[1]) if len(p) > 1 else 20
            m, sd = self._mean(n)
            self.tare, self.have_tare = [float(m[0]), float(m[1])], True
            self._reply(f"OK TARE {m[0]:.1f} {m[1]:.1f} sd {sd[0]:.1f} {sd[1]:.1f} n {n} {n}")
        elif verb == "CAL":
            if len(p) < 3 or p[1].upper() not in ("D", "L"):
                return self._reply("ERR CAL needs D|L <grams> [n]")
            if not self.have_tare:
                return self._reply("ERR TARE first, wind off and no load")
            n = int(p[3]) if len(p) > 3 else 20
            m, _ = self._mean(n)
            F = float(p[2]) / 1000.0 * G_STD
            col = 0 if p[1].upper() == "D" else 1
            self.K_live[0][col] = (m[0] - self.tare[0]) / F
            self.K_live[1][col] = (m[1] - self.tare[1]) / F
            self._reply(f"OK CAL {p[1].upper()} k {self.K_live[col][col]:.3f} "
                        f"{self.K_live[1 - col][col]:.3f} F_N {F:.5f} n {n}")
        elif verb == "SCALE?":
            K = self.K_live
            self._reply(f"OK SCALE {K[0][0]:.3f} {K[0][1]:.3f} {K[1][0]:.3f} "
                        f"{K[1][1]:.3f} tare {self.tare[0]:.1f} {self.tare[1]:.1f}")
        elif verb == "SCALE":
            if len(p) < 5:
                return self._reply("ERR SCALE needs k_dd k_dl k_ld k_ll (counts per N)")
            v = [float(x) for x in p[1:5]]
            if abs(v[0] * v[3] - v[1] * v[2]) < 1e-6 * (abs(v[0] * v[3]) + abs(v[1] * v[2]) + 1e-30):
                return self._reply("ERR SCALE matrix is singular - kept the previous one")
            self.K_live = [[v[0], v[1]], [v[2], v[3]]]
            self._handle("SCALE?")
        elif verb in ("ALPHA", "ALPHA?"):
            if verb == "ALPHA" and len(p) > 1:
                self.alpha = float(p[1])
            self._reply(f"OK ALPHA {self.alpha:.2f}")
        elif verb == "MARK":
            self._reply(f"OK MARK {' '.join(p[1:]) or '-'} {int(self.board_s * 1e6) & 0xFFFFFFFF}")
        elif verb == "RATE?":
            hz = float(self.T["rate_hz"])
            self._reply(f"OK RATE rows_hz {hz:.2f} drag_hz {hz:.2f} lift_hz {hz:.2f} "
                        f"imu_hz {float(self.T['imu_hz']):.0f}")
        elif verb == "AMB?":
            self._reply(f"OK AMB {float(self.T['board_temp_c']):.2f} "
                        f"{float(self.T['pressure_pa']):.0f}")
        elif verb == "BURST":
            self._burst(int(p[1]) if len(p) > 1 else 2000)
        elif verb in ("HELP", "?"):
            self._reply("OK HELP ID START STOP RAW? TARE[n] CAL<D|L><g>[n] SCALE? "
                        "SCALE<kdd kdl kld kll> ALPHA<deg> ALPHA? MARK<label> RATE? "
                        "AMB? BURST<n>")
        else:
            self._reply(f"ERR unknown command {verb}")

    def _burst(self, n):
        np, T = self.np, self.T
        n = max(1, min(int(n), 4000))
        fs = float(T["imu_hz"])
        t = self.board_s + np.arange(n) / fs + self.rng.normal(0, 30e-6, n)
        t.sort()
        sig = self.rng.normal(0.0, 0.004, (n, 3))
        sig[:, 2] += 1.0                                   # gravity
        c = self.cond
        st = None
        for a, v in (T.get("shedding_st") or {}).items():
            if abs(((float(a) - self.alpha + 180.0) % 360.0) - 180.0) < 0.5:
                st = float(v)
        if c["kind"] == "wind" and c["U"] > 0 and st:
            f = st * c["U"] / float(T["c_ref_m"])
            sig[:, 1] += float(T["shedding_amp_g"]) * np.sin(2 * np.pi * f * t)
        self.board_s = float(t[-1]) + 1.0 / fs
        hz = (n - 1) / (t[-1] - t[0]) if n > 1 else 0.0
        self._reply(f"OK BURST {n} rate_hz {hz:.1f}")
        self._reply(BURST_HEADER)
        for i in range(n):
            us = int(t[i] * 1e6) & 0xFFFFFFFF
            self._reply(f"{us},{sig[i, 0]:.4f},{sig[i, 1]:.4f},{sig[i, 2]:.4f},0,0,0")
        self._reply("END BURST")


# ── a session on disk ─────────────────────────────────────────────────────

class Session:
    """
    One folder: trace.csv (every row of every dwell), runsheet.csv (one row
    per dwell), session.json, bursts/. Files are flushed after every dwell so
    an aborted session keeps everything up to the abort.
    """

    def __init__(self, balance, folder, *, set_name="Plain", notes="",
                 balance_cfg_path=DEFAULT_BALANCE_CFG, save_cal=True,
                 dwell_s=30.0, zero_s=20.0, cal_s=10.0, out=print):
        self.b = balance
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=False)
        (self.folder / "bursts").mkdir()
        self.out = out
        self.cfg_path = Path(balance_cfg_path)
        self.save_cal = save_cal
        self.fan_cal = fan_calibration()
        self.labels = {"set": set_name, "mount": 1, "alpha_deg": 0.0,
                       "fan_rpm": None, "U_nom_ms": 0.0, "U_meas_ms": None,
                       "air_temp_ref_c": None, "pressure_ref_pa": None}
        self.pending_note = ""
        self.defaults = {"wind": dwell_s, "support": dwell_s, "zero": zero_s, "cal": cal_s}
        self.dwell_id = 0
        self.cal_hardware_in = False
        self.zero_seen = set()          # (set, mount, alpha) with a zero recorded
        self.open_block = None          # (set, mount, alpha) with wind after its last zero
        self.cal_points = []
        self.last_zero = {}             # (set, mount, alpha) -> (mean counts, dwell)
        self.cal_zero = None            # last unloaded calibration dwell
        self.K = None

        bal = _load_json(self.cfg_path)
        if bal.get("k_counts_per_n"):
            try:
                self.b.set_scale(bal["k_counts_per_n"])
                self.K = bal["k_counts_per_n"]
                self.out(f"  live scale from {self._rel(self.cfg_path)} "
                         f"({(bal.get('k_record') or {}).get('date', 'undated')})")
            except BalanceError as e:
                self.out(f"  ⚠ the recorded K was not accepted: {e}")
        self.span_m = bal.get("span_m")
        self.c_ref_m = bal.get("c_ref_m", 0.048)
        try:
            self.b.alpha(0.0)
        except BalanceError:
            pass

        self.meta = {
            "session": self.folder.name,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "logger": f"section_balance_logger.py {LOGGER_VERSION}",
            "firmware": balance.identity or "?",
            "port": balance.port,
            "fan_calibration": f"U = {self.fan_cal[0]:.5f} * rpm {self.fan_cal[1]:+.4f} "
                               f"m/s ({self.fan_cal[2]})",
            "live_K_counts_per_n": json.dumps(self.K) if self.K else "not set",
            "notes": notes,
            "_record": "raw counts are the record; drag_n_live/lift_n_live use "
                       "the board's live K and TARE, for the operator only",
            "_clock": "t_s is board time since the session began; host_unix is "
                      "the host wall clock when the row arrived",
            "_alpha": "CFD convention (cfd/section2d/README.md section 1): 0 cup "
                      "into the wind, 90 wind from tip A to tip B, 180 convex "
                      "side into the wind",
        }
        (self.folder / "session.json").write_text(json.dumps(self.meta, indent=1) + "\n")
        self._trace_f = open(self.folder / "trace.csv", "w", newline="")
        self._trace = csv.writer(self._trace_f)
        _write_meta(self._trace, self.meta)
        self._trace.writerow(TRACE_COLUMNS)
        self._run_f = open(self.folder / "runsheet.csv", "w", newline="")
        self._run = csv.writer(self._run_f)
        _write_meta(self._run, {"session": self.folder.name,
                                "_use": "set use to 0 to exclude a dwell; add "
                                        "U_meas_ms, q_pa or rho_kg_m3 columns "
                                        "to override the labels"})
        self._run.writerow(RUNSHEET_COLUMNS)
        self._trace_f.flush()
        self._run_f.flush()

    @staticmethod
    def _rel(p):
        try:
            return str(Path(p).resolve().relative_to(ROOT))
        except ValueError:
            return str(p)

    def close(self):
        for f in (self._trace_f, self._run_f):
            try:
                f.close()
            except Exception:
                pass

    # labels -------------------------------------------------------------------
    def block_key(self):
        L = self.labels
        return (L["set"], L["mount"], round(float(L["alpha_deg"]), 1))

    def remind_closing_zero(self, always=False):
        if self.open_block and (always or self.open_block != self.block_key()):
            s, m, a = self.open_block
            self.out(f"  ⚠ no closing zero for {s} mount {m} alpha {a:g} since "
                     f"its last wind dwell. Stop the fan and take one, or the "
                     f"analysis has only the zero before it.")

    def set_label(self, key, value):
        self.labels[key] = value
        if key == "alpha_deg":
            try:
                self.b.alpha(value)
            except BalanceError as e:
                self.out(f"  ⚠ {e}")
        self.remind_closing_zero()

    def set_wind(self, rpm=None, U=None):
        """A new wind label. Any measured speed belongs to the old one and is dropped."""
        self.labels["U_meas_ms"] = None
        if rpm is not None:
            self.labels["fan_rpm"] = float(rpm)
            self.labels["U_nom_ms"] = wind_from_rpm(rpm, self.fan_cal)
        else:
            self.labels["fan_rpm"] = None
            self.labels["U_nom_ms"] = float(U)
        if self.cal_hardware_in and self.labels["U_nom_ms"] > 0:
            self.out("  ⚠ CALIBRATION HARDWARE may still be in the test section. "
                     "Remove the string, pulley and masses BEFORE the fan "
                     "starts, then type `cleared`.")
        return self.labels["U_nom_ms"]

    # dwells -------------------------------------------------------------------
    def record(self, kind, duration=None, axis=None, mass_g=None, direction=1):
        """Record one dwell. Returns its runsheet row as a dict."""
        if kind not in ("zero", "wind", "support", "cal"):
            raise BalanceError(f"unknown dwell kind {kind!r}")
        L = dict(self.labels)
        duration = float(duration or self.defaults[kind])
        if kind in ("wind", "support"):
            if self.cal_hardware_in:
                raise BalanceError(
                    "calibration hardware may still be in the test section. "
                    "Remove the string, pulley and masses, then type `cleared`. "
                    "(A reminder, not an interlock: the fan is yours to control.)")
            if not L["U_nom_ms"] > 0:
                raise BalanceError("no wind label: `rpm <fan rpm>` or `u <m/s>` first")
            if kind == "wind" and L["set"].lower() == "support":
                raise BalanceError("set is 'support': use `support` for support-only dwells")
            if kind == "support" and L["set"].lower() != "support":
                raise BalanceError("`set support` first, so the zeros taken with "
                                   "the slice removed carry the same label")
            key = (L["set"], L["mount"], round(float(L["alpha_deg"]), 1))
            if key not in self.zero_seen:
                self.out(f"  ⚠ no wind-off zero yet for {key[0]} mount {key[1]} "
                         f"alpha {key[2]:g}. Recording anyway; take one after "
                         f"(fan stopped) so this dwell has a zero.")
        F_cal = (0.0, 0.0)
        if kind == "cal":
            if axis not in ("d", "l"):
                raise BalanceError("cal needs an axis: d (drag) or l (lift)")
            if mass_g is None or mass_g < 0:
                raise BalanceError("cal needs a mass in grams (0 for the unloaded point)")
            F = float(mass_g) / 1000.0 * G_STD * (1 if direction >= 0 else -1)
            F_cal = (F, 0.0) if axis == "d" else (0.0, F)
            if not self.cal_hardware_in:
                self.out("  calibration hardware goes in the test section: take it all out "
                         "before the wind comes on, then type `cleared`")
            self.cal_hardware_in = True
        set_name = L["set"]
        U = L["U_nom_ms"] if kind in ("wind", "support") else 0.0
        fan = L["fan_rpm"] if kind in ("wind", "support") else 0.0
        if hasattr(self.b.link, "set_conditions"):
            self.b.link.set_conditions(kind, set_name, U, L["alpha_deg"], F_cal)

        self.dwell_id += 1
        did = self.dwell_id
        board_t, board_p = self.b.ambient()
        host_start = self.b.host_time()
        n = stale = sat = 0
        t_first = t_last = None
        csum, cnum = [0.0, 0.0], [0, 0]
        key = (set_name, L["mount"], round(float(L["alpha_deg"]), 1))
        zero = self._zero_for(kind, key)
        aborted, why = False, ""
        self.b.start()
        try:
            shown = time.monotonic()
            for row, t_s, host in self.b.rows():
                if t_first is None:
                    t_first = t_s
                if t_s - t_first >= duration:
                    break
                t_last = t_s
                n += 1
                fl = row["flags"]
                if (fl & 3) != 3:
                    stale += 1
                if fl & (FLAG_DRAG_SAT | FLAG_LIFT_SAT):
                    sat += 1
                for k, (bit, col) in enumerate(((FLAG_DRAG_FRESH, "drag_counts"),
                                                (FLAG_LIFT_FRESH, "lift_counts"))):
                    if fl & bit:
                        csum[k] += row[col]
                        cnum[k] += 1
                self._trace.writerow([did, f"{t_s:.6f}", f"{host:.3f}", row["t_us"],
                                      row["seq"], f"{row['alpha_deg']:.2f}",
                                      row["drag_counts"], row["lift_counts"],
                                      row["drag_n"], row["lift_n"], fl])
                if time.monotonic() - shown > 0.5:
                    shown = time.monotonic()
                    self._progress(kind, t_s - t_first, duration, row, zero)
        except KeyboardInterrupt:
            aborted, why = True, "aborted"
            self.out("\n  aborted — rows so far are kept, the dwell is marked use=0")
        except BalanceError as e:
            aborted, why = True, f"aborted: {e}"
            self.out(f"\n  ✗ {e}\n  rows so far are kept, the dwell is marked use=0")
        finally:
            try:
                self.b.stop()
            except BalanceError as e:
                self.out(f"  ⚠ {e}")
            self._trace_f.flush()

        dur = (t_last - t_first) if (t_first is not None and t_last is not None) else 0.0
        rate = (n - 1) / dur if dur > 0 and n > 1 else 0.0
        note = self.pending_note
        self.pending_note = ""
        if aborted:
            note = (note + "; " if note else "") + why
        row = {
            "dwell": did, "kind": kind, "set": set_name, "mount": L["mount"],
            "alpha_deg": f"{float(L['alpha_deg']):.2f}",
            "fan_rpm": "" if fan is None else f"{fan:.0f}",
            "U_nom_ms": f"{U:.3f}",
            "U_meas_ms": "" if kind not in ("wind", "support") or L["U_meas_ms"] is None
            else f"{L['U_meas_ms']:.3f}",
            "t_start_s": "" if t_first is None else f"{t_first:.6f}",
            "t_end_s": "" if t_last is None else f"{t_last:.6f}",
            "duration_s": f"{dur:.3f}", "host_start": f"{host_start:.3f}",
            "n_rows": n, "n_stale": stale, "n_sat": sat,
            "axis": axis or "", "mass_g": "" if mass_g is None else f"{mass_g:g}",
            "direction": "" if kind != "cal" else ("+" if direction >= 0 else "-"),
            "air_temp_ref_c": "" if L["air_temp_ref_c"] is None else f"{L['air_temp_ref_c']:.2f}",
            "pressure_ref_pa": "" if L["pressure_ref_pa"] is None else f"{L['pressure_ref_pa']:.0f}",
            "board_temp_c": "" if board_t is None else f"{board_t:.2f}",
            "board_pressure_pa": "" if board_p is None else f"{board_p:.0f}",
            "rate_hz": f"{rate:.2f}", "burst_file": "", "notes": note,
            "use": 0 if aborted or n == 0 else 1,
        }
        self._run.writerow([row[c] for c in RUNSHEET_COLUMNS])
        self._run_f.flush()

        means = [csum[k] / cnum[k] if cnum[k] else float("nan") for k in range(2)]
        self._summary(row, means, zero)
        if kind == "zero" and not aborted and n:
            self.zero_seen.add(key)
            self.last_zero[key] = (means, did)
            if self.open_block == key:
                self.open_block = None
        elif kind in ("wind", "support") and not aborted:
            self.open_block = key
        if kind == "cal" and not aborted and n:
            self.cal_points.append({
                "F_drag": F_cal[0], "F_lift": F_cal[1], "t_s": (t_first + t_last) / 2,
                "drag_counts": None, "lift_counts": None, "dwell": did})
            if not mass_g:
                self.cal_zero = (means, did)
        if sat:
            self.out(f"  ⚠ {sat} saturated rows: a cell is overloaded or unwired. "
                     f"The analysis drops this dwell.")
        if n and stale > 0.05 * n:
            self.out(f"  ⚠ {stale} of {n} rows had a channel that did not update: "
                     f"check the HX711 wiring.")
        return row

    def _zero_for(self, kind, key):
        """The zero a live force is taken against: last wind-off zero at these labels."""
        return self.cal_zero if kind == "cal" else self.last_zero.get(key)

    def host_forces(self, counts, zero):
        """(D, L) in N on the balance axes, K^-1 (counts - zero); None without K or a zero."""
        if not self.K or zero is None:
            return None
        K, z = self.K, zero[0]
        det = K[0][0] * K[1][1] - K[0][1] * K[1][0]
        if not det or any(math.isnan(v) for v in z):
            return None
        dd, dl = counts[0] - z[0], counts[1] - z[1]
        return ((K[1][1] * dd - K[0][1] * dl) / det, (-K[1][0] * dd + K[0][0] * dl) / det)

    def _readout(self, counts, zero, live_n=None):
        F = self.host_forces(counts, zero)
        if F is not None:
            return f"D {F[0]:+8.4f} N  L {F[1]:+8.4f} N (vs zero #{zero[1]})", F
        if live_n and not math.isnan(live_n[0]):
            return f"D {live_n[0]:+8.4f} N  L {live_n[1]:+8.4f} N (board TARE)", None
        return "no K or no zero yet: counts only", None

    def _rough(self, F):
        """D/(qS) and L/(qS) on the balance axes: no tare, no blockage, rough rho."""
        L = self.labels
        if F is None or not self.span_m or not L["U_nom_ms"] > 0:
            return ""
        T = L["air_temp_ref_c"] if L["air_temp_ref_c"] is not None else 20.0
        p = L["pressure_ref_pa"] or 101325.0
        q = 0.5 * p / (287.05 * (T + 273.15)) * L["U_nom_ms"] ** 2
        S = float(self.span_m) * float(self.c_ref_m)
        return f"   rough D/qS {F[0] / q / S:6.3f}  L/qS {F[1] / q / S:+6.3f}"

    def _progress(self, kind, t, duration, row, zero):
        txt, _ = self._readout((row["drag_counts"], row["lift_counts"]), zero,
                               (row["drag_n"], row["lift_n"]))
        sys.stdout.write(f"\r  {kind:<7} {t:5.1f}/{duration:.0f} s   {txt}   "
                         f"raw {row['drag_counts']:>9} {row['lift_counts']:>9}   ")
        sys.stdout.flush()

    def _summary(self, row, means, zero):
        if sys.stdout.isatty():
            sys.stdout.write("\r" + " " * 110 + "\r")
        what = row["kind"]
        if row["kind"] == "cal":
            what += f" {row['axis']} {row['mass_g']} g {row['direction']}"
        if row["kind"] == "zero" or (row["kind"] == "cal" and zero is None):
            extra = f"   mean counts {means[0]:.0f} {means[1]:.0f}"
        else:
            txt, F = self._readout(means, zero)
            extra = "   " + txt + (self._rough(F) if row["kind"] == "wind" else "")
        self.out(f"  #{row['dwell']:<3} {what:<16} {row['set']:<8} alpha "
                 f"{float(row['alpha_deg']):6.1f}  U {float(row['U_nom_ms']):5.2f}  "
                 f"{row['n_rows']} rows {row['rate_hz']} Hz{extra}")

    def cleared(self):
        self.cal_hardware_in = False
        self.out("  noted: calibration hardware out of the test section")

    def burst(self, n=4000):
        L = self.labels
        if hasattr(self.b.link, "set_conditions"):
            kind = "wind" if L["U_nom_ms"] > 0 else "zero"
            self.b.link.set_conditions(kind, L["set"], L["U_nom_ms"], L["alpha_deg"])
        self.dwell_id += 1
        did = self.dwell_id
        host = self.b.host_time()
        hz, rows = self.b.burst(n)
        name = f"burst_{did:03d}.csv"
        ident = dict(t.split("=", 1) for t in (self.b.identity or "").split() if "=" in t)
        with open(self.folder / "bursts" / name, "w", newline="") as f:
            w = csv.writer(f)
            _write_meta(w, {"session": self.folder.name, "dwell": did,
                            "set": L["set"], "mount": L["mount"],
                            "alpha_deg": f"{float(L['alpha_deg']):.2f}",
                            "U_nom_ms": f"{L['U_nom_ms']:.3f}", "rate_hz": hz,
                            "imu": ident.get("imu", "?"),
                            "_axes": "board axes; gyro columns are zero by design"})
            w.writerow(BURST_HEADER.split(","))
            for r in rows:
                w.writerow([r[0], f"{r[1]:.4f}", f"{r[2]:.4f}", f"{r[3]:.4f}", 0, 0, 0])
        row = {c: "" for c in RUNSHEET_COLUMNS}
        row.update({"dwell": did, "kind": "burst", "set": L["set"], "mount": L["mount"],
                    "alpha_deg": f"{float(L['alpha_deg']):.2f}",
                    "fan_rpm": "" if L["fan_rpm"] is None else f"{L['fan_rpm']:.0f}",
                    "U_nom_ms": f"{L['U_nom_ms']:.3f}", "host_start": f"{host:.3f}",
                    "n_rows": len(rows), "rate_hz": f"{hz or 0:.1f}",
                    "burst_file": f"bursts/{name}", "notes": self.pending_note, "use": 1})
        self.pending_note = ""
        self._run.writerow([row[c] for c in RUNSHEET_COLUMNS])
        self._run_f.flush()
        self.out(f"  #{did:<3} burst  {len(rows)} samples at {hz:.1f} Hz -> bursts/{name}")
        return row

    # calibration ----------------------------------------------------------------
    def fit(self):
        """Fit K from this session's calibration dwells, send it, record it."""
        if not self.cal_points:
            raise BalanceError("no calibration dwells in this session")
        _, rows = read_meta_csv(self.folder / "trace.csv")
        by = collections.defaultdict(list)
        for r in rows:
            by[int(r["dwell"])].append(r)
        pts = []
        for p in self.cal_points:
            rr = [r for r in by.get(p["dwell"], []) if (int(r["flags"]) & 3) == 3]
            if not rr:
                continue
            q = dict(p)
            q["drag_counts"] = sum(float(r["drag_counts"]) for r in rr) / len(rr)
            q["lift_counts"] = sum(float(r["lift_counts"]) for r in rr) / len(rr)
            pts.append(q)
        res = fit_k(pts)
        K = res["K"]
        self.b.set_scale(K)
        self.K = K
        x = res["crosstalk"]
        self.out(f"  K (counts per N)   drag row {K[0][0]:12.1f} {K[0][1]:12.1f}")
        self.out(f"                     lift row {K[1][0]:12.1f} {K[1][1]:12.1f}")
        self.out(f"  cross-talk         lift/drag {100 * x['lift_counts_per_drag_counts']:+.2f} %"
                 f"   drag/lift {100 * x['drag_counts_per_lift_counts']:+.2f} %")
        self.out(f"  worst residual     {1000 * res['resid_n_max']:.2f} mN = "
                 f"{100 * res['resid_frac_of_span']:.3f} % of the largest load "
                 f"({res['n_points']} dwells, drift {'fitted' if res['drift_fitted'] else 'not fitted'})")
        rec = {"date": time.strftime("%Y-%m-%d %H:%M"), "session": self.folder.name,
               "method": "least squares over calibration dwells "
                         "(counts = a + d t + K F), scripts/section_balance_logger.py fit",
               "n_points": res["n_points"], "resid_n_max": res["resid_n_max"],
               "max_load_n": res["max_load_n"], "drift_fitted": res["drift_fitted"]}
        (self.folder / "calibration_fit.json").write_text(
            json.dumps({**res, "record": rec}, indent=1) + "\n")
        if self.save_cal:
            bal = _load_json(self.cfg_path)
            bal.setdefault("_README", [
                "Section balance (firmware/section_balance/). Written by "
                "scripts/section_balance_logger.py; nothing else writes it.",
                "k_counts_per_n is re-sent to the board on every connect: the "
                "firmware keeps K in RAM only.",
                "The analysis refits K from the calibration dwells and does not "
                "use this copy."])
            bal["k_counts_per_n"] = K
            bal["k_record"] = rec
            self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
            self.cfg_path.write_text(json.dumps(bal, indent=1) + "\n")
            self.out(f"  recorded in {self._rel(self.cfg_path)}")
        return res

    # live view --------------------------------------------------------------------
    def live(self, seconds=None):
        """Live readout until Ctrl-C (or `seconds`). Nothing is recorded."""
        L = self.labels
        if hasattr(self.b.link, "set_conditions"):
            kind = "wind" if L["U_nom_ms"] > 0 else "zero"
            self.b.link.set_conditions(kind, L["set"], L["U_nom_ms"], L["alpha_deg"])
        zero = self.last_zero.get(self.block_key())
        self.b.start()
        t0 = None
        shown = 0.0
        try:
            for row, t_s, _ in self.b.rows():
                t0 = t_s if t0 is None else t0
                if seconds and t_s - t0 >= seconds:
                    break
                if time.monotonic() - shown < 0.5:
                    continue
                shown = time.monotonic()
                txt, F = self._readout((row["drag_counts"], row["lift_counts"]), zero,
                                       (row["drag_n"], row["lift_n"]))
                sys.stdout.write(f"\r  alpha {row['alpha_deg']:6.1f}  U {L['U_nom_ms']:5.2f}  "
                                 f"{txt}   raw {row['drag_counts']:>9} {row['lift_counts']:>9}"
                                 f"   flags {row['flags']}{self._rough(F)}   ")
                sys.stdout.flush()
        except KeyboardInterrupt:
            pass
        finally:
            self.b.stop()
            print()


# ── the command line ──────────────────────────────────────────────────────

HELP = """\
  set <name>              blade set: Plain, FS0.05, FS0.10, FS0.20 ...
  mount                   the slice was (re)mounted: zeros start again
  alpha <deg>             CFD convention: 0 cup into the wind, 90 tip A -> tip B, 180 convex
  rpm <fan rpm>           wind label from the fan set point (U from the fan calibration)
  u <m/s>                 wind label directly (nominal)
  umeas <m/s>             MEASURED wind speed at this set point (pitot); the analysis uses it
  air <degC> [Pa]         reference thermometer (and barometer) for the density
  note <text>             attached to the next dwell
  zero [s]                wind-off zero: FAN STOPPED
  wind [s]                wind-on dwell at the current labels
  support [s]             wind-on dwell with the support only (slice removed)
  cal d|l <g> [+|-] [s]   calibration load on the drag or lift axis; `cal d 0` unloaded
  cleared                 calibration string, pulley and masses are out of the test section
  fit                     fit K from this session's cal dwells, send it, record it
  tare                    board TARE for the live readout (wind off, no load)
  live [s]                live readout, Ctrl-C to stop
  burst [n]               accelerometer burst (default 4000 samples)
  status                  labels and calibration
  quit"""


def execute(s, line):
    """Run one REPL command against Session `s`. Returns False to quit."""
    parts = line.strip().split()
    if not parts or parts[0].startswith("#"):
        return True
    cmd, args = parts[0].lower(), parts[1:]
    num = lambda i, d=None: float(args[i]) if len(args) > i else d   # noqa: E731
    if cmd in ("q", "quit", "exit"):
        return False
    if cmd in ("help", "?"):
        s.out(HELP)
    elif cmd == "set":
        if not args:
            raise BalanceError("set needs a name")
        s.set_label("set", args[0])
    elif cmd == "mount":
        s.labels["mount"] += 1
        s.out(f"  mount {s.labels['mount']}: take zeros at each alpha again")
        s.remind_closing_zero()
    elif cmd == "alpha":
        s.set_label("alpha_deg", num(0))
    elif cmd == "rpm":
        U = s.set_wind(rpm=num(0))
        s.out(f"  fan {num(0):.0f} rpm -> U_nom {U:.2f} m/s (fan calibration; "
              f"measured to 700 rpm, extrapolated above)")
    elif cmd == "u":
        s.set_wind(U=num(0))
    elif cmd == "umeas":
        if not s.labels["U_nom_ms"] > 0:
            raise BalanceError("set the wind label first (`rpm` or `u`), then `umeas`")
        s.labels["U_meas_ms"] = num(0)
        s.out(f"  measured U {num(0):.2f} m/s for the dwells at this set point "
              f"(fan label {s.labels['U_nom_ms']:.2f}); the analysis uses it")
    elif cmd == "air":
        s.labels["air_temp_ref_c"] = num(0)
        s.labels["pressure_ref_pa"] = num(1)
    elif cmd == "note":
        s.pending_note = " ".join(args)
    elif cmd == "zero":
        s.out("  zero: the fan must be STOPPED")
        s.record("zero", num(0))
    elif cmd in ("wind", "support"):
        s.record(cmd, num(0))
    elif cmd == "cal":
        if len(args) < 2:
            raise BalanceError("cal d|l <grams> [+|-] [seconds]")
        axis = args[0].lower()[:1]
        rest = args[2:]
        direction = 1
        if rest and rest[0] in ("+", "-"):
            direction = 1 if rest[0] == "+" else -1
            rest = rest[1:]
        s.record("cal", float(rest[0]) if rest else None, axis=axis,
                 mass_g=float(args[1]), direction=direction)
    elif cmd == "cleared":
        s.cleared()
    elif cmd == "fit":
        s.fit()
    elif cmd == "tare":
        s.out("  " + s.b.checked("TARE 20", timeout=10))
    elif cmd == "live":
        s.live(num(0))
    elif cmd == "burst":
        s.burst(int(num(0, 4000)))
    elif cmd == "status":
        L = s.labels
        air = ("not set" if L["air_temp_ref_c"] is None else f"{L['air_temp_ref_c']:g} C"
               + (f", {L['pressure_ref_pa']:.0f} Pa" if L["pressure_ref_pa"] else ""))
        meas = "" if L["U_meas_ms"] is None else f"  measured {L['U_meas_ms']:.2f} m/s"
        s.out(f"  set {L['set']}  mount {L['mount']}  alpha {L['alpha_deg']:g}  "
              f"fan {L['fan_rpm'] or 0:.0f} rpm  U_nom {L['U_nom_ms']:.2f} m/s{meas}  "
              f"air {air}")
        s.out(f"  K {'set' if s.K else 'NOT set'}  ·  calibration hardware "
              f"{'IN the test section' if s.cal_hardware_in else 'out'}  ·  "
              f"{s.dwell_id} dwells in {s.folder}")
    else:
        raise BalanceError(f"unknown command {cmd!r} — `help` lists them")
    return True


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--port", default=None)
    ap.add_argument("--simulate", action="store_true",
                    help="no hardware: a simulated board with known forces")
    ap.add_argument("--realtime", action="store_true",
                    help="with --simulate: pace rows to the wall clock")
    ap.add_argument("--sim-truth", default=None,
                    help="JSON overriding the simulator's known forces")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--session", default="session",
                    help="folder name suffix (date and time are prefixed)")
    ap.add_argument("--set", default="Plain", help="initial blade set label")
    ap.add_argument("--notes", default="")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--balance-config", default=str(DEFAULT_BALANCE_CFG),
                    help="where K and the port are recorded")
    ap.add_argument("--no-save-cal", action="store_true",
                    help="`fit` sends K to the board but does not record it")
    ap.add_argument("--dwell", type=float, default=30.0, help="wind and support dwell, s")
    ap.add_argument("--zero", type=float, default=20.0, help="zero dwell, s")
    ap.add_argument("--cal-dwell", type=float, default=10.0, help="calibration dwell, s")
    ap.add_argument("--script", default=None,
                    help="run the commands in this file, then quit")
    ap.add_argument("--settle", type=float, default=2.5,
                    help="seconds to wait after opening the port")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        if a.simulate:
            truth = json.loads(Path(a.sim_truth).read_text()) if a.sim_truth else None
            b = Balance(SimulatedBalance(truth, seed=a.seed, realtime=a.realtime), "SIM")
            print("\n  SIMULATED — no board, no wind. Forces are known; see SIM_DEFAULTS.")
        else:
            bal = _load_json(a.balance_config)
            port = resolve_port(a.port, bal)
            b = Balance.open_serial(port, settle=a.settle)
        b.identify()
    except BalanceError as e:
        raise SystemExit(f"\n  {e}\n")
    except ImportError:
        raise SystemExit("\n  pyserial is missing:  pip install pyserial\n")

    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(b.host_time()))
    folder = Path(a.out) / f"{stamp}_{a.session}"
    s = Session(b, folder, set_name=a.set, notes=a.notes,
                balance_cfg_path=a.balance_config, save_cal=not a.no_save_cal,
                dwell_s=a.dwell, zero_s=a.zero, cal_s=a.cal_dwell)
    print(f"  {b.identity}")
    print(f"  session folder {folder}")
    print("  `help` lists the commands. The fan is controlled elsewhere, as usual.\n")
    try:
        if a.script:
            for line in Path(a.script).read_text().splitlines():
                if not line.strip() or line.strip().startswith("#"):
                    continue
                print(f"balance> {line.strip()}")
                try:
                    if not execute(s, line):
                        break
                except BalanceError as e:
                    print(f"  ✗ {e}")
                    raise SystemExit(2)
        else:
            while True:
                try:
                    line = input("balance> ")
                except EOFError:
                    break
                try:
                    if not execute(s, line):
                        break
                except (BalanceError, ValueError) as e:
                    print(f"  ✗ {e}")
                except KeyboardInterrupt:
                    print()
    finally:
        s.remind_closing_zero(always=True)
        s.close()
        b.close()
    print(f"\n  wrote {folder}")
    print(f"  next: python scripts/section_balance_analyze.py {Session._rel(folder)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
