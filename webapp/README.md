# Wind Tunnel Dashboard

Flask control panel for the Aerolab tunnel. URI palette, matching the
Conveyor Twin dashboard: navy strip, **Keaney blue for measured**, **gold for
commanded**. System fonts and hand-drawn canvas plots — no CDN, because a lab
bench is very likely on an isolated network.

## Run

```bash
cd webapp
python app.py --dry-run                 # simulated drive, no hardware
python app.py --port /dev/ttyVFD        # real tunnel
```

Open <http://127.0.0.1:5000>.

## Reaching it from a bench

It binds to **127.0.0.1** deliberately. Forward the port over SSH:

```bash
ssh -L 5000:localhost:5000 pi@tunnel-pi
```

`--host 0.0.0.0` exposes it with **no authentication** — anyone who can reach
the Pi could spin a 15 HP fan. There is a typed confirmation on that flag.
Lab network only, and preferably not even then.

## Tabs

| Tab | What |
|---|---|
| **Control** | Session attribution, setpoint in Hz/RPM/m/s, start/stop, live 3-minute trace |
| **Profiles** | Build gusts and turbulence, preview with a realizability check, optional feedforward, stepped sweeps |
| **Parameters** | Read and write drive parameters, grouped, with the dangerous ones marked |
| **Commissioning** | Verify the calibration, characterize τ, frequency sweep — the steps that decide what the project can promise |
| **Calibration** | The Hz→RPM→velocity table, fit quality, ambient conditions |
| **Diagnostics** | Read-only self-test, live status word |
| **Logs** | Browse runs, fit τ, overlay commanded vs measured, export a handoff bundle |

## Where the safety actually lives

**Nothing in the browser is a guard.** A tab can be closed, a laptop can
sleep, someone can open the page on their phone and forget. So enforcement is
server-side and in the drive:

- the **soft frequency limit** is applied in `controller.py` to every setpoint,
  whatever the UI sends
- **one background thread owns the drive** — RS-485 is single-master, and a
  Flask app with a port open per request would collide frames on the wire
- the **E-stop latches**; setpoints and starts are refused until it is cleared
- **control-source parameters are refused while the fan turns**
- the drive's **comm watchdog (par 3018/3019) stops the fan if this process
  dies**, which is the whole reason a browser is an acceptable place to
  command from
- the **hardwired E-stop is untouched** and remains the actual safety device

The red button on the strip issues a coast stop. It is a convenience, not a
safety device, and no substitute for the one on the wall.

## Architecture

```
  browser ──SSE──► Flask (app.py)
                      │
                      ▼
             TunnelController  ← single owner, one poll thread
                      │
                      ▼
              ACS550 / SimulatedACS550
                      │
                    RS-485
```

The controller polls at 4 Hz, which also feeds the drive's watchdog, and keeps
a 15-minute telemetry ring buffer. The browser gets one SSE stream rather than
every open tab polling on its own timer.


## Run on boot

```bash
sudo cp windtunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now windtunnel
journalctl -u windtunnel -f
```

`Restart=on-failure` rather than `always` is deliberate: a crash-looping
dashboard is a fan starting and stopping with it, and a start limit parks a
persistent fault visibly in `systemctl status` instead of letting it thrash.
It stops with SIGINT so the controller's shutdown path issues a clean ramp-down
rather than leaving the drive's watchdog to catch it.

## Session attribution

Set the operator, test-section configuration, project and notes once per
session on the Control tab. Every run's metadata sidecar carries them.

This is not bookkeeping for its own sake. "20250316_1655_1mc.csv" tells you
nothing about which blades were installed or who ran it, and that context
cannot be reconstructed afterwards — least of all by the other lab six months
later.

Simulated runs are stamped `simulated: true` and the export README says so in
capitals, so nobody ever publishes a figure made from simulator output.

## Export bundle

The Logs tab exports a zip with the CSV, the provenance sidecar, the points
table for sweeps, and a generated README explaining every column, the
calibration in force at the time, and the air conditions. A CSV handed to
another lab without that becomes unusable the moment its author moves on.


## Live wind speed

Everything used to *derive* velocity from drive frequency through a static
calibration. `velocity_source.py` lets a real sensor feed the same interface:

| Source | Use |
|---|---|
| `manual` | operator types a reading — goes stale after 2 minutes |
| `nidaq` | an NI DAQ analog channel through nidaqmx |
| `serial` | an anemometer streaming over a serial port |
| `simulated` | derived from the simulator, for dry runs and tests |

Configure in `tunnel.json`:

```json
"velocity_source": {
  "kind": "nidaq",
  "channel": "cDAQ1Mod1/ai0",
  "calibration": {"a": 115, "b": 1.5, "form": "linear"}
}
```

The Control tab shows **measured** next to **derived from Hz**, and the gap
between them. That gap is the calibration being wrong today, and it is the one
thing a static calibration cannot tell you.

### Closed-loop hold

With a healthy source, "Hold measured velocity" runs a slow PI loop that starts
from the calibration and trims against the measurement. It reports how far off
the calibration is under today's conditions — persisting across sessions means
a calibration error worth folding in; moving day to day means air density.

It refuses to run against a stale source. A loop integrating on a frozen
reading will wind the fan up until something stops it, and the reading looks
plausible the whole time.

**It withholds the calibration number if it did not converge.** An unconverged
correction is a snapshot of an approach, not a measurement of the plant, and
reporting it would bake a wrong conclusion into someone's notes.


## Pre-flight

Every profile run is checked before it starts: disk space against the run's
size, log volume, drive fault state, LOC/REM, link error counters, velocity
source health, bandwidth realizability, and duration.

**Failures block; warnings do not.** Most warnings are judgement calls the
operator is better placed to make. A blocked run offers an explicit override
rather than leaving you stuck with an error.

Disk space is on the list for a concrete reason: the player flushes every
sample so a crash at minute four does not lose the first four minutes. The
cost is that a full filesystem fails *mid-profile* rather than refusing up
front — and on a Pi with a season of logs on the SD card, that is a real
failure mode.

## Reload config

The CLI and the dashboard write the same `tunnel.json`. If someone runs
`characterize` from a terminal while the dashboard is up, the dashboard's τ is
stale — and a stale τ silently disables the bandwidth check on every profile
built afterwards. The rail has a Reload button.
