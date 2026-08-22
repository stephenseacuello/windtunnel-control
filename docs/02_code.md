# Code Notes — How It Works and Where to Change It

Read this before modifying the module. It covers the reasoning behind the
structure, the three or four places where a wrong assumption would cause real
problems, and the natural extension points.

---

## 1. The mental model

The ACS550's embedded fieldbus is not an API. It is a **shared block of 16-bit
registers** that both sides read and write, and the drive continuously acts on
whatever it currently finds there.

That has one consequence that shapes the whole design: **there are no commands,
only states.** You do not "send a start." You set a bit and leave it set. If
you stop transmitting entirely, the drive keeps running on the last values it
has — which is why the watchdog exists and why the keep-alive thread exists.

Four registers carry everything:

| Direction | Register | Wire addr | Contents |
|---|---|---|---|
| PC → drive | 40001 | 0 | Control word — bitfield of run/stop/reset latches |
| PC → drive | 40002 | 1 | Reference 1 — speed setpoint, normalized |
| drive → PC | 40004 | 3 | Status word — bitfield of ready/running/faulted |
| drive → PC | 40005/6 | 4/5 | Actual values — whatever params 5310/5311 point at |

Everything else in the module is plumbing around those four.

---

## 2. Module layout

```
  ┌────────────────────────────────────────────────────────────┐
  │  run.py            CLI, confirmation prompts, mode dispatch │  ← edit freely
  ├────────────────────────────────────────────────────────────┤
  │  gusts.py          profile generators, feasibility checking │  ← edit freely
  │  characterize.py   system identification                    │
  ├────────────────────────────────────────────────────────────┤
  │  player.py         real-time scheduling, logging            │  ← careful
  ├────────────────────────────────────────────────────────────┤
  │  acs550.py                                                  │
  │    start/stop/set_hz/status    drive semantics              │  ← stable
  │    _read/_write/_kw            transactions + locking       │  ← don't touch
  ├────────────────────────────────────────────────────────────┤
  │  pymodbus                      framing, CRC, serial         │
  └────────────────────────────────────────────────────────────┘
```

The split matters: the lower layers encode things that are true about this
drive and easy to get wrong. The upper layers encode things about *your
experiment* and should change as the research does.

| Module | Responsibility |
|---|---|
| `acs550.py` | Everything that knows what a control word is |
| `gusts.py` | Pure functions, no hardware. Generate and check profiles |
| `player.py` | Hold a schedule without drifting; log commanded vs measured |
| `characterize.py` | Measure τ, frequency response, velocity calibration |
| `run.py` | Argument parsing and the confirmation prompt |

`gusts.py` importing nothing from the others is deliberate — you can design and
plot profiles on any machine, no drive and no serial port. `examples/gust_demo.py`
does exactly that, and it is the right place to iterate on a test matrix.

## 3. The non-obvious decisions in acs550.py

### 3.1 Reference is read from the drive, not hardcoded

`connect()` reads parameter 1105 REF1 MAX and uses it to scale Hz into the
0–20000 counts the drive expects. It would have been one line shorter to
assume 60 Hz.

The reason not to: if someone changed 1105 to 50 Hz at some point, a hardcoded
60 would mean every commanded speed comes out 20% high, and **nothing would
report an error.** The fan just runs faster than your data says it does. That
is the worst class of bug in an instrument — silent, plausible, and it
contaminates results retroactively.

The heuristic `raw / 10.0 if raw > 200 else raw` handles ABB's tenths-of-a-Hz
storage. If you ever see commanded speeds off by exactly 10×, that line is why.

### 3.2 Reference is written before the run bit

In `start()`, `set_hz()` runs first. If you reversed it, the drive would
accelerate toward whatever value was left in 40002 from the last session
before your new setpoint landed. On a 15 HP fan that is a genuinely unpleasant
surprise for anyone standing near the tunnel.

### 3.3 The start sequence passes through 0x047E

The drive latches on the **rising edge** of the run bit. If the control word
already reads 0x047F — because the last session died without stopping — then
writing 0x047F again creates no edge, and the drive sits idle while every
write returns success. Passing through 0x047E first guarantees the transition.

If you ever find `start()` silently not starting, check the status word for
`SWC_ON_INHIB`, which is the drive telling you exactly this.

### 3.4 The keep-alive thread swallows its exceptions

This looks wrong and is deliberate. The thread exists to feed the drive's
watchdog (params 3018/3019). If the bus dies, the correct outcome is that the
watchdog **stops noticing us and trips**, stopping the fan. A keep-alive that
retried aggressively or raised into the main thread would be trying to keep a
15 HP fan running using the very subsystem that is currently failing.

The safety property is: *the drive protects itself, and the software's job is
to not get in the way of that.*

The `threading.Lock` around every transaction is not optional. RS-485 is half
duplex with one master. If the keep-alive transmits while the main thread is
mid-transaction, the frames collide and you get CRC errors that look exactly
like a wiring problem.

---

## 3b. The non-obvious decisions in player.py and gusts.py

### Deadlines are absolute, not relative

`player.play()` computes each sample's deadline as `t0 + k·dt`, not as
"sleep(dt) after the last one." With a relative sleep, every iteration would
accumulate the Modbus transaction time plus OS jitter — at 20 Hz with a 10 ms
transaction you drift about 50% long, so a "2 second gust" plays as 3 seconds
*and stretches non-uniformly through the run*. Absolute deadlines keep the
error bounded instead of accumulating.

`time.monotonic()` rather than `time.time()`, so an NTP correction mid-run
cannot warp the timebase.

### Late samples are counted, not hidden

If the loop can't keep up, the player counts it and warns at the end rather
than silently producing a stretched profile. A handful of late samples is
normal jitter; more than 5% means the link cannot sustain the update rate and
the profile you played was not the one you designed.

### check_realizable() predicts amplitude, not spectral fraction

An earlier version reported "what fraction of spectral energy is above the
corner." It over-warned badly — a perfectly good 20-second gust flagged at 39%
— because summing FFT *magnitude* weights thousands of near-empty
high-frequency bins.

The current version pushes the profile through a first-order lag and reports
the fraction of commanded peak-to-peak that survives. That is the number
someone actually needs: *this is the gust you will get.* A 20 s 1-cosine
retains 86%; a 2 s one retains 26%.

### Turbulence is band-limited and tapered before it is played

Raw spectrally-shaped noise has content to Nyquist, most of it unreachable.
Two consequences were visible in testing:

1. The drive spends the run chasing setpoints it can never reach, so the
   record is "turbulence, attenuated in ways we did not characterize."
2. Splicing a noise realization onto a steady lead section commands a step of
   order sigma in one sample — a 2.4 Hz jump in the test case, which is both a
   slew violation and a pointless transient sitting at the front of every
   record.

`band_limit()` fixes the first, `taper_ends()` fixes the second. Together they
took a von Kármán profile from 47% amplitude retention with 48 Hz/s peak slew
down to 88% retention at 1.2 Hz/s. `run.py` applies both by default whenever
`--tau` is supplied.

---

## 4. Where you'll want to extend it

### Add a DAQ trigger

The marked block in `do_sweep()`. Log both the commanded setpoint and the
measured frequency — they diverge slightly under aerodynamic load, and the
measured one is what belongs in the dataset.

```python
with nidaqmx.Task() as task:
    task.ai_channels.add_ai_voltage_chan("cDAQ1Mod1/ai0")
    task.timing.cfg_samp_clk_timing(rate=1000, samps_per_chan=dwell * 1000)
    data = task.read(number_of_samples_per_channel=int(dwell * 1000))
writer.writerow([sp, f, i, np.mean(data), np.std(data)])
```

### Close the loop on velocity instead of frequency

Right now you command Hz, which is only proportional to tunnel velocity through
the fan curve and whatever the tunnel is doing. If you have a pitot or hot wire
reading, wrap `set_hz` in a slow outer PI loop targeting velocity:

```python
def hold_velocity(drive, target_mps, read_velocity, tol=0.05, timeout=120):
    hz = drive._ref / REF_FULL_SCALE * drive.ref1_max_hz
    t0 = time.time()
    while time.time() - t0 < timeout:
        err = target_mps - read_velocity()
        if abs(err) < tol:
            return hz
        hz = drive.set_hz(hz + 0.4 * err)   # gain needs tuning on the real rig
        time.sleep(3)                       # slow — the tunnel is the lag
    raise DriveError("velocity setpoint not reached")
```

Keep the gain low and the loop slow. The dominant time constant is the tunnel
settling, not the drive.

### Wait for AT_SETPOINT instead of a fixed settle

Status word bit 8 tells you the drive has reached its reference. That is
electrical settling, not aerodynamic, so use it as a *floor* on the wait rather
than a replacement for it:

```python
while not drive.status()["AT_SETPOINT"]:
    time.sleep(0.2)
time.sleep(settle)   # then wait for the flow
```

### Log continuously rather than at points

Run a second thread polling `actuals()` into a CSV at 2–5 Hz for the whole
session. Cheap, and it means when something odd shows up in the data you have
the drive's own record of what the fan was doing.

### Add an interlock check

If you wire a limit switch, door sensor, or "test section closed" contact into
a spare digital input, you can read the DI states over Modbus (they map to
Modbus discrete inputs beginning at 33, DI1 = input 33) and refuse to start
unless the interlock is made. This is a software convenience layer, **not** a
safety function — a real interlock belongs in the hardwired chain.

---

## 5. Things to be careful with

**`write_param()` is persistent.** It is the same as editing on the keypad. It
survives power cycles and there is no undo. If you script parameter changes,
read and log the old value first.

**Ramp times are not yours.** `stop()` ramps over parameter 2203. A sweep that
steps down faster than the decel time will just track the ramp. If your steps
look sluggish, that is 2202/2203, not the script.

**Don't loop on `reset_fault()`.** A drive that faults repeatedly is protecting
itself from something real. Read parameter 0401 and find out what.

**The E-stop is not in this file and should never be.** Nothing in software is
part of the safety chain.

---

## 6. Debugging order when it won't talk

1. `--monitor` — does anything come back at all?
2. Keypad params 5306 / 5307 / 5308: OK messages, CRC errors, UART errors.
   Climbing OK means the wire is fine and the problem is upstream. Climbing
   CRC means noise or termination. Climbing UART means parity or baud. All
   frozen at zero means nothing is physically arriving.
3. Swap X1-29 and X1-30. A/B labeling is inconsistent across adapter vendors
   and this is the single most common cause.
4. Confirm you power-cycled the drive after changing 9802 or group 53.
5. Confirm `--unit` matches parameter 5302.


---

## The load-side modules

| Module | Responsibility |
|---|---|
| `chroma_load.py` | SCPI over VISA/serial/USB-TMC/TCP, plus `TurbineInterlock` |
| `probe_load.py` | find the instrument; verify every command it will be sent |
| `peak_finder.py` | the measurement — ramp, detect the power roll-off, refine the peak |
| `load_ramp.py` | one wind speed, driven by hand; also the bench-proof ladder |
| `blade_sweep.py` | the campaign — fourteen wind speeds, driving the fan |
| `load_sim.py` | a modelled rotor and a modelled Chroma, same interfaces |
| `turbine.py` | Cp(λ) sweep and stall guard — needs rotor RPM, not yet wired |
| `merge_load_facts.py` | restore load-side config after `tunnel.json` is replaced |

### Three decisions worth knowing about

**The ramp stops on the power roll-off, not at stall.** Ramping to the rotor's
stall threshold means driving it to let go at every wind speed. Stopping once
power has fallen to 80% of a maximum you have actually observed brackets the
peak, never approaches stall, never reaches the load's cut-out voltage, and is
about a third shorter.

**The peak is found by fitting, not by `argmax`.** The top of P(I) is flat.
`argmax` over a plateau jitters in position and is biased high in value, and
the bias grows with sample count — so a blade that got more dwells would look
better than one that got fewer. `PeakResult.refine()` fits a parabola through
the points around the maximum. Both numbers are written to the CSV; comparisons
use the fitted one.

**Nothing in the load path ever commands zero amps to a spinning rotor.**
`find_peak` raises rather than accept `floor_amps=0`, and recovers from a stall
to the floor rather than to zero. `blade_sweep` is the one exception, because
the protocol calls for unloading between wind speeds — and it says so in its
docstring rather than doing it quietly.

### The scaling rule, and why it is in the fingerprint

Peak current goes as v². A fixed ladder step gives ~35 dwells to the peak at
1800 rpm and three at 500, and three points either side of a maximum overshoots
into stall before a roll-off can be confirmed. The `v2` scaling keeps the
chosen step at the top of the range and scales it down below.

That rule changes what a curve means, so it is hashed into the protocol
fingerprint alongside step size, dwell, cut-out voltage, range and floor. Runs
whose fingerprints differ are not comparable, and the fingerprint is the only
thing that makes that visible after the fact.
