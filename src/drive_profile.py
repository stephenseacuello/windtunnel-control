#!/usr/bin/env python3
"""
drive_profile.py — read, record, compare and apply ACS550 parameter sets.

    python src/drive_profile.py snapshot --name baseline
    python src/drive_profile.py diff  --profile windtunnel
    python src/drive_profile.py apply --profile windtunnel        # dry run
    python src/drive_profile.py apply --profile windtunnel --commit

Needs PMC firmware **3.0 or later** (`firmware/acs550_pmc_v3/`), which adds
the RD/WR verbs. Older builds are command-shaped only and cannot reach a
parameter at all.

═══════════════════════════════════════════════════════════════════════════
READS ARE FREE. WRITES ARE NOT.
═══════════════════════════════════════════════════════════════════════════
`snapshot` and `diff` only read. They cannot change the drive, and they are
where most of the value is: a timestamped record committed to git turns
"somebody changed something" into a two-line diff.

`apply` writes, and a parameter write is persistent with no undo — the same
as editing on the keypad. So:

  · it is a DRY RUN unless you pass --commit
  · it snapshots the live drive first, unprompted, and refuses to write if
    that snapshot cannot be saved
  · it shows every change and waits for confirmation
  · it reads each value back afterwards and reports what the drive is
    actually holding, which is not always what you sent — drives clamp
    silently, and some parameters are read-only while running

The refusal list is NOT here. It is in the PMC firmware, because a host-side
list can be copied, edited in a hurry and applied by somebody who did not
read it. Group 53 (the serial config of the very link the command arrives
on), 3018/3019 (the comm-loss watchdog) and group 99 (the motor model) are
refused by the firmware at any time, with no override.

═══════════════════════════════════════════════════════════════════════════
PROFILES
═══════════════════════════════════════════════════════════════════════════
`data/profiles/<name>.json`:

    {
      "name": "windtunnel",
      "description": "what this configuration is for",
      "parameters": { "2202": {"value": 300, "why": "30.0 s accel"} , ... }
    }

Parameters are keypad numbers as strings; values are raw register contents,
so a 30.0 s ramp is 300. `why` is not decoration — it is the difference
between a profile somebody maintains and one nobody dares touch.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parent.parent
PROFILES = REPO / "data" / "profiles"
SNAPSHOTS = REPO / "data" / "snapshots"

# Every parameter this package reads, writes, or reasons about. Read-only
# operating data (group 01/03) is included in a snapshot because it is
# context: what the drive was doing when the record was taken.
KNOWN = {
    401: "LAST FAULT",
    1001: "EXT1 COMMANDS", 1002: "EXT2 COMMANDS",
    1102: "EXT1/EXT2 SEL", 1103: "REF1 SELECT", 1105: "REF1 MAX",
    1106: "REF2 SELECT",
    2002: "MAXIMUM SPEED", 2007: "MINIMUM FREQ", 2008: "MAXIMUM FREQ",
    2202: "ACCELER TIME 1", 2203: "DECELER TIME 1",
    3018: "COMM FAULT FUNC", 3019: "COMM FAULT TIME",
    5302: "EFB STATION ID", 5303: "EFB BAUD RATE", 5304: "EFB PARITY",
    5305: "EFB CTRL PROFILE", 5306: "EFB OK MESSAGES",
    5307: "EFB CRC ERRORS", 5308: "EFB UART ERRORS",
    5310: "EFB PAR 10", 5311: "EFB PAR 11", 5312: "EFB PAR 12",
    9802: "COMM PROT SEL",
    9904: "MOTOR CTRL MODE", 9905: "MOTOR NOM VOLT", 9906: "MOTOR NOM CURR",
    9907: "MOTOR NOM FREQ", 9908: "MOTOR NOM SPEED", 9909: "MOTOR NOM POWER",
}

# ACS550 parameter groups, from the firmware manual. A full scan walks these
# rather than 0000-9999: most of that space does not exist, and every miss is
# a round trip over a 19200-baud link.
GROUPS = {
    1: "OPERATING DATA", 3: "FB ACTUAL SIGNALS", 4: "FAULT HISTORY",
    10: "START/STOP/DIR", 11: "REFERENCE SELECT", 12: "CONSTANT SPEEDS",
    13: "ANALOGUE INPUTS", 14: "RELAY OUTPUTS", 15: "ANALOGUE OUTPUTS",
    16: "SYSTEM CONTROLS", 20: "LIMITS", 21: "START/STOP",
    22: "ACCEL/DECEL", 23: "SPEED CTRL", 24: "TORQUE CTRL",
    25: "CRITICAL SPEEDS", 26: "MOTOR CONTROL", 29: "MAINTENANCE TRIG",
    30: "FAULT FUNCTIONS", 31: "AUTOMATIC RESET", 32: "SUPERVISION",
    33: "INFORMATION", 34: "PANEL DISPLAY", 35: "MOTOR TEMP MEAS",
    40: "PROCESS PID SET 1", 41: "PROCESS PID SET 2", 42: "EXT / TRIM PID",
    45: "ENERGY SAVING", 50: "ENCODER", 51: "EXT COMM MODULE",
    52: "PANEL COMM", 53: "EFB PROTOCOL", 64: "LOAD ANALYZER",
    81: "PFC CONTROL", 98: "OPTION MODULES", 99: "START-UP DATA",
}

# Groups worth scanning by default: everything this rig's behaviour depends
# on, without the PID/PFC/encoder space it does not use. `--all` takes the lot.
DEFAULT_SCAN = [1, 3, 4, 10, 11, 13, 14, 15, 16, 20, 21, 22, 26, 30,
                32, 33, 34, 51, 52, 53, 98, 99]

# Refused by the firmware. Repeated here only so the tool can say WHY before
# a round trip, never as the enforcement point.
FIRMWARE_REFUSES = {
    "group 53 (5302-5399)": lambda p: 5302 <= p <= 5399,
    "3018/3019 comm watchdog": lambda p: p in (3018, 3019),
    "group 99 (motor model)": lambda p: 9900 <= p <= 9999,
    "groups 01-04 read-only": lambda p: p < 500,
}


# Running counters, not configuration. They tick constantly, so including
# them in a profile guarantees a diff that never converges and trains the
# operator to ignore the diff — which is the whole value of having one.
COUNTERS = {
    5204: "PANEL OK MESSAGES", 5205: "PANEL CRC ERRORS",
    5306: "EFB OK MESSAGES", 5307: "EFB CRC ERRORS", 5308: "EFB UART ERRORS",
}


def is_counter(par):
    return int(par) in COUNTERS


def refusal(par):
    for why, test in FIRMWARE_REFUSES.items():
        if test(par):
            return why
    return None


def scan_groups(tp, groups, per_group=99, on_progress=None):
    """
    Read every parameter that answers, group by group.

    A drive returns an exception for parameters that do not exist in its
    build, so discovery is simply "ask and see". That is slower than a
    curated list — a few hundred round trips — but it is the only way to
    capture a configuration you did not write, which is exactly what a
    baseline of somebody else's commissioning is.
    """
    found, misses = {}, 0
    total = len(groups) * per_group
    done = 0
    for g in groups:
        for idx in range(1, per_group + 1):
            par = g * 100 + idx
            done += 1
            try:
                found[str(par)] = tp.read_param(par)
            except Exception:
                misses += 1
            if on_progress and done % 25 == 0:
                on_progress(done, total, len(found), g)
    return found, misses


def open_drive(a):
    from config import TunnelConfig
    import transport as _tr
    cfg = TunnelConfig.load(a.config)
    spec = cfg.get("transport") or {}
    if spec.get("kind") != "pmc":
        raise SystemExit("this tool speaks to the drive through the PMC; "
                         "tunnel.json transport.kind is not 'pmc'")
    tp = _tr.PMCTransport(
        a.port, baudrate=int(spec.get("baudrate", 115200)),
        host_watchdog_ms=int(spec.get("host_watchdog_ms", 5000)),
        feedback_scale=float(spec.get("feedback_scale", 295.0)))
    try:
        tp.connect()
    except Exception as e:
        raise SystemExit(
            f"\n  Could not reach the PMC on {a.port}: {e}\n\n"
            f"  Is it plugged in? `ls /dev/cu.usbmodem*` should list it.\n")
    if not getattr(tp, "_rdwr", False):
        tp.close()
        raise SystemExit(
            "\n  This PMC has no RD/WR. Parameter access needs acs550-pmc 3.0\n"
            "  or later — flash firmware/acs550_pmc_v3/.\n\n"
            "  The original sketch is untouched at firmware/acs550_pmc/.\n")
    return tp


def read_all(tp, pars, verbose=True):
    out, failed = {}, []
    for par in sorted(pars):
        try:
            out[str(par)] = tp.read_param(par)
            if verbose:
                print(f"    {par:>4}  {KNOWN.get(par, ''):<18} {out[str(par)]}")
        except Exception as e:
            failed.append((par, str(e)[:60]))
    return out, failed


def write_snapshot(values, name, note=""):
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = SNAPSHOTS / f"{stamp}_{name}.json"
    path.write_text(json.dumps({
        "name": name, "note": note,
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "labels": {str(k): v for k, v in KNOWN.items()},
        "parameters": values}, indent=2) + "\n")
    return path


# ═══════════════════════════════════════════════════════════════════════════

def cmd_snapshot(a):
    tp = open_drive(a)
    try:
        print(f"\n  reading {len(KNOWN)} parameters…\n")
        vals, failed = read_all(tp, KNOWN)
    finally:
        tp.close()
    path = write_snapshot(vals, a.name, a.note or "")
    print(f"\n  {len(vals)} read, {len(failed)} unreadable")
    for par, why in failed:
        print(f"    {par:>4}  — {why}")
    print(f"\n  wrote {path.relative_to(REPO)}")
    print(f"  Commit it. A snapshot nobody can diff against is a file, not a "
          f"record.")
    return 0


def cmd_scan(a):
    tp = open_drive(a)
    groups = sorted(GROUPS) if a.all else DEFAULT_SCAN
    print(f"\n  scanning {len(groups)} groups "
          f"({len(groups) * 99} candidate parameters)")
    print(f"  this is a round trip each — expect a few minutes\n")
    t0 = time.time()

    def prog(done, total, found, g):
        pct = 100 * done / total
        sys.stdout.write(f"\r    {pct:5.1f}%  group {g:>2} "
                         f"{GROUPS.get(g,''):<20} {found} found")
        sys.stdout.flush()

    try:
        vals, misses = scan_groups(tp, groups, on_progress=prog)
    finally:
        tp.close()
    print(f"\n\n  {len(vals)} parameters exist on this drive "
          f"({misses} candidates did not answer) in {time.time()-t0:.0f} s")
    path = write_snapshot(vals, a.name, a.note or f"full scan of {len(groups)} groups")
    print(f"  wrote {path.relative_to(REPO)}")
    print(f"\n  Promote it to a reusable profile with:")
    print(f"    python src/drive_profile.py promote --snapshot "
          f"{path.name} --name aerolab")
    return 0


def cmd_promote(a):
    """Turn a snapshot into a named, applyable profile."""
    src = SNAPSHOTS / a.snapshot
    if not src.exists():
        cands = sorted(SNAPSHOTS.glob("*.json"))
        raise SystemExit(f"no snapshot {a.snapshot}. Available:\n  " +
                         "\n  ".join(c.name for c in cands[-8:]))
    snap = json.loads(src.read_text())
    vals = snap["parameters"]

    keep = {}
    for k, v in sorted(vals.items(), key=lambda kv: int(kv[0])):
        par = int(k)
        if is_counter(par):
            continue                       # a running counter, not a setting
        if refusal(par) and not a.include_refused:
            continue                       # read-only or firmware-refused
        keep[k] = {"value": v,
                   "why": KNOWN.get(par, snap.get("labels", {}).get(k, ""))}

    PROFILES.mkdir(parents=True, exist_ok=True)
    out = PROFILES / f"{a.name}.json"
    if out.exists() and not a.force:
        raise SystemExit(f"{out} already exists — pass --force to replace it")
    out.write_text(json.dumps({
        "name": a.name,
        "description": a.description or f"captured from {src.name}",
        "_source": f"snapshot {src.name} taken {snap.get('when','?')}",
        "_note": "Values are raw register contents. Parameters the firmware "
                 "refuses to write (group 53, 3018/3019, group 99, groups "
                 "01-04) are excluded unless --include-refused was used; they "
                 "would show in a diff but could never be applied.",
        "parameters": keep}, indent=2) + "\n")
    print(f"\n  {len(keep)} parameters → {out.relative_to(REPO)}")
    print(f"  {len(vals) - len(keep)} excluded as read-only or firmware-refused")
    print(f"\n  Compare against the live drive with:")
    print(f"    python src/drive_profile.py diff --profile {a.name}")
    return 0


def cmd_diff(a):
    prof_path = PROFILES / f"{a.profile}.json"
    if not prof_path.exists():
        raise SystemExit(f"no profile at {prof_path}")
    prof = json.loads(prof_path.read_text())
    want = prof["parameters"]

    tp = open_drive(a)
    try:
        live, failed = read_all(tp, [int(k) for k in want], verbose=False)
    finally:
        tp.close()

    same, differ, unread = [], [], [p for p, _ in failed]
    for k, spec in want.items():
        target = spec["value"] if isinstance(spec, dict) else spec
        if k not in live:
            continue
        (same if live[k] == target else differ).append(
            (int(k), live[k], target,
             spec.get("why", "") if isinstance(spec, dict) else ""))

    print(f"\n  profile '{prof['name']}' vs the live drive\n")
    print(f"  {len(same)} already match, {len(differ)} differ, "
          f"{len(unread)} unreadable\n")
    if differ:
        print(f"  {'par':>5} {'name':<18} {'live':>8} {'profile':>8}   why")
        print(f"  {'-'*5} {'-'*18} {'-'*8} {'-'*8}   {'-'*30}")
        for par, live_v, target, why in sorted(differ):
            no = refusal(par)
            tag = f"  [FIRMWARE REFUSES: {no}]" if no else ""
            print(f"  {par:>5} {KNOWN.get(par,''):<18} {live_v:>8} "
                  f"{target:>8}   {why[:34]}{tag}")
    else:
        print("  the drive already matches this profile.")
    return 0


def cmd_apply(a):
    prof_path = PROFILES / f"{a.profile}.json"
    if not prof_path.exists():
        raise SystemExit(f"no profile at {prof_path}")
    prof = json.loads(prof_path.read_text())
    want = prof["parameters"]

    tp = open_drive(a)
    try:
        # Snapshot BEFORE anything. Refuse to write if it cannot be saved:
        # an un-backed-out change to a drive is not recoverable.
        print("\n  snapshotting the live drive first…")
        live, _ = read_all(tp, KNOWN, verbose=False)
        try:
            backup = write_snapshot(live, f"before_{a.profile}",
                                    f"taken automatically before applying "
                                    f"'{a.profile}'")
            print(f"  backup: {backup.relative_to(REPO)}")
        except Exception as e:
            raise SystemExit(f"  ✗ refusing to write — could not save a "
                             f"backup first: {e}")

        plan = []
        for k, spec in want.items():
            par = int(k)
            target = spec["value"] if isinstance(spec, dict) else spec
            no = refusal(par)
            cur = live.get(k)
            if cur == target:
                continue
            plan.append((par, cur, target,
                         spec.get("why", "") if isinstance(spec, dict) else "",
                         no))

        if not plan:
            print("\n  nothing to do — the drive already matches.")
            return 0

        print(f"\n  {len(plan)} parameter(s) would change:\n")
        for par, cur, target, why, no in sorted(plan):
            mark = "REFUSED" if no else "write  "
            print(f"    {mark} {par:>5} {KNOWN.get(par,''):<18} "
                  f"{cur} → {target}   {why[:32]}")
            if no:
                print(f"            firmware refuses this: {no}")

        writable = [p for p in plan if not p[4]]
        if not a.commit:
            print(f"\n  DRY RUN — nothing was written. Add --commit to apply "
                  f"{len(writable)} change(s).\n")
            return 0
        if not writable:
            print("\n  every change is refused by firmware. Nothing to do.\n")
            return 1

        print(f"\n  About to write {len(writable)} parameter(s). This is "
              f"persistent and has no undo.")
        if input("  Type the profile name to confirm: ").strip() != prof["name"]:
            print("  aborted.")
            return 1

        tp.unlock_writes()
        done, bad = [], []
        for par, cur, target, why, _ in sorted(writable):
            try:
                r = tp.write_param(par, target)
                ok = r["after"] == target
                (done if ok else bad).append((par, r["before"], r["after"],
                                              target))
                print(f"    {'ok  ' if ok else 'MISMATCH'} {par:>5}  "
                      f"{r['before']} → {r['after']}"
                      + ("" if ok else f"  (asked for {target})"))
            except Exception as e:
                bad.append((par, cur, "ERROR", target))
                print(f"    FAIL {par:>5}  {e}")
        tp.lock_writes()

        print(f"\n  {len(done)} written and verified, {len(bad)} did not take.")
        if bad:
            print("  A drive clamps out-of-range values silently and refuses "
                  "some\n  parameters while running. Check those by keypad.")
        if any(400 <= p[0] <= 5399 for p in done):
            print("\n  NOTE  group 53 is read at boot only. If anything in it "
                  "changed,\n        power-cycle the drive before trusting the "
                  "link.")
    finally:
        tp.close()
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--config", default=str(REPO / "data" / "tunnel.json"))
    p.add_argument("--port", default="/dev/cu.usbmodem1101")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="read every known parameter to JSON")
    s.add_argument("--name", default="snapshot")
    s.add_argument("--note", default="")
    s.set_defaults(fn=cmd_snapshot)

    d = sub.add_parser("diff", help="compare the drive against a profile")
    d.add_argument("--profile", required=True)
    d.set_defaults(fn=cmd_diff)

    sc = sub.add_parser("scan", help="discover EVERY parameter the drive has")
    sc.add_argument("--all", action="store_true",
                    help="every group, not just the ones this rig uses")
    sc.add_argument("--name", default="fullscan")
    sc.add_argument("--note", default="")
    sc.set_defaults(fn=cmd_scan)

    pr = sub.add_parser("promote", help="turn a snapshot into a profile")
    pr.add_argument("--snapshot", required=True, help="filename in data/snapshots/")
    pr.add_argument("--name", required=True, help="profile name, e.g. aerolab")
    pr.add_argument("--description", default="")
    pr.add_argument("--include-refused", action="store_true",
                    dest="include_refused",
                    help="keep parameters the firmware will never write")
    pr.add_argument("--force", action="store_true")
    pr.set_defaults(fn=cmd_promote)

    ap = sub.add_parser("apply", help="write a profile (dry run by default)")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--commit", action="store_true",
                    help="actually write. Without this it is a dry run.")
    ap.set_defaults(fn=cmd_apply)

    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
