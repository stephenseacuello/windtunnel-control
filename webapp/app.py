#!/usr/bin/env python3
"""
app.py — Flask dashboard for the Aerolab wind tunnel.

    python app.py --port /dev/ttyVFD
    python app.py --dry-run                 # simulated drive, no hardware

Then open http://127.0.0.1:5000

═══════════════════════════════════════════════════════════════════════════
NETWORK EXPOSURE
═══════════════════════════════════════════════════════════════════════════
Binds to **127.0.0.1 by default**, so it is reachable only from the machine it
runs on. Use SSH port forwarding to reach it from a bench:

    ssh -L 5000:localhost:5000 pi@tunnel-pi

`--host 0.0.0.0` exposes it to the whole network with **no authentication**,
which means anyone who can reach the Pi can spin a 15 HP fan. There is a
deliberate confirmation prompt on that flag. Lab network only, and preferably
not even then.

═══════════════════════════════════════════════════════════════════════════
WHAT PROTECTS YOU IF THE BROWSER MISBEHAVES
═══════════════════════════════════════════════════════════════════════════
Nothing in the UI is a safety guard. All enforcement is in controller.py and
in the drive itself:

  · the soft frequency limit is applied server-side to every setpoint
  · the drive's comm watchdog (par 3018/3019) stops the fan if this process
    dies, which is what makes a browser an acceptable place to command from
  · the hardwired E-stop is untouched and remains the actual safety device
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from flask import Flask, Response, jsonify, render_template, request

import analyze as analysis
from controller import TunnelController

app = Flask(__name__)
ctl: TunnelController = None


def ok(**kw):
    return jsonify({"ok": True, **kw})


def err(message, code=400):
    return jsonify({"ok": False, "error": str(message)}), code


@app.route("/")
def index():
    return render_template("index.html")


# ── live state ────────────────────────────────────────────────────────────

@app.route("/api/state")
def api_state():
    return jsonify(ctl.snapshot())


@app.route("/api/trace")
def api_trace():
    """Telemetry ring buffer for the live plot."""
    n = int(request.args.get("n", 400))
    return jsonify({"points": list(ctl.trace)[-n:]})


@app.route("/api/stream")
def api_stream():
    """
    Server-sent events. One connection, pushed at the poll rate, rather than
    every open tab hammering /api/state on its own timer.
    """
    def gen():
        last = 0.0
        while True:
            snap = ctl.snapshot()
            pts = list(ctl.trace)[-2:]
            yield f"data: {json.dumps({'state': snap, 'points': pts})}\n\n"
            time.sleep(0.25)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# ── manual control ────────────────────────────────────────────────────────

@app.route("/api/setpoint", methods=["POST"])
def api_setpoint():
    d = request.get_json(force=True)
    try:
        return ok(target=ctl.set_setpoint(d["value"], d.get("units", "hz")))
    except Exception as e:
        return err(e)


@app.route("/api/go", methods=["POST"])
def api_go():
    try:
        ctl.go()
        return ok()
    except Exception as e:
        return err(e)


@app.route("/api/stop", methods=["POST"])
def api_stop():
    ctl.stop()
    return ok()


@app.route("/api/estop", methods=["POST"])
def api_estop():
    ctl.estop()
    return ok()


@app.route("/api/clear-estop", methods=["POST"])
def api_clear_estop():
    try:
        ctl.clear_estop()
        return ok()
    except Exception as e:
        return err(e)


# ── profiles ──────────────────────────────────────────────────────────────

@app.route("/api/profile/preview", methods=["POST"])
def api_preview():
    """Build and check a profile without running it. The safe half of the UI."""
    try:
        t, u, desc, diag, pred = ctl.build_profile(request.get_json(force=True))
        step = max(1, len(u) // 600)          # decimate for the browser
        return ok(desc=desc, diagnostics=diag,
                  predicted=([round(float(x), 3) for x in pred[::step]]
                             if pred is not None else None),
                  t=[round(float(x), 3) for x in t[::step]],
                  u=[round(float(x), 3) for x in u[::step]],
                  hz_min=float(u.min()), hz_max=float(u.max()),
                  duration=float(t[-1]),
                  velocity=([round(float(ctl.cfg.calibration.velocity(x)), 2)
                             for x in u[::step]]
                            if ctl.cfg.calibration else None))
    except Exception as e:
        return err(e)


@app.route("/api/profile/run", methods=["POST"])
def api_run():
    d = request.get_json(force=True)
    try:
        return ok(job=ctl.start_profile(d, skip_preflight=d.get("force", False)))
    except Exception as e:
        return err(e)


@app.route("/api/preflight", methods=["POST"])
def api_preflight():
    """Run the checks without running anything. Touches nothing."""
    d = request.get_json(force=True)
    try:
        samples = duration = 0
        diag = None
        if d.get("spec"):
            t, u, _desc, diag, _p = ctl.build_profile(d["spec"])
            samples = len(u)
            duration = float(t[-1]) + float(d["spec"].get("settle", 20))
        return ok(**ctl.preflight(samples=samples, duration_s=duration,
                                  diagnostics=diag))
    except Exception as e:
        return err(e)


@app.route("/api/config/reload", methods=["POST"])
def api_reload():
    return ok(summary=ctl.reload_config())


@app.route("/api/profile/abort", methods=["POST"])
def api_abort():
    ctl.abort_profile()
    return ok()


# ── commissioning ─────────────────────────────────────────────────────────

@app.route("/api/commission/characterize", methods=["POST"])
def api_characterize():
    d = request.get_json(force=True)
    try:
        return ok(job=ctl.run_characterize(
            base=float(d.get("base", 20)), step=float(d.get("step", 10)),
            settle=float(d.get("settle", 30)), record=float(d.get("record", 30))))
    except Exception as e:
        return err(e)


@app.route("/api/commission/freqresp", methods=["POST"])
def api_freqresp():
    d = request.get_json(force=True)
    try:
        freqs = [float(x) for x in str(d.get("frequencies",
                 "0.02,0.05,0.1,0.2,0.5")).split(",")]
        return ok(job=ctl.run_freqresp(base=float(d.get("base", 25)),
                                       amp=float(d.get("amp", 5)),
                                       frequencies=freqs,
                                       cycles=int(d.get("cycles", 6))))
    except Exception as e:
        return err(e)


@app.route("/api/commission/verify", methods=["POST"])
def api_verify():
    d = request.get_json(force=True)
    try:
        return ok(job=ctl.run_verify_hold(hz=float(d.get("hz", 30)),
                                          settle=float(d.get("settle", 30)),
                                          hold=float(d.get("hold", 30))))
    except Exception as e:
        return err(e)


@app.route("/api/commission/verify/apply", methods=["POST"])
def api_verify_apply():
    d = request.get_json(force=True)
    try:
        return ok(result=ctl.apply_verify(float(d["hz"]), float(d["measured"])))
    except Exception as e:
        return err(e)


# ── the load and the turbine ────────────────────────────────────────────

@app.route("/api/load/on", methods=["POST"])
def api_load_on():
    try:
        ctl.load_on()
    except Exception as e:
        return err(str(e))
    return ok()


@app.route("/api/load/off", methods=["POST"])
def api_load_off():
    try:
        ctl.load_off()
    except Exception as e:
        return err(str(e))
    return ok()


@app.route("/api/load/amps", methods=["POST"])
def api_load_amps():
    d = request.get_json(force=True, silent=True) or {}
    try:
        return ok(amps=ctl.set_load_amps(d.get("amps", 0.0)))
    except Exception as e:
        return err(str(e))


@app.route("/api/sweep/start", methods=["POST"])
def api_sweep_start():
    d = request.get_json(force=True, silent=True) or {}
    try:
        return ok(sweep=ctl.start_blade_sweep(
            blade=(d.get("blade") or "").strip(),
            notes=(d.get("notes") or "").strip(),
            start_rpm=float(d.get("start_rpm", 500)),
            stop_rpm=float(d.get("stop_rpm", 1800)),
            rpm_step=float(d.get("rpm_step", 100)),
            step_amps=float(d.get("step_amps", 0.02)),
            dwell=float(d.get("dwell", 1.0)),
            stop_power_frac=float(d.get("stop_power_frac", 0.80)),
            max_amps=float(d.get("max_amps", 0.8))))
    except Exception as e:
        return err(str(e))


@app.route("/api/sweep/abort", methods=["POST"])
def api_sweep_abort():
    return ok(aborted=ctl.abort_blade_sweep())


# ── the blade library ───────────────────────────────────────────────────

def _repo():
    return Path(__file__).resolve().parent.parent


def _sweep_summary(name):
    """
    (meta, points) from logs/sweep_<name>_summary.csv, or (None, []).

    Reads the `# key,value` header rows the sweep writes, so the protocol
    fingerprint travels with the curve. Two blades whose fingerprints differ
    were not measured the same way and must not be plotted as if they were.
    """
    import csv as _csv
    f = _repo() / "logs" / f"sweep_{name}_summary.csv"
    if not f.exists():
        return None, []
    meta, rows = {}, []
    with f.open() as fh:
        body = []
        for line in fh:
            if line.startswith("#"):
                k, _, v = line[1:].partition(",")
                meta[k.strip()] = v.strip()
            else:
                body.append(line)
    for r in _csv.DictReader(body):
        try:
            rows.append({
                "rpm": float(r.get("fan_rpm_cmd") or r.get("fan_rpm") or 0),
                "mps": float(r["wind_mps"]),
                "p_w": float(r.get("p_max_fit_w") or r.get("p_max_w") or 0),
                "i_a": float(r.get("i_at_pmax_fit_a") or r.get("i_at_pmax_a") or 0),
                "limited_by": r.get("limited_by", ""),
                "clean": (r.get("clean") or "1") in ("1", "True", "true")})
        except (KeyError, ValueError):
            continue
    return meta, rows


@app.route("/api/blades")
def api_blades():
    """Every rotor we have geometry for, results for, or both."""
    import json as _json
    bdir, ldir = _repo() / "blades", _repo() / "logs"
    names = {p.stem for p in bdir.glob("*.stl")}
    names |= {p.name[len("sweep_"):-len("_summary.csv")]
              for p in ldir.glob("sweep_*_summary.csv")}
    out = []
    for n in sorted(names):
        stl = bdir / f"{n}.stl"
        side = bdir / f"{n}.json"
        meta, pts = _sweep_summary(n)
        info = {}
        if side.exists():
            try:
                info = _json.loads(side.read_text())
            except Exception:
                pass
        out.append({
            "name": n,
            "stl": stl.exists(),
            "stl_kb": round(stl.stat().st_size / 1024) if stl.exists() else 0,
            "info": info,
            "swept": bool(pts),
            "points": len(pts),
            "notes": (meta or {}).get("notes", ""),
            "protocol": (meta or {}).get("protocol", ""),
            "clean": all(p["clean"] for p in pts) if pts else None,
            "p_max": max((p["p_w"] for p in pts), default=None)})
    return jsonify({"ok": True, "blades": out})


@app.route("/api/blades/<name>/stl")
def api_blade_stl(name):
    f = _repo() / "blades" / f"{Path(name).name}.stl"
    if not f.exists():
        return err("no STL for that blade", 404)
    return Response(f.read_bytes(), mimetype="model/stl")


@app.route("/api/blades/<name>/curve")
def api_blade_curve(name):
    meta, pts = _sweep_summary(Path(name).name)
    if not pts:
        return err("no sweep on record for that blade", 404)
    return jsonify({"ok": True, "meta": meta, "points": pts})


@app.route("/api/job")
def api_job():
    """Full job record including captured output — too big for the SSE tick."""
    j = ctl.job
    if not j:
        return ok(job=None)
    return ok(job={k: v for k, v in j.items() if k not in ("diagnostics",)})


@app.route("/api/sweep", methods=["POST"])
def api_sweep():
    d = request.get_json(force=True)
    try:
        return ok(job=ctl.run_sweep(
            float(d["start"]), float(d["stop"]), float(d["step"]),
            settle=float(d.get("settle", 25)), dwell=float(d.get("dwell", 15)),
            units=d.get("units", "hz")))
    except Exception as e:
        return err(e)


@app.route("/api/velocity/manual", methods=["POST"])
def api_manual_velocity():
    d = request.get_json(force=True)
    try:
        v = ctl.submit_manual_velocity(float(d["value"]))
        return ok(value=v, source=ctl.vsource.describe())
    except Exception as e:
        return err(e)


@app.route("/api/velocity/hold", methods=["POST"])
def api_hold_velocity():
    d = request.get_json(force=True)
    try:
        return ok(job=ctl.hold_velocity(
            float(d["target"]), duration=float(d.get("duration", 90))))
    except Exception as e:
        return err(e)


@app.route("/api/session", methods=["GET", "POST"])
def api_session():
    if request.method == "POST":
        d = request.get_json(force=True)
        return ok(session=ctl.set_session(
            operator=d.get("operator"), configuration=d.get("configuration"),
            notes=d.get("notes"), project=d.get("project")))
    return ok(session=ctl.cfg.get("session"))


@app.route("/api/logs/<name>/export")
def api_export(name):
    """
    Bundle a run for handoff: the CSV, its provenance sidecar, the points
    table if it is a sweep, and a README explaining the columns.

    The README matters. A CSV handed to another lab without one becomes
    unusable the moment the person who made it moves on.
    """
    import io
    import zipfile
    from flask import send_file

    stem = Path(name).stem
    d = Path("logs")
    files = [p for p in (d / f"{stem}.csv", d / f"{stem}.json",
                         d / f"{stem}_points.csv", d / f"{stem}.png")
             if p.exists()]
    if not files:
        return err("not found", 404)

    meta = {}
    j = d / f"{stem}.json"
    if j.exists():
        meta = json.loads(j.read_text())
    sess = meta.get("session") or {}
    cal = meta.get("calibration") or {}

    readme = f"""Wind tunnel run: {stem}
{'=' * (18 + len(stem))}

Recorded   {meta.get('recorded', 'unknown')}
Operator   {sess.get('operator', 'not recorded')}
Config     {sess.get('configuration', 'not recorded')}
Project    {sess.get('project', '-')}
Notes      {sess.get('notes', '-')}
Mode       {meta.get('mode', '-')}
{'SIMULATED — not real tunnel data' if meta.get('simulated') else ''}

COLUMNS ({stem}.csv)
  t_s       seconds from the start of the profile
  cmd_hz    drive frequency commanded
  meas_hz   drive frequency reported back
  meas_a    motor current, amps
{'  phase     settling | acquiring — acquire only inside `acquiring`' if (d / f'{stem}_points.csv').exists() else ''}
{'  point     index into the setpoint list' if (d / f'{stem}_points.csv').exists() else ''}

The gap between cmd_hz and meas_hz is the tunnel's dynamic response. It is
data, not error — a first-order fit to the pair recovers the time constant.

CALIBRATION AT THE TIME OF THIS RUN
  {('v = %.4f*Hz %+.3f %s' % (cal['coeffs'][0], cal['coeffs'][1], cal.get('units','m/s'))) if cal.get('coeffs') else 'none recorded'}
  status: {meta.get('calibration_status', '-')}
  {('%.2f rpm/Hz' % cal['rpm_per_hz']) if cal.get('rpm_per_hz') else ''}

  Velocity is DERIVED from frequency through this fit, not measured
  independently. Re-deriving it later with a different calibration will give
  different numbers — use the one recorded here.

AIR CONDITIONS
  {json.dumps(meta.get('ambient')) if meta.get('ambient') else 'not recorded — density affects every force'}

TUNNEL DYNAMICS
  tau {meta.get('tau')} s rising, {meta.get('tau_down')} s falling
  Content above ~{(1 / (2 * 3.14159 * meta['tau'])):.3f} Hz is attenuated by the
  tunnel itself.""" if meta.get("tau") else ""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.name)
        z.writestr("README.txt", readme)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"{stem}.zip")


# ── parameters ────────────────────────────────────────────────────────────

PARAM_GROUPS = [
    ("Communication", [
        (9802, "COMM PROT SEL", "1 = STD MODBUS"),
        (5302, "EFB STATION ID", "must match --unit"),
        (5303, "EFB BAUD RATE", ""),
        (5304, "EFB PARITY", ""),
        (5305, "EFB CTRL PROFILE", "0 = ABB DRV LIM"),
        (5310, "EFB PAR 10 → 40005", "103 = output freq"),
        (5311, "EFB PAR 11 → 40006", "104 = current"),
    ]),
    ("Control source", [
        (9902, "APPLIC MACRO", "record before changing anything"),
        (1001, "EXT1 COMMANDS", "10 = COMM"),
        (1002, "EXT2 COMMANDS", "10 = COMM"),
        (1102, "EXT1/EXT2 SEL", "a DI here = manual/computer switch"),
        (1103, "REF1 SELECT", "8 = COMM"),
        (1106, "REF2 SELECT", "8 = COMM"),
        (1105, "REF1 MAX", "the scaling anchor"),
    ]),
    ("Ramps & limits", [
        (2007, "MIN FREQ", ""),
        (2008, "MAX FREQ", ""),
        (2202, "ACCEL TIME 1", "over the full range, not to setpoint"),
        (2203, "DECEL TIME 1", "limited by DC bus without a chopper"),
        (2204, "RAMP SHAPE", "0 = linear"),
        (2005, "OVERVOLT CTRL", "silently stretches decel when on"),
    ]),
    ("Safety", [
        (3018, "COMM FAULT FUNC", "1 = FAULT. Do not disable."),
        (3019, "COMM FAULT TIME", "seconds"),
        (1601, "RUN ENABLE", ""),
        (1608, "START ENABLE 1", ""),
    ]),
    ("Diagnostics", [
        (401, "LAST FAULT", "read-only"),
        (5306, "EFB OK MESSAGES", "read-only"),
        (5307, "EFB CRC ERRORS", "read-only"),
        (5308, "EFB UART ERRORS", "read-only"),
    ]),
]

READ_ONLY = {401, 5306, 5307, 5308}


@app.route("/api/params")
def api_params():
    numbers = [n for _, rows in PARAM_GROUPS for n, _, _ in rows]
    values = ctl.read_params(numbers)
    groups = [{"name": g,
               "rows": [{"num": n, "name": nm, "note": note,
                         "value": values.get(n),
                         "readonly": n in READ_ONLY}
                        for n, nm, note in rows]}
              for g, rows in PARAM_GROUPS]
    return ok(groups=groups)


@app.route("/api/params/write", methods=["POST"])
def api_param_write():
    d = request.get_json(force=True)
    if int(d["param"]) in READ_ONLY:
        return err("that parameter is read-only")
    try:
        return ok(result=ctl.write_param(d["param"], d["value"]))
    except Exception as e:
        return err(e)


@app.route("/api/params/capability")
def api_param_capability():
    """What this transport can do, so the UI stops offering what it cannot."""
    return ok(capability=ctl.param_capability(),
              profiles=ctl.list_profiles())


@app.route("/api/params/profile/<name>")
def api_param_profile(name):
    try:
        return ok(**ctl.profile_diff(name))
    except Exception as e:
        return err(e)


@app.route("/api/params/snapshot", methods=["POST"])
def api_param_snapshot():
    d = request.get_json(force=True, silent=True) or {}
    try:
        return ok(**ctl.snapshot_params(d.get("note", "")))
    except Exception as e:
        return err(e)


@app.route("/api/params/unlock", methods=["POST"])
def api_param_unlock():
    try:
        return ok(**ctl.unlock_param_writes())
    except Exception as e:
        return err(e)


@app.route("/api/params/scan", methods=["POST"])
def api_param_scan():
    d = request.get_json(force=True, silent=True) or {}
    try:
        return ok(scan=ctl.start_param_scan(bool(d.get("all")),
                                            d.get("note", "")))
    except Exception as e:
        return err(e)


@app.route("/api/params/scan/status")
def api_param_scan_status():
    return ok(scan={k: v for k, v in (ctl.scan or {}).items() if k != "abort"}
                   if ctl.scan else None)


@app.route("/api/params/scan/abort", methods=["POST"])
def api_param_scan_abort():
    return ok(aborted=ctl.abort_param_scan())


@app.route("/api/params/snapshots")
def api_param_snapshots():
    return ok(snapshots=ctl.list_snapshots())


@app.route("/api/params/snapshot/<path:name>")
def api_param_snapshot_diff(name):
    """Live drive vs a saved snapshot — the restore preview. Read-only."""
    try:
        return ok(**ctl.snapshot_diff(name))
    except Exception as e:
        return err(e)


@app.route("/api/params/promote", methods=["POST"])
def api_param_promote():
    d = request.get_json(force=True, silent=True) or {}
    try:
        return ok(**ctl.promote_snapshot(d.get("snapshot"), d.get("name", ""),
                                         d.get("description", ""),
                                         bool(d.get("force"))))
    except Exception as e:
        return err(e)


@app.route("/api/params/apply", methods=["POST"])
def api_param_apply():
    """
    Apply a profile. DRY RUN unless commit is true.

    Snapshots the live drive first and refuses to write if that record cannot
    be saved — an un-backed-out change to a drive is not recoverable.
    """
    d = request.get_json(force=True, silent=True) or {}
    name, commit = d.get("profile"), bool(d.get("commit"))
    snap = d.get("snapshot")
    try:
        # A saved snapshot is applyable in exactly the same way a profile is
        # — that IS the restore path, and it is the reason snapshots are
        # worth taking before anyone touches the drive.
        diff = ctl.snapshot_diff(snap) if snap else ctl.profile_diff(name)
    except Exception as e:
        return err(e)

    plan = [r for r in diff["rows"]
            if r["match"] is False and not r["refused"]]
    blocked = [r for r in diff["rows"] if r["match"] is False and r["refused"]]

    if not commit:
        return ok(dry_run=True, profile=diff["profile"],
                  would_write=plan, refused=blocked)

    if not plan:
        return ok(dry_run=False, written=[], failed=[], refused=blocked,
                  note="nothing to write")
    try:
        backup = ctl.snapshot_params(
            f"before applying '{snap or name}' from the dashboard")
    except Exception as e:
        return err(f"refusing to write — could not save a backup first: {e}")

    try:
        ctl.unlock_param_writes()
    except Exception as e:
        return err(f"could not unlock writes: {e}")

    written, failed = [], []
    for r in plan:
        try:
            res = ctl.write_param(r["num"], r["target"])
            (written if res["after"] == r["target"] else failed).append(
                {**r, "before": res["before"], "after": res["after"]})
        except Exception as e:
            failed.append({**r, "error": str(e)[:120]})
    return ok(dry_run=False, profile=diff["profile"], backup=backup["file"],
              written=written, failed=failed, refused=blocked)


# ── calibration ───────────────────────────────────────────────────────────

@app.route("/api/calibration")
def api_calibration():
    cal = ctl.cfg.calibration
    if not cal:
        return ok(calibration=None, table=[])
    lim = ctl.cfg.hz_limit or cal.hz_max
    # Same rpm_per_hz trap that to_hz() and describe() were fixed for: on an
    # rpm-native reference the table was quoting 70,800 rpm on a 2435 rpm
    # machine, stepping 5 rpm at a time over a 2400 rpm range.
    rpm_native = (ctl.ref_unit.lower() == "rpm"
                  or getattr(cal, "domain", "") == "rpm")
    step = 100.0 if rpm_native else 5.0
    table, hz = [], (100.0 if rpm_native else 5.0)
    while hz <= lim + 0.01:
        table.append({"hz": round(hz, 1),
                      "rpm": round(hz) if rpm_native else
                             (round(hz * cal.rpm_per_hz) if cal.rpm_per_hz else None),
                      "mps": round(float(cal.velocity(hz)), 2),
                      "mph": round(float(cal.velocity(hz)) / 0.44704, 1)})
        hz += step
    return ok(calibration=cal.to_dict(), reference_unit=ctl.ref_unit,
              status=ctl.cfg.get("calibration_status", ""),
              notes=cal.notes, table=table)


@app.route("/api/ambient", methods=["POST"])
def api_ambient():
    d = request.get_json(force=True)
    ctl.cfg.set("temperature_c", float(d["temperature"]))
    ctl.cfg.set("pressure_pa", float(d.get("pressure", 101325))).save()
    return ok(ambient=ctl.cfg.ambient())


# ── diagnostics ───────────────────────────────────────────────────────────

@app.route("/api/selftest")
def api_selftest():
    """
    Read-only assumption check. Runs the same probes as the CLI self-test but
    without the interactive keypad question, which a web UI cannot ask
    meaningfully — so it reports the inferred 1105 value for you to confirm
    by eye instead.
    """
    checks = []
    try:
        with ctl._lock:
            sw = ctl.drive._read(3)[0]
        checks.append(("pass", "Modbus transport",
                       f"status word 0x{sw:04X}"))
    except Exception as e:
        checks.append(("fail", "Modbus transport", str(e)))
        return ok(checks=checks)

    p = ctl.read_params([2008, 1105, 5310, 5311, 1001, 1103, 3018, 3019, 1102])
    from acs550 import resolve_ref1_max
    raw = p.get(1105) or 0
    unit = getattr(ctl, "ref_unit", "Hz")
    inferred = resolve_ref1_max(raw, unit)

    checks.append(("pass" if 10 <= (p.get(2008) or 0) <= 5000 else "fail",
                   "parameter mapping (address = P − 1)",
                   f"par 2008 MAX FREQ raw = {p.get(2008)}"))
    checks.append(("warn", "REF1 MAX scaling",
                   f"raw {raw} → inferred {inferred:g} {unit}. "
                   f"CONFIRM THIS AGAINST THE KEYPAD — a wrong guess makes "
                   f"every commanded speed off by 10x, silently."))
    checks.append(("pass" if p.get(5310) == 103 else "warn",
                   "par 5310 → 40005", f"points at {p.get(5310)} (want 103)"))
    checks.append(("pass" if p.get(5311) == 104 else "warn",
                   "par 5311 → 40006", f"points at {p.get(5311)} (want 104)"))
    checks.append(("pass" if (p.get(1001) == 10 and p.get(1103) == 8) else "info",
                   "control source",
                   f"1001 = {p.get(1001)}, 1103 = {p.get(1103)} "
                   f"({'Modbus can command the fan' if p.get(1001) == 10 else 'Modbus cannot command the fan yet'})"))
    checks.append(("fail" if p.get(3018) == 0 else "pass", "comm-loss watchdog",
                   f"3018 = {p.get(3018)}, 3019 = {p.get(3019)}"
                   + (" — DISABLED. The fan would run unattended if this "
                      "process died." if p.get(3018) == 0 else "")))
    checks.append(("pass" if p.get(1102) not in (0, 1) else "info",
                   "manual fallback",
                   f"1102 = {p.get(1102)}"
                   + (" — a DI selector, so the Aerolab panel still works"
                      if p.get(1102) not in (0, 1)
                      else " — fixed. The Aerolab pot is inactive when 1001/1103 are COMM.")))

    st = ctl.last.get("status", {})
    checks.append(("warn" if not st.get("REMOTE", True) else "pass",
                   "control location",
                   "LOCAL keypad mode — ignoring the fieldbus"
                   if not st.get("REMOTE", True) else "REMOTE"))

    c = ctl.read_params([5306, 5307, 5308])
    checks.append(("warn" if (c.get(5307) or c.get(5308)) else "pass",
                   "link quality",
                   f"ok {c.get(5306)}, CRC {c.get(5307)}, UART {c.get(5308)}"))
    return ok(checks=[{"status": s, "name": n, "detail": d}
                      for s, n, d in checks])


# ── logs ──────────────────────────────────────────────────────────────────

@app.route("/api/logs")
def api_logs():
    d = Path("logs")
    if not d.exists():
        return ok(logs=[])
    files = sorted(d.glob("*.csv"), key=lambda p: p.stat().st_mtime,
                   reverse=True)[:60]
    return ok(logs=[{"name": f.name,
                     "size": f.stat().st_size,
                     "modified": time.strftime("%Y-%m-%d %H:%M",
                                               time.localtime(f.stat().st_mtime))}
                    for f in files])


@app.route("/api/logs/<name>/analyze")
def api_log_analyze(name):
    path = Path("logs") / Path(name).name        # no traversal
    if not path.exists():
        return err("not found", 404)
    try:
        res = analysis.analyze(str(path), verbose=False)
        t, cmd, meas, amps, meta = analysis.load(str(path))
        step = max(1, len(t) // 600)
        return ok(result=res, meta=meta,
                  t=[round(float(x), 2) for x in t[::step]],
                  cmd=[round(float(x), 2) for x in cmd[::step]],
                  meas=[round(float(x), 2) for x in meas[::step]])
    except Exception as e:
        return err(e)


# ── entry point ───────────────────────────────────────────────────────────

def main():
    global ctl
    p = argparse.ArgumentParser(description="wind tunnel dashboard")
    p.add_argument("--port", default="/dev/ttyVFD")
    p.add_argument("--baud", type=int, default=19200)
    p.add_argument("--parity", default="N")
    p.add_argument("--unit", type=int, default=1)
    p.add_argument("--dry-run", action="store_true",
                   help="simulated drive — no hardware")
    p.add_argument("--config", default=None,
                   help="tunnel.json. Defaults to data/tunnel.json beside the "
                        "repo, resolved from this file rather than the "
                        "working directory — launching from webapp/ used to "
                        "find no config at all, and the dashboard came up with "
                        "no calibration and no explanation.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--http-port", type=int, default=5000)
    a = p.parse_args()

    if a.host not in ("127.0.0.1", "localhost"):
        print("\n  WARNING: binding to", a.host)
        print("  This dashboard has NO AUTHENTICATION. Anyone who can reach")
        print("  this machine will be able to start a 15 HP fan.")
        print("  Prefer:  ssh -L 5000:localhost:5000 pi@this-host\n")
        if input("  Type EXPOSE to continue: ").strip() != "EXPOSE":
            sys.exit(1)

    if not a.config:
        here = Path(__file__).resolve().parent
        for cand in (here.parent / "data" / "tunnel.json",
                     here / "tunnel.json"):
            if cand.exists():
                a.config = str(cand)
                break
        else:
            a.config = "tunnel.json"
    print(f"  config: {a.config}")

    ctl = TunnelController(a.port, baud=a.baud, parity=a.parity, unit=a.unit,
                           dry_run=a.dry_run, config_path=a.config)
    if not ctl.start():
        print(f"\n  could not reach the drive: {ctl.connect_error}")
        print("  the dashboard will start anyway so you can see diagnostics\n")

    print(f"\n  dashboard → http://{a.host}:{a.http_port}")
    if a.dry_run:
        print("  DRY RUN — simulated drive, no hardware\n")
    try:
        app.run(host=a.host, port=a.http_port, threaded=True,
                debug=False, use_reloader=False)
    finally:
        ctl.shutdown()


if __name__ == "__main__":
    main()
