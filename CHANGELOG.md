# Changelog

## v4.1 — 2026-08-22

Dashboard hardening. Three audit rounds by five independent reviewers each —
three software engineers (frontend, backend/concurrency, safety-critical
control) and two research professors (experimental methods, HCI for
instrument displays) — with every finding adversarially refuted before being
accepted. Round 1: 40 raised, 29 confirmed. Round 2: 40 raised, 34 confirmed,
**13 of them regressions from the round-1 fixes**. Round 3 did not run — the
agents failed on a billing limit, so the remaining round-2 tail was worked
through by hand instead.

### The one that mattered most

`$('#cfg-reload')` referenced a button that has never existed in the template.
`null.onclick = …` threw, and in a classic non-deferred script that aborts the
**entire file** — so `connectStream()` never ran. The dashboard rendered its
static zeros indefinitely and looked calm and connected, while START and
E-STOP, bound earlier in the file, still commanded a 15 HP fan. `$()` now
returns an inert Proxy for missing elements and surfaces misses, plus any
duplicate ids, as a banner.

### Safety

- **E-STOP now stops a blade sweep.** The worker consulted nothing and called
  `drive.start()` at the next wind point, restarting the fan seconds after
  somebody hit the button. Four of five reviewers found this independently.
- **"Ramp stop" now stops.** Same defect via `stop()`: the sweep saw
  `running == False` and restarted the fan. `_halt_all()` latches every
  running activity; both stop paths call it.
- **One authority.** `_authorise()` holds a lock across check-and-claim and
  gates E-stop, link, running job, running sweep, load state and load demand.
  Load-before-wind was enforced on 2 of 8 fan-start paths; it is now on all of
  them, including characterize, freqresp, verify-hold and the stepped sweep.
- **A 2 mA load floor.** "Load ON" armed at the 0.000 A default — on,
  reporting *"safe to wind up"*, and electrically an open circuit. The sweep
  also commanded 0 A between wind points, leaving the rotor open-circuit for
  2+ s at each of 14 points, each faster than the last.
- **The interlock uses a measurement.** `is_on` is an optimistic Python
  attribute never read back from the instrument; a spinning rotor with stale
  or sub-floor current now reads danger, not "safe".
- **A drive fault latches E-stop on the PMC rig.** `last_fault()` reads a
  parameter the PMC cannot serve; it raised, was caught as "lost comms", and
  the latch was never set. Latch first, read the code opportunistically.
- **`clear_estop()` refuses** while a worker is still unwinding.
- **A stopped characterize no longer writes its tau** over a good calibration.

### Data integrity

- **Dashboard sweeps persist**, incrementally, with a protocol fingerprint —
  10–30 minutes of tunnel time per blade previously wrote nothing to disk.
  The fingerprint carries `via=dashboard` because the ladder and settle really
  do differ from the CLI's, so the two are deliberately not comparable.
- **`apply_verify()` refuses on an rpm-native calibration.** It divided an
  already-per-rpm slope by a vestigial `rpm_per_hz`, flipped `domain` to
  `"hz"`, saved that over `tunnel.json` and stamped it "VERIFIED". A backup is
  written before any calibration change.
- **rpm conversions.** Asking for 1800 rpm commanded **61 rpm**; the confirm
  dialog before starting a 15 HP fan quoted 70,800 rpm on a 2435 rpm machine.
  Fixed in `to_hz()`, `describe()` and `/api/calibration`.
- **Duplicate ids** `sw-step`/`sw-dwell` — the Profiles stepped sweep silently
  submitted the Turbine tab's values.
- **One log directory.** `LOG_DIR` was relative to the process CWD, and the
  service runs from `webapp/`, so profiles and sweeps went to a different tree
  from the one the Blades tab reads.

### Interface

- **A persistent safety strip on every tab** — what is running, fan rpm, load
  state, interlock, data age. The most dangerous state on the rig was
  previously visible only inside one tab.
- **Stale readings look stale.** A dropped stream froze every indicator at its
  last value with nothing to say so.
- **Refusals survive.** A safety refusal was erased ~250 ms later by the next
  telemetry frame; refusals now go to a node the render loop never touches.
- **Plots no longer blank on one NaN.** The default manual velocity source
  emits `None` every frame until an operator types a reading, which made the
  Control tab's primary plot a white box with axis numbers and no curves.

### Added earlier in this cycle

- Turbine tab: interlock, live load state, blade sweep runner, live P–I ramp
  and accumulating blade curve.
- Blades tab: dependency-free STL viewer (binary + ASCII, 60k-triangle display
  cap) paired with that rotor's measured curve, joined by name.
- `blades/` library with optional per-rotor JSON metadata.
- PMC transport support — the dashboard built a raw-Modbus `ACS550`
  unconditionally and could never have connected to this rig.
- `--config` resolved from the repo, not the CWD.
- The simulator's `max_freq` still defaulted to 60, so in the rpm domain every
  dry run ramped at 6 rpm/s — a fortieth of the real rate.

**93 tests passing.**

## v4.0 — 2026-08-21

The rig works end to end. The PMC drives the ACS550, the ACS550 turns the fan,
the Chroma sinks current, and one command characterises a rotor across the whole
wind range unattended.

### The drive commands rpm, not Hz

Parameter 1105 REF1 MAX is 2435 rpm, corroborated by 2002 and 9908. Every
document, table and formula moved to the speed domain:

- **`v (m/s) = 0.02132 × RPM − 0.424`**, soft limit 2400 rpm
- `README.md`, `FIELD_CARD.md`, `PLAYBOOK.md`, `TODO.md`,
  `docs/04_troubleshooting.md` updated
- `tests/test_docs.py` migrated with them — it now rejects a document that
  calls the 2400 rpm limit a frequency

Config keys still carrying `hz` are legacy; the values are rpm.

### τ measured, and better than feared

**0.63 ± 0.12 s** across five 1-cosine gust runs — corner ≈ 0.25 Hz. Planning
had assumed τ ≈ 3 s and a 0.05 Hz corner. Gusts of a few seconds are achievable
where they previously looked impossible. Measure τ from a gust, not a step: a
step saturates the drive's ramp generator and what you fit is parameter 2202.

### Added — the load and turbine half

- **`peak_finder.py`** — ramps constant current until electrical power falls to
  a chosen fraction of its peak. Locates the peak by parabolic fit rather than
  `argmax`, which over a flat maximum jitters in position and is biased high in
  value with a bias that grows with sample count. Distinguishes a rotor stall
  from the load's cut-out, and reports a censored result as a lower bound.
- **`blade_sweep.py`** — the campaign. Fourteen wind speeds, 500 → 1800 rpm,
  driving the fan itself through the PMC, inside `TurbineInterlock` end to end.
  ~10 minutes per blade.
- **`load_ramp.py`** — one wind speed by hand, plus `--wait-for-source` so the
  load can be on before the wind comes up.
- **`load_sim.py`** — a modelled rotor and Chroma presenting the real
  interfaces, so the measurement logic is testable with no rig.
- **`merge_load_facts.py`** and `data/load_facts.json` — load-side measurements
  kept out of the shared `tunnel.json`, which has been replaced wholesale twice.
- **`tests/test_peak_finder.py`** — 16 tests.

### Fixed

- **`VisaTransport` could not open the resource `probe_load.py` told you to
  record.** The Chroma pads its serial with NULs; the probe strips them for
  JSON and the stripped string then matched no device. Now resolved by
  NUL-stripped match with a serial-number fallback.
- **`protection()` sent commands this firmware rejects.** Every `:PROT:`
  mnemonic returns `3,"Command Error"` on fw 2.01 — there is no programmable
  OVP/OCP/OPP on this model. It now reports what landed instead of raising.
- **Load ranges were assumed and wrong.** Measured off the instrument:
  CC 2 / 6 / 60 A, CR 250 / 1250 / 2500 Ω. The low current range is 2 A, not a
  tenth of anything. Out-of-range is refused, not clamped — but the setpoint
  then keeps its previous value, so setpoints are read back.
- **`build_transport` crashed on the real config**, which carries more keys
  than any transport constructor accepts.
- **The sweep stopped the fan by not talking to it.** A load ramp is tens of
  seconds of silence against the PMC's 5000 ms host watchdog. A `DriveWatch`
  thread now ticks it and logs actual fan rpm and motor current per dwell.
- **A settle that could not tell "settled" from "not started".** 0.000 V is
  perfectly stable; the first real sweep recorded an accelerating fan as a
  finished one. Settling now waits on drive speed first, then voltage.
- **Peak mode switched the load off** to take an open-circuit reading — the
  runaway condition on a rig where the load is wired to the turbine. Nothing in
  peak mode switches the load off any more.
- **`test_disk_check_fails_when_run_would_not_fit`** assumed no machine has
  40 GB free. Now derived from actual free space.

### Documentation

- **`TRAINING.md`** — new. Onboarding from four safety rules to a first blade
  run, first hour with no hardware.
- **`docs/07_blade_campaign.md`** — new. The user guide: running a sweep,
  reading `limited_by`, and why runs with different protocol fingerprints are
  not comparable.
- `docs/06_chroma.md` — what the instrument actually said, measured not
  assumed.
- `docs/01_architecture.md`, `docs/02_code.md` — the load half.

**93 tests, all passing.** `scipy` is needed for five of them.

### Reference result

Blade `v2_Ra20` (PETG, 0.2 mm, Ra 20), protocol `94bed28333f7`, 14/14 clean:
**P ∝ v^3.754**, R² = 0.998 over 10.2–38.0 m/s, peaking at 3.72 W at 38 m/s.
Independent single points reproduce it to 0.2–0.3%.

The exponent is the finding — constant Cp would give 3.0. Cp is still climbing
with Reynolds at 38 m/s, so a blade ranked at 10 m/s may not rank the same at
38.

## v3.2 — 2026-08-13

### Added
- **`tests/test_docs.py`** — 13 tests that make the documentation falsifiable:
  every documented command must parse, every CLI mode must appear somewhere,
  wind speed tables must match the calibration, cross-references must resolve.

### Fixed
- **`calibrate` was a working CLI mode documented nowhere.** Found by the new
  tests. Now phase 12B of the playbook, with the warning about using loaded
  rather than synchronous nameplate speed.
- Parameter `9902` APPLIC MACRO is in the playbook's "record before you change
  anything" list but was missing from the dashboard's parameter editor — you
  had to walk to the keypad for it.

---

## v3.1 — 2026-08-13

### Fixed
- **`examples/daq_integration.py` was stale.** It predated `velocity_source.py`
  and hand-rolled what that module now does properly — a misleading example is
  worse than none. Rewritten around the three integration patterns, with a
  working timestamp-join helper and a `TunnelClient` that can be handed to
  Jeong's lab as-is.

### Documentation
- Docstrings added to every public entry point whose behaviour has a
  consequence you could not guess from the name — `go`, `stop`, `clear_estop`,
  `start_profile`, `snapshot`, `analyze`, `fit_all`, and the CLI modes that
  move the fan (now labelled as such).
- Remaining gaps are deliberate: Flask route handlers are one-line wrappers,
  and simulator methods mirror a documented ACS550 surface. Chasing 100% would
  add noise, not information.
- `examples/README.md` — which integration pattern to pick and why.

---

## v3 — 2026-08-13

Documentation consolidation, plus bundling the source material the calibration
was derived from.

### Documentation
- **Removed two duplicate documents.** Four files described how to wire the
  drive and six described how to start; `QUICKSTART.md` and
  `docs/01_wiring_checklist.md` were merged into `PLAYBOOK.md`, which is now
  the single field procedure.
- `README.md` rewritten as an orientation map — "I want to X, read Y" — rather
  than a fourth competing tutorial.
- **`FIELD_CARD.md`** — one printable page for use at the tunnel.
- **`docs/01_architecture.md`** + `diagrams/architecture.svg` — layers, the two
  data paths, and which layer each safety property lives at.
- **`docs/04_troubleshooting.md`** — organised by symptom, because at the
  tunnel you know the symptom and not the cause.
- **`diagrams/commissioning_flow.svg`** — the phase order, the gate at phase
  10, and the branch when the bus is silent.
- `reference/` — nameplate photos, the March 2 report and the March 16 raw
  capture, with a provenance index recording what each established and what
  re-analysis corrected.

### Added
- `scripts/rpm.py` — standalone 130-line RPM console, no package dependency.

---

## v2.5 — 2026-08-13

### Added
- `velocity_source.py` — live wind speed with manual, NI DAQ, serial and
  simulated backends; averaging and staleness are declared properties.
- `preflight.py` — disk, link, fault, velocity, bandwidth and duration checks
  before a long run. Failures block; warnings do not.
- `fit_sensor.py` — compares linear / sqrt / King calibration forms by AIC, and
  refuses data whose columns are not independent.
- `archive_logs.py` — moves runs as complete sets; refuses to delete anything
  missing its provenance sidecar.
- Runs log measured velocity (`v_meas`) alongside commanded and measured Hz.
- Session attribution: operator, configuration, project, notes — stamped into
  every run.
- Export bundle: CSV + sidecar + points table + generated README.
- Stepped sweep and commissioning (verify / characterize / freqresp) in the
  dashboard; CLI parity for the velocity source and closed-loop hold.
- `windtunnel.service` for systemd.

### Fixed
- **`suggest_gains` used the wrong time constant for the integral term.**
  IMC-PI sets Ti to the *plant* τ; the code used the closed-loop τ, making `ki`
  ~3× too small. The loop converged so slowly that a 160 s hold ended
  mid-approach and reported the approach as a calibration error. Now converges
  in 30 s and recovers an injected 13.6% error to +13.1%.
- **`ManualSource` never went stale**, which was the entire point of the class —
  its poll loop re-read the stored value and refreshed its own timestamp.
  Staleness is now measured from submission.
- **Unconverged closed-loop runs withheld the calibration number.** An
  unconverged correction is a snapshot of an approach, not a measurement.
- **Simulator dead-time model.** A pop-based delay queue assumed `_advance()`
  ran at a fine regular interval; under sparse polling the simulated flow never
  caught up, reporting 0 Hz after a full settle. Now interpolates by timestamp.
- Feedforward preview returned HTTP 400 — a numpy array was being placed in the
  diagnostics dict, which is serialized into every run's metadata sidecar.

---

## v2 — 2026-08-12

Rebuilt as a package around gust simulation, after Dr. Sodhi's note
("We can generate wind gusts!") brought Jeong lab in on acquisition.

### Added
- `gusts.py` — 1-cosine discrete gusts (FAA/EASA CS-25 shape), steps, ramps,
  sinusoids, chirps, von Kármán and Dryden turbulence, CSV replay.
- `player.py` — drift-free real-time streaming with CSV logging of commanded vs
  measured.
- `characterize.py` — step response (τ), frequency response, velocity
  calibration.
- `feedforward.py` — pre-compensation to recover usable bandwidth.
- `simulator.py`, `selftest.py`, `analyze.py`, `daq_survey.py`.
- Flask dashboard in the URI palette.
- `docs/03_gusts.md` — achievable bandwidth and why it is what it is.
- `setup_pi.sh`, including the ModemManager trap.
- 57-test suite against the simulator.

### Changed
- Host is a Raspberry Pi at the tunnel rather than a laptop.
- Wiring simplified to the FTDI cable landing directly on X1 — no Belden, no
  shield drain, X1-28/32 unused.

### Fixed
- **Cover removal procedure was wrong.** It is a captive screw at the top,
  pulled from near the top — not screws along the bottom edge. Corrected from
  ABB quick start 3AUA0000001558.
- **The FTDI cable was listed as isolated. It is not.** Acceptable at 6 ft to a
  Pi; documented rather than hidden.
- **Feasibility checker over-warned.** Replaced a spectral-fraction heuristic
  with a first-order lag prediction of retained amplitude.
- **Turbulence commanded a step at onset** — splicing a noise realization onto a
  steady lead produced a 2.4 Hz jump in one sample. Added tapering and
  band-limiting: von Kármán went from 47% retention at 48 Hz/s peak slew to 88%
  at 1.2 Hz/s.
- The ACS550 auto-starts at power-up if a run command is already present —
  added to the checklist.
