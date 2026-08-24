# Dashboard

```bash
cd webapp && python app.py --dry-run          # simulated, safe to click around
python app.py --port /dev/cu.usbmodem1101     # the real rig
```

→ http://127.0.0.1:5000

`--config` resolves `data/tunnel.json` from the repo, not the working
directory, so launching from here works.

---

## Tabs

| Tab | What it does |
|---|---|
| **Control** | setpoint in rpm, START/STOP, E-STOP, live trace |
| **Turbine** | interlock, live load state, **digital twin**, blade sweep runner |
| **Blades** | STL viewer paired with that rotor's measured curve |
| **Profiles** | gust and turbulence profiles, stepped sweeps |
| **Parameters** | drive parameters, configuration profiles, snapshots |
| **Commissioning** | characterize, freqresp, verify |
| **Calibration** | RPM → m/s table and its provenance |
| **Diagnostics** | comm counters, status word, preflight |
| **Logs** | run logs, plotted |

A **safety strip** sits above every tab: what is running, fan rpm, load state,
interlock, and the age of the data.

---

## Three things worth knowing before you use it

**It talks to the rig through the PMC.** The controller honours
`transport.kind` in `tunnel.json`. It used to build a raw-Modbus `ACS550`
unconditionally, which on this rig means speaking Modbus at a device that
answers ASCII lines — it could never have connected.

**The interlock is enforced on the server, not in the UI.** A greyed-out
button is not an interlock: a stale page, a second tab, or a direct POST all
bypass it. Every path that can move the fan goes through one gate,
`_authorise()`, which checks E-stop, link, running job, running sweep, load
on, and load demand above the 2 mA floor.

**Stale readings look stale.** If the stream drops, indicators grey out and a
banner appears. A frozen panel and a live one used to be indistinguishable —
which on a control display is the worst failure mode there is.

---

## Parameters tab

Asks the transport what it can do *first*. Over PMC firmware 2.x nothing can
reach a drive parameter, so no write buttons are rendered and the tab says to
flash `firmware/acs550_pmc_v3/`.

- **Compare** the live drive against a profile in `data/profiles/`
- **Dry run** before applying anything
- **Apply** snapshots the drive first and refuses to write if that backup
  cannot be saved; two confirmations, and every value is read back
- **Snapshot** the 31 known parameters, or **Scan** every parameter that
  exists on the drive
- **Restore** any saved snapshot, or **promote** one to a named profile

Group 53, 3018/3019, group 99 and groups 01–04 are refused by the PMC
firmware at any time. Set those from the keypad.

---

## Digital twin

Renders the rotor from a real STL, spinning, coloured by interlock state.

**The rotor speed is inferred, not measured** — nothing on this rig reports
rotor rpm yet, so the animation is driven from terminal voltage through an
unmeasured generator constant. It shows `no data` and freezes grey rather than
rendering a confident standstill when telemetry stops. The panel says all of
this on itself.

The animation rate is capped to avoid aliasing (an n-blade rotor looks
stationary when n·rpm/60 nears the frame rate); the printed number is always
the real inferred value.

---

## Deploying on the Pi

`windtunnel.service` — systemd unit. It sets `WorkingDirectory` to this
directory; `LOG_DIR` is anchored on the repo rather than the CWD, so logs land
in one place rather than two.

---

## Testing

```bash
cd tests && python -m pytest -q test_dashboard.py
```

Static checks on the dashboard: no duplicate ids, every selector the script
looks up exists, every `/api/` path it calls is routed, `snapshot()` still
produces the keys the UI reads, and the two specific regressions that have
already cost a day — the boot-aborting missing selector and the
canvas-resize feedback loop — cannot come back.
