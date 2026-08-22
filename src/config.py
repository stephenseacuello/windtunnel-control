"""
config.py — persistent tunnel configuration.

Everything the tunnel "knows about itself" lives in one JSON file rather than
being retyped on the command line every run:

    · tau                measured time constant, from characterize
    · f_corner           derived, the bandwidth ceiling
    · calibration        Hz ↔ velocity, from calibrate
    · hz_limit           soft ceiling so a typo cannot command full speed
    · ramp_accel/decel   what 2202/2203 are set to
    · port, baud, unit   link settings

Two reasons this is worth a module rather than a pile of flags:

**Reproducibility.** Every run's metadata sidecar records the config that
produced it. Six months later you can tell whether two datasets were taken
with the same calibration, which is the sort of thing that silently invalidates
a comparison.

**Not retyping τ.** If `--tau` is optional and easy to forget, it will be
forgotten, and the bandwidth check that stops you running an unrealizable
profile silently does nothing. Reading it from a file means the guard is on by
default rather than by discipline.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

DEFAULT_PATH = Path("tunnel.json")


class TunnelConfig:
    def __init__(self, data=None, path=DEFAULT_PATH):
        self.path = Path(path)
        self.data = dict(data or {})

    # ── access ───────────────────────────────────────────────────────────

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value, note=None):
        self.data[key] = value
        hist = self.data.setdefault("_history", [])
        hist.append({"when": datetime.now().isoformat(timespec="seconds"),
                     "key": key, "value": value, "note": note})
        # Keep the tail only — this is a breadcrumb trail, not an audit log.
        self.data["_history"] = hist[-40:]
        return self

    @property
    def tau(self):
        return self.data.get("tau")

    @property
    def f_corner(self):
        """Bandwidth ceiling implied by tau. None if tau is unknown."""
        t = self.tau
        return 1.0 / (2 * math.pi * t) if t else None

    @property
    def hz_limit(self):
        return self.data.get("hz_limit")

    @property
    def calibration(self):
        """Rehydrate the Calibration object, or None if not yet built."""
        d = self.data.get("calibration")
        if not d:
            return None
        from calibration import Calibration
        return Calibration.from_dict(d)

    def set_calibration(self, cal, note=None):
        return self.set("calibration", cal.to_dict(), note=note)

    # ── persistence ──────────────────────────────────────────────────────

    @classmethod
    def load(cls, path=DEFAULT_PATH, required=False):
        p = Path(path)
        if not p.exists():
            if required:
                raise FileNotFoundError(
                    f"no config at {p}. Run `calibrate` and `characterize` "
                    f"first, or pass the values explicitly.")
            return cls({}, p)
        return cls(json.loads(p.read_text()), p)

    def save(self, path=None):
        p = Path(path or self.path)
        p.write_text(json.dumps(self.data, indent=2, default=str))
        return p

    # ── reporting ────────────────────────────────────────────────────────

    def summary(self):
        """What the tunnel currently knows about itself, and what it doesn't."""
        lines = [f"config: {self.path}"]
        missing = []

        if self.tau:
            lines.append(f"  τ = {self.tau:.2f} s  →  corner "
                         f"{self.f_corner:.3f} Hz")
        else:
            missing.append("τ — run `characterize`")

        cal = self.calibration
        if cal:
            lines.append(f"  calibration: {cal.hz_min:.0f}–{cal.hz_max:.0f} Hz "
                         f"→ {cal.velocity(cal.hz_min):.1f}–"
                         f"{cal.velocity(cal.hz_max):.1f} {cal.units}"
                         + (f"  (R²={cal.r2:.4f})" if cal.r2 else ""))
        else:
            missing.append("velocity calibration — run `calibrate`")

        if self.hz_limit:
            lines.append(f"  soft limit: {self.hz_limit:.1f} Hz")
        else:
            missing.append("hz_limit — set one before unattended runs")

        for k in ("ramp_accel", "ramp_decel"):
            if self.data.get(k) is not None:
                lines.append(f"  {k}: {self.data[k]:.1f} s")

        if missing:
            lines.append("  not yet known:")
            lines += [f"    · {m}" for m in missing]
        return "\n".join(lines)

    def ambient(self):
        """
        Air properties for the recorded conditions, used to normalize runs.

        Density from the ideal gas law, ρ = p/(R·T) with R = 287.05 J/kg·K for
        dry air. A 10 °C swing moves ρ by ~3.5%, and dynamic pressure with it —
        which is why two identical RPM sweeps taken on different days do not
        give identical forces. Record temperature and pressure per session and
        this stops being a mystery.
        """
        T_c = self.data.get("temperature_c")
        p_pa = self.data.get("pressure_pa", 101325.0)
        if T_c is None:
            return None
        rho = p_pa / (287.05 * (T_c + 273.15))
        rho_ref = 101325.0 / (287.05 * 288.15)      # ISA sea level, 15 °C
        return {"temperature_c": T_c, "pressure_pa": p_pa,
                "density": round(rho, 4), "density_ref": round(rho_ref, 4),
                "density_ratio": round(rho / rho_ref, 4),
                "dynamic_pressure_scale": round(rho / rho_ref, 4)}

    def require(self, *keys):
        """Fail loudly rather than silently proceeding without a guard."""
        absent = [k for k in keys if self.data.get(k) is None]
        if absent:
            raise ValueError(
                f"config is missing {', '.join(absent)}. This mode needs it — "
                f"see `status` for what to run.")
        return True
