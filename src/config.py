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

# Anchored to the repo, NOT the working directory. As a bare relative
# "tunnel.json" this never resolved from anywhere, and `load()` answers a
# missing path with an EMPTY config rather than an error — so every consumer
# using the default silently ran with no calibration, no tau, no port and no
# limits. This module's own docstring promises the bandwidth guard is "on by
# default rather than by discipline"; a path that never resolves turned it off
# by default instead.
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "tunnel.json"


class TunnelConfig:
    def __init__(self, data=None, path=DEFAULT_PATH, readonly=False):
        self.path = Path(path)
        self.data = dict(data or {})
        # A dry run models the tunnel; it must not leave marks on the real
        # config. `run.py --dry-run characterize` measured the SIMULATOR's
        # time constant and wrote 1.504 s over the measured 0.60 s — a
        # four-run mean — in data/tunnel.json. Under the old broken default
        # that landed in a throwaway file nobody read; once the path was
        # fixed to resolve, the same command started hitting the real one.
        # Guarding the nine .save() sites individually would leave the tenth.
        self.readonly = bool(readonly)

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
    def load(cls, path=DEFAULT_PATH, required=False, readonly=False):
        p = Path(path)
        if not p.exists():
            if required:
                raise FileNotFoundError(
                    f"no config at {p}. Run `calibrate` and `characterize` "
                    f"first, or pass the values explicitly.")
            # SAY SO. An empty config is not a neutral default: tau is absent
            # so the bandwidth guard passes everything, calibration is absent
            # so velocities read as zero, and the port is absent so the link
            # falls back to autodetect. All of that is survivable; none of it
            # is survivable *silently*, because the run still completes and
            # writes a plausible-looking file.
            import sys as _s
            print(f"  ⚠ no config at {p} — continuing with an EMPTY config: "
                  f"no tau, no calibration, no port, no limits.",
                  file=_s.stderr)
            return cls({}, p, readonly=readonly)
        return cls(json.loads(p.read_text()), p, readonly=readonly)

    def save(self, path=None):
        """
        Persist, MERGING over whatever is on disk now rather than replacing it.

        This file is written by several processes that do not know about each
        other: the dashboard holds a copy loaded at startup, `run.py` writes
        calibration, and `tunnel_node.py` writes the node's temperature
        offset. A plain write of an in-memory dict silently reverts every key
        another process added since load — the dashboard's own /api/ambient
        save was erasing the node offset that tunnel_node.connect() re-applies
        each session, which would have put a 20 C self-heating error back into
        every density, and therefore 6.5% into every Cp, with nothing saying
        so.

        Keys THIS instance holds win; keys only on disk survive. Nothing in
        this codebase deletes config keys, so merge-wins-on-conflict is the
        right rule here — if deletion is ever needed it will need an explicit
        path, because this will resurrect a removed key.

        Written temp-then-rename so a crash mid-write cannot leave a
        half-written config, which is unreadable rather than merely wrong.
        """
        p = Path(path or self.path)
        if self.readonly and path is None:
            import sys as _s
            print(f"  (dry run — not saved to {p})", file=_s.stderr)
            return p

        def merge(base, over):
            for k, v in over.items():
                if isinstance(v, dict) and isinstance(base.get(k), dict):
                    merge(base[k], v)
                else:
                    base[k] = v
            return base

        out = self.data
        if p.exists():
            try:
                out = merge(json.loads(p.read_text()), self.data)
            except (ValueError, OSError):
                out = self.data          # unreadable on disk: ours is better
        p.parent.mkdir(parents=True, exist_ok=True)
        # Unique per writer. A fixed ".tmp" means two processes writing at
        # once share one scratch file: one rename wins, the other raises
        # FileNotFoundError, and the window in between can leave the real
        # file torn — which makes it unparseable for EVERY consumer at
        # startup, not merely stale. That is the opposite of what an atomic
        # write is for.
        import os as _os
        tmp = p.with_suffix(f"{p.suffix}.{_os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(out, indent=2, default=str) + "\n")
            tmp.replace(p)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        self.data = out
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
