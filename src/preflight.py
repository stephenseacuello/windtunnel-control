"""
preflight.py — checks that run before a long profile, not after it fails.

A turbulence run is minutes. A frequency sweep is half an hour. Discovering at
minute eighteen that the SD card is full, or that the velocity sensor went
stale ten minutes ago, wastes a test session and — if anyone was waiting on
the tunnel — somebody else's afternoon too.

These are all cheap. None of them touches the fan.

═══════════════════════════════════════════════════════════════════════════
WHY DISK SPACE IS ON THIS LIST
═══════════════════════════════════════════════════════════════════════════
The player streams every sample to disk and flushes it, deliberately, so a
crash at minute four does not lose the first four minutes. The cost of that
choice is that a full filesystem produces a write failure *mid-profile* rather
than a clean refusal at the start. On a Pi with an SD card and a season of
logs on it, that is a real failure mode rather than a theoretical one.
"""

from __future__ import annotations

import shutil
from pathlib import Path

PASS, WARN, FAIL = "pass", "warn", "fail"

# Measured from real logs: ~40 bytes per row with the velocity column.
BYTES_PER_SAMPLE = 40


def check_disk(log_dir, samples, min_free_mb=50):
    """Will this run fit, with room to spare?"""
    p = Path(log_dir)
    p.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(p)
    free_mb = usage.free / 1e6
    need_mb = samples * BYTES_PER_SAMPLE / 1e6

    if free_mb < need_mb + min_free_mb:
        return (FAIL, "disk space",
                f"{free_mb:.0f} MB free, this run needs ~{need_mb:.1f} MB plus "
                f"{min_free_mb} MB headroom.\n"
                f"The player flushes every sample, so a full filesystem fails "
                f"mid-profile rather than refusing up front. Clear old logs "
                f"first.")
    if free_mb < 500:
        return (WARN, "disk space",
                f"{free_mb:.0f} MB free — enough for this run "
                f"(~{need_mb:.1f} MB) but getting tight.")
    return (PASS, "disk space",
            f"{free_mb / 1000:.1f} GB free, run needs ~{need_mb:.1f} MB")


def check_log_volume(log_dir, warn_files=400, warn_mb=500):
    """Housekeeping. Logs accumulate quietly until they don't."""
    p = Path(log_dir)
    if not p.exists():
        return (PASS, "log volume", "no logs yet")
    files = list(p.glob("*.csv"))
    total = sum(f.stat().st_size for f in files) / 1e6
    if len(files) > warn_files or total > warn_mb:
        return (WARN, "log volume",
                f"{len(files)} runs, {total:.0f} MB. Archive the old ones — "
                f"exports bundle a run with its provenance, so they are safe "
                f"to move off once exported.")
    return (PASS, "log volume", f"{len(files)} runs, {total:.0f} MB")


def check_drive(drive):
    """
    Fault state, control location, and link health.

    LOC/REM is the subtle one: a drive in local keypad mode ignores the
    fieldbus while every write still reports success, so a run would appear to
    proceed against a drive that was never listening.
    """
    checks = []
    try:
        st = drive.status()
    except Exception as e:
        return [(FAIL, "drive comms", str(e))]

    checks.append((FAIL, "drive fault",
                   f"drive is faulted, par 0401 = {drive.last_fault()}. "
                   f"Find out why before resetting.")
                  if st.get("TRIPPED") else
                  (PASS, "drive fault", "no active fault"))

    checks.append((FAIL, "control location",
                   "drive is in LOCAL keypad mode and will ignore the "
                   "fieldbus. Press LOC/REM on the keypad.")
                  if not st.get("REMOTE", True) else
                  (PASS, "control location", "REMOTE"))

    try:
        c = drive.comm_counters()
        if c["crc_err"] or c["uart_err"]:
            checks.append((WARN, "link quality",
                           f"CRC {c['crc_err']}, UART {c['uart_err']} errors "
                           f"since power-up. A long run on a marginal link is "
                           f"how you get an abort at minute twelve."))
        else:
            checks.append((PASS, "link quality", f"{c['ok']} frames, no errors"))
    except Exception:
        pass
    return checks


def check_velocity(source):
    """
    Is there a live wind speed reading, and is it fresh?

    Warns rather than fails when absent — a run without it is still a valid
    run, it just records what the drive did rather than what the air did.
    """
    if source is None:
        return (WARN, "velocity source",
                "none configured — the run will record drive frequency only, "
                "not measured wind speed.")
    d = source.describe()
    if not d["healthy"]:
        return (WARN, "velocity source",
                f"{d['name']} is stale"
                + (f" ({d['last_error']})" if d.get("last_error") else "")
                + ".\nThe run will proceed but the velocity column will be "
                  "blank, and closed-loop modes will refuse.")
    return (PASS, "velocity source",
            f"{d['name']} reading {d['value']:.2f} {d['units']}")


def check_realizability(diagnostics, tau):
    """Is the profile one the tunnel can actually produce?"""
    if tau is None:
        return (WARN, "bandwidth",
                "no τ recorded — profiles cannot be checked against the "
                "tunnel's bandwidth. Run characterize.")
    r = diagnostics.get("amplitude_retained")
    if r is None:
        return (PASS, "bandwidth", "not applicable")
    if r < 0.4:
        return (FAIL, "bandwidth",
                f"only {r:.0%} of the commanded amplitude survives the "
                f"tunnel's lag. This will produce a ripple, not a gust.")
    if r < 0.7:
        return (WARN, "bandwidth",
                f"{r:.0%} retained — noticeably smaller and smoother than "
                f"drawn. Usable if you report it that way.")
    return (PASS, "bandwidth", f"{r:.0%} of commanded amplitude retained")


def check_duration(duration_s, warn_min=20):
    """
    Flag runs long enough that nobody will be watching the whole way.

    Not a fault — long runs are the point. But past twenty minutes the drive's
    comm watchdog is the only thing that stops the fan if the host dies, and
    that is worth being conscious of rather than surprised by.
    """
    if duration_s > warn_min * 60:
        return (WARN, "duration",
                f"{duration_s / 60:.0f} minutes. Nobody should be in the test "
                f"section for any of it, and the drive's comm watchdog is the "
                f"only thing that stops the fan if the host dies.")
    return (PASS, "duration", f"{duration_s / 60:.1f} minutes")


def run_all(drive=None, velocity_source=None, samples=0, duration_s=0,
            diagnostics=None, tau=None, log_dir="logs"):
    """
    Returns (ok_to_run, checks). `ok_to_run` is False if anything FAILed —
    warnings never block, because most of them are judgement calls the
    operator is better placed to make than this function is.
    """
    checks = []
    if samples:
        checks.append(check_disk(log_dir, samples))
    checks.append(check_log_volume(log_dir))
    if drive is not None:
        checks.extend(check_drive(drive))
    checks.append(check_velocity(velocity_source))
    if diagnostics is not None:
        checks.append(check_realizability(diagnostics, tau))
    if duration_s:
        checks.append(check_duration(duration_s))

    ok = not any(s == FAIL for s, _, _ in checks)
    return ok, [{"status": s, "name": n, "detail": d} for s, n, d in checks]
