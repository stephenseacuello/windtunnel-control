"""
player.py — stream a time-varying setpoint to the drive in real time.

Turns a profile from gusts.py into an actual gust. Four jobs: hold a schedule
without drifting, write setpoints on that schedule, notice when the drive stops
cooperating, and leave behind a record you can publish from.

────────────────────────────────────────────────────────────────────────────
WHY NOT JUST sleep(dt) IN A LOOP
────────────────────────────────────────────────────────────────────────────
Every iteration would accumulate the Modbus transaction time plus OS jitter.
At 20 Hz with a 10 ms transaction you drift ~50% long, so a "2 second gust"
plays as 3 seconds — and stretches non-uniformly through the run, because the
error compounds.

Each deadline is computed from the absolute start (t0 + k·dt) instead, so
errors stay bounded. `time.monotonic()` rather than `time.time()`, so an NTP
correction mid-run cannot warp the timebase.

────────────────────────────────────────────────────────────────────────────
WHAT THE LOG IS FOR
────────────────────────────────────────────────────────────────────────────
Commanded and measured will not match during a gust. That gap IS the tunnel's
dynamic response — it is data, not error. Log both every sample and you can
extract a transfer function from any run, without a dedicated identification
experiment. `analyze.py` does exactly that.
"""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime
from pathlib import Path

from acs550 import ACS550, DriveError


class ProfileAborted(RuntimeError):
    """Raised when a run is cut short — fault, limit violation, or lost comms."""


class ProfilePlayer:
    """
    Plays a (t, u) profile to the drive and logs the result.

    Args:
        drive:        a connected ACS550
        log_path:     CSV destination. None disables logging.
        read_every:   read actuals every Nth sample. Each read is a full Modbus
                      round trip, so reading every sample roughly halves the
                      achievable update rate. 2 is a fair compromise at 20 Hz.
        check_every:  poll the status word every Nth sample to catch faults
                      mid-run. Costs one transaction each time. At 20 Hz,
                      every 20 samples is a 1 s detection latency, which is
                      well inside the drive's own 3 s watchdog.
        hz_limit:     hard ceiling. A typo in an amplitude should not be able
                      to command full speed at a model rated for half of it.
        metadata:     dict written alongside the CSV as a sidecar JSON. Put the
                      profile parameters, seed, and calibration in here — six
                      months from now the CSV alone will not tell you what the
                      run was.
    """

    def __init__(self, drive: ACS550, log_path=None, read_every=2,
                 check_every=20, hz_limit=None, metadata=None,
                 velocity_source=None):
        self.drive = drive
        self.log_path = Path(log_path) if log_path else None
        self.read_every = max(1, int(read_every))
        self.check_every = max(0, int(check_every))
        self.hz_limit = hz_limit
        self.metadata = dict(metadata or {})

        # Optional live wind speed. Without it a run records what the *drive*
        # did, which is only a proxy for what the air did. With it the log is
        # about the tunnel rather than about the motor — and that is the
        # difference between a dataset you can publish velocities from and one
        # you have to caveat.
        self.velocity_source = velocity_source

        self.rows = []
        self.late_samples = 0
        self.max_lateness = 0.0
        self.aborted_reason = None

        self._fh = None
        self._writer = None

    # ── streaming log ────────────────────────────────────────────────────

    def _open_log(self):
        """
        Open the CSV and write the header immediately.

        Streaming rather than buffering to the end: a turbulence run is minutes
        long, and losing all of it because the process died at minute four is
        an avoidable way to waste a test session. Each row is flushed, so
        whatever completed is on disk even after a hard kill.
        """
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.log_path, "w", newline="")
        self._writer = csv.writer(self._fh)
        cols = ["t_s", "cmd_hz", "meas_hz", "meas_a"]
        if self.velocity_source is not None:
            cols.append("v_meas")
        self._writer.writerow(cols)
        self._fh.flush()

    def _log_row(self, row):
        self.rows.append(row)
        if self._writer:
            out = [f"{row[0]:.4f}", f"{row[1]:.3f}", f"{row[2]:.2f}",
                   f"{row[3]:.2f}"]
            if self.velocity_source is not None:
                v = row[4] if len(row) > 4 else None
                out.append("" if v is None else f"{v:.3f}")
            self._writer.writerow(out)
            self._fh.flush()

    def _close_log(self, summary=None):
        if self._fh:
            self._fh.close()
            self._fh = self._writer = None
        if self.log_path and (self.metadata or summary):
            side = self.log_path.with_suffix(".json")
            payload = dict(self.metadata)
            payload["written"] = datetime.now().isoformat(timespec="seconds")
            if summary:
                payload["run"] = summary
            side.write_text(json.dumps(payload, indent=2, default=str))

    # ── the loop ─────────────────────────────────────────────────────────

    def play(self, t, u, dt=None, on_sample=None, return_to=None,
             stop_on_abort=True):
        """
        Stream profile (t, u) to the drive. u is in Hz.

        Args:
            on_sample:     callback(k, t_elapsed, cmd_hz, meas_hz, meas_a).
                           Runs inside the real-time loop, so keep it fast —
                           anything slow here eats the update rate directly.
            return_to:     Hz to hold after the profile. None leaves the drive
                           at the final value.
            stop_on_abort: ramp the fan down if the run is cut short.

        Raises ProfileAborted if the drive faults, comms drop, or the profile
        exceeds hz_limit. Whatever was captured before the abort is already on
        disk.
        """
        dt = float(dt if dt is not None else (t[1] - t[0]))
        n = len(u)

        # Pre-flight: refuse rather than clip. A profile that exceeds the limit
        # is a design error, and silently flattening its peaks would produce a
        # run that looks fine and is not the experiment anyone intended.
        if self.hz_limit is not None:
            peak = float(max(u))
            if peak > self.hz_limit:
                raise ProfileAborted(
                    f"profile peaks at {peak:.1f} Hz, above the "
                    f"{self.hz_limit:.1f} Hz limit. Lower the amplitude or "
                    f"raise the limit deliberately.")

        st = self.drive.status()

        # If someone pressed LOC/REM on the keypad, the drive takes its
        # commands from the panel and silently ignores the fieldbus. Writes
        # still succeed. Without this check a profile would "run" for five
        # minutes against a drive that was never listening, and the log would
        # look complete.
        if not st.get("REMOTE", True):
            raise ProfileAborted(
                "drive is in LOCAL keypad mode (status bit 9 REMOTE is clear). "
                "It is ignoring the fieldbus. Press LOC/REM on the keypad to "
                "return it to remote.")

        if not st["RDY_REF"]:
            raise ProfileAborted(
                "drive is not running — start() it and let it reach the "
                "baseline first, or the acceleration ramp lands inside your "
                "gust")

        self._open_log()
        f_meas = i_meas = float("nan")
        t0 = time.monotonic()
        summary = None

        try:
            for k in range(n):
                deadline = t0 + k * dt

                slack = deadline - time.monotonic()
                if slack > 0:
                    time.sleep(slack)
                else:
                    self.late_samples += 1
                    self.max_lateness = max(self.max_lateness, -slack)

                try:
                    self.drive.set_hz_fast(float(u[k]))
                except DriveError as e:
                    # Comms died mid-profile. Do not soldier on writing into
                    # the void — the rest of the "profile" would be fiction and
                    # the log would imply it ran.
                    raise ProfileAborted(f"lost comms at sample {k}: {e}")

                if k % self.read_every == 0:
                    try:
                        f_meas, i_meas = self.drive.actuals()
                    except DriveError:
                        f_meas = i_meas = float("nan")

                # Catch a trip mid-run. Without this the loop keeps commanding
                # a stopped drive for the remainder of a multi-minute profile
                # and logs a record that looks complete but is not.
                if self.check_every and k % self.check_every == 0 and k > 0:
                    try:
                        st = self.drive.status()
                        if st["TRIPPED"]:
                            raise ProfileAborted(
                                f"drive faulted at sample {k} "
                                f"(t={k * dt:.1f} s, par 0401 = "
                                f"{self.drive.last_fault()})")
                    except DriveError:
                        pass          # transient read failure, keep going

                v_meas = None
                if self.velocity_source is not None and k % self.read_every == 0:
                    # read_or_none, never read(): a stale sensor must leave a
                    # blank in the record rather than abort a good run or,
                    # worse, silently repeat its last value forever.
                    v_meas = self.velocity_source.read_or_none()
                    self._last_v = v_meas
                elif self.velocity_source is not None:
                    v_meas = getattr(self, "_last_v", None)

                elapsed = time.monotonic() - t0
                self._log_row((elapsed, float(u[k]), f_meas, i_meas, v_meas))

                if on_sample is not None:
                    on_sample(k, elapsed, float(u[k]), f_meas, i_meas)

            if return_to is not None:
                self.drive.set_hz(return_to)

            summary = self._summary(n, dt, t0, complete=True)
            return summary

        except ProfileAborted as e:
            self.aborted_reason = str(e)
            summary = self._summary(n, dt, t0, complete=False)
            print(f"  ABORTED  {e}")
            if stop_on_abort:
                try:
                    self.drive.stop()
                    print("  stop command sent")
                except DriveError:
                    print("  could not send stop — the drive's own watchdog "
                          "will trip within par 3019 seconds")
            raise

        finally:
            self._close_log(summary)

    def _summary(self, n, dt, t0, complete):
        vals = [r[4] for r in self.rows
                if len(r) > 4 and r[4] is not None]
        s = {"velocity_logged": len(vals),
             "velocity_coverage": (len(vals) / max(len(self.rows), 1)),
             "samples_planned": n,
             "samples_played": len(self.rows),
             "complete": complete,
             "requested_duration": n * dt,
             "actual_duration": time.monotonic() - t0,
             "late_samples": self.late_samples,
             "max_lateness_s": round(self.max_lateness, 4),
             "update_rate_hz": round(1.0 / dt, 3)}
        if self.aborted_reason:
            s["aborted_reason"] = self.aborted_reason

        # A few late samples is normal jitter. Many means the link cannot
        # sustain the rate and the profile played was not the one designed.
        if complete and self.late_samples > 0.05 * n:
            print(f"  WARNING  {self.late_samples}/{n} samples late "
                  f"(worst {self.max_lateness * 1000:.0f} ms). Raise par 5303 "
                  f"to 38.4 kbaud, increase dt, or raise read_every.")
        return s

    def columns(self):
        """
        Rows as float arrays: (t, cmd_hz, meas_hz, amps, v_meas).

        Rows carry `None` in the velocity slot when there is no source, which
        makes a naive np.array(rows) object-dtype — and then isnan, mean and
        everything else downstream fails on it. Coercing here means callers
        never have to think about it.
        """
        import numpy as _np
        if not self.rows:
            e = _np.array([])
            return e, e, e, e, e

        def col(i):
            return _np.array([
                (r[i] if len(r) > i and r[i] is not None else _np.nan)
                for r in self.rows], dtype=float)

        return col(0), col(1), col(2), col(3), col(4)

    def reset(self):
        self.rows.clear()
        self.late_samples = 0
        self.max_lateness = 0.0
        self.aborted_reason = None


def play_profile(drive, t, u, baseline_hz, settle=20.0, log_path=None,
                 read_every=2, hz_limit=None, metadata=None, on_sample=None,
                 velocity_source=None):
    """
    Bring the tunnel to the profile's starting value, let the flow settle,
    play, then return to baseline.

    `settle` is aerodynamic, not electrical. The drive reaches its setpoint in
    seconds; the flow field in the test section takes longer. Measure it once
    with characterize.py and use the real number rather than a guess.
    """
    start_hz = float(u[0])
    # Keepalive first. Over the PMC transport this is what feeds the PMC's
    # host watchdog, and the settle below is far longer than that timeout.
    drive.start_keepalive()
    print(f"  bringing tunnel to {start_hz:g}")
    drive.start(start_hz)

    print(f"  settling {settle:.0f} s")
    time.sleep(settle)

    player = ProfilePlayer(drive, log_path=log_path, read_every=read_every,
                           hz_limit=hz_limit, metadata=metadata,
                           velocity_source=velocity_source)
    print(f"  playing {len(u)} samples")
    summary = player.play(t, u, on_sample=on_sample, return_to=baseline_hz)

    print(f"  done in {summary['actual_duration']:.1f} s "
          f"(requested {summary['requested_duration']:.1f} s)")
    if log_path:
        print(f"  log  {log_path}")
        print(f"  meta {Path(log_path).with_suffix('.json')}")
    return summary, player
