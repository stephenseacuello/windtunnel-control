# Gust Generation — What This Tunnel Can and Cannot Do

Read this before designing a test matrix. The honest summary up front:

> **Measured: τ = 0.60 ± 0.14 s, corner ≈ 0.265 Hz.**
>
> This document was written before that measurement, against an assumed τ of
> "a few seconds". **The tunnel turned out roughly five times better than it
> assumed.** Gusts of a few seconds are achievable; the original text implied
> they were not.
>
> Useful content runs to roughly **0.27 Hz**, with amplitude falling above it.
> Everything else here is about why the ceiling exists and how to get the most
> from the range below it — that reasoning is unchanged, only the number moved.
>
> Reproduce: `python src/analyze.py logs/20260820_14*_1mc.csv --summary`
> (0.80/0.50/0.60/0.50 over four unclipped 1-cosine runs — a fifth
> commanded 238% of the ramp limit and is excluded, because a clipped
> response is not first order and a τ fitted to it describes the ramp).

That constraint is not a defect of the Modbus approach. Commanding the drive
over analog, over a fieldbus card, or by hand turning the pot would all hit
the same wall, because the wall is mechanical.

---

## 1. Where the bandwidth goes

The chain from your command to the air in the test section:

```
  setpoint  →  drive ramp  →  motor torque  →  fan inertia  →  air momentum
   (µs)         (seconds)      (fast)          (seconds)       (seconds)
```

Three of those five links are slow, and they compound. The composite behaves
approximately first-order with a time constant τ of a few seconds, giving a
corner frequency

$$f_c = \frac{1}{2\pi\tau}$$

For the **measured τ = 0.60 s** that is **0.27 Hz**. Content at 3× the corner
passes at roughly a third of amplitude; content at 10× is essentially gone.

Do not hardcode either figure. `check_realizable` prints the retention for
whatever τ is in `data/tunnel.json`, which is where the measured value lives.

**The failure mode is silent.** Command a 2 Hz gust and the drive accepts it,
the fan does something, the tunnel produces a small ripple, and nothing
anywhere reports an error. You get a figure captioned "2 Hz gust" that is
really a 20%-amplitude smear with 80° of phase lag. This is why
`gusts.check_realizable()` exists and why every mode in `run.py` calls it.

---

## 2. Which link is your bottleneck

Run this first:

```bash
python run.py --port /dev/ttyVFD characterize --base 20 --step 10
```

It fits τ, reports the corner frequency, and — importantly — compares τ to the
drive's configured ramp time.

**If the ramp time dominates** (accel ≫ 3τ), your bottleneck is a parameter,
not physics, and you can buy real bandwidth by shortening it. This is the
common case out of the box: tunnels are usually commissioned with long, gentle
ramps because nobody needed anything else.

**If τ dominates**, you are against fan and air inertia, and the only remaining
levers are mechanical (see §5).

---

## 3. Shortening the ramps — carefully

> **Read section 4 first.** At the measured τ = 0.60 s the drive's ramp is not
> what limits you. Par 2202/2203 at 6.0 s allow 8.65 m/s per second, and a
> 1-cosine gust only demands more than that below about a 1-second period.
> **Bandwidth binds first almost everywhere**, so shortening the ramps buys
> very little until you are already past what the lag will pass.
>
> This section was written when τ was assumed to be a few seconds and the ramp
> looked like the obvious lever. It is kept because the decel asymmetry below
> is real, is not obvious, and will bite anyone who does decide to shorten
> them — but it is no longer where to start.


Parameters `2202` (accel) and `2203` (decel) are the time to traverse
0 → `2008` MAX FREQ, **not** the time to reach your setpoint. Misreading this
is the most common mistake with these parameters.

`ACS550.set_ramp_times(accel_s, decel_s)` writes them.

### Acceleration

Shorten in steps — try halving, run a step test, watch the motor current.
Too aggressive and you trip overcurrent as the drive fights fan inertia. The
current reading in the log is your guide: if peak current during the step
approaches the drive's 46.2 A rating, back off.

### Deceleration — the harder direction

A decelerating fan is a generator. Its kinetic energy has to go somewhere, and
without a brake chopper and resistor the only place is the DC bus, whose
voltage rises until the drive trips on overvoltage.

Two consequences:

1. **There is a hard floor on decel rate** set by how much energy the bus
   capacitance can absorb. You cannot parameter your way past it.
2. **Parameter `2005` OVERVOLT CTRL will silently stretch your ramp** to stay
   under the trip threshold. So a commanded fast decel may simply not happen,
   and — again — nothing errors.

This asymmetry matters for gust design: **the tunnel accelerates better than
it decelerates.** A 1-cosine gust is symmetric by construction, so the falling
edge is what limits you. If your logs show the rising half tracking well and
the falling half lagging, this is why, not a bug.

Frame R3 and up have `UDC+`/`UDC−` terminals for a braking unit. If symmetric
fast gusts turn out to matter for the research, a brake chopper and resistor is
the hardware answer — worth pricing before promising anything to Jeong's lab.

---

## 4. Designing profiles that work

### What is actually achievable — measured, not assumed

Two limits, and the one people worry about is not the binding one.

**Bandwidth.** A first-order tunnel retains `1/√(1+(f/f_c)²)` of a commanded
amplitude. At the **measured τ = 0.60 s**, f_c = 0.265 Hz:

| gust period | frequency | retained | |
|---:|---:|---:|---|
| 30 s | 0.033 Hz | **99%** | |
| 10 s | 0.100 Hz | **94%** | |
| 5 s | 0.200 Hz | **80%** | |
| 3 s | 0.333 Hz | **62%** | usable |
| 2 s | 0.500 Hz | 47% | marginal |
| 1 s | 1.000 Hz | 26% | no |

**Gusts down to about three seconds are real.** This document was written
against an assumed τ of 3 s, where a 10 s gust retained 47% and a 3 s gust
16% — so it advised against experiments this tunnel can actually run. If you
have been avoiding short gusts on that advice, stop.

**Slew.** Par 2202/2203 are 6.0 s over the full reference range, so the drive
can move **8.65 m/s per second**. A 1-cosine gust of amplitude A over period T
demands a peak of `πA/T`:

| period | A = 1 | A = 2 | A = 3 | A = 5 |
|---:|---:|---:|---:|---:|
| 10 s | 0.3 | 0.6 | 0.9 | 1.6 |
| 5 s | 0.6 | 1.3 | 1.9 | 3.1 |
| 3 s | 1.0 | 2.1 | 3.1 | 5.2 |
| 2 s | 1.6 | 3.1 | 4.7 | 7.9 |
| 1 s | 3.1 | 6.3 | **9.4** | **15.7** |

Only the 1-second row crosses 8.65, and only above about 2 m/s of amplitude.
**Bandwidth binds first almost everywhere** — shortening the ramps buys
you very little until you are already past what the lag will pass.

Both numbers come from `data/tunnel.json` (`tau`, `max_slew_mps_s`), so
`check_realizable` computes them for whatever profile you actually wrote
rather than leaving you to read them off a table.

### Use 1-cosine, not steps

```python
t, u = gusts.one_minus_cosine(u_mean=25, u_gust=8, gust_length=20)
```

The 1-cosine shape is the aviation certification standard (FAA/EASA CS-25,
MIL-F-8785C) for good reason: value and slope are both continuous at each end.
A step or a triangle demands infinite acceleration at the corners, so what you
actually get is the drive's ramp limit — meaning your "step gust" is really an
undocumented ramp whose rate depends on a parameter you may not have recorded.

If you want a step, use it deliberately as a system-ID input, not as a gust.

### Match the length scale to the tunnel, not to full scale

For turbulence, `length_scale` in metres sets where the spectrum sits.
Atmospheric integral scales of 100–300 m, run through Taylor's hypothesis at
tunnel velocities, put nearly all the energy far below anything you can
resolve in a reasonable run time — you will be playing a 20-minute profile to
capture two eddies.

Scale it to your model and your test-section velocity. Getting this right is
the difference between turbulence that exercises the model and a very slow
drift.

### Check before you run

```python
gusts.check_realizable(t, u, tau=3.0, max_slew_hz_s=drive_limit)
```

Warns on both slew-rate clipping and out-of-band spectral content. `run.py`
calls it automatically and prints the result above the confirmation prompt —
read it before typing `y`.

### Fix the seed

```bash
python run.py --port /dev/ttyVFD turbulence --mean 25 --sigma 2 --seed 42
```

Same seed, same realization, every time. Without this you cannot compare two
model configurations, and you cannot hand Tim a profile that his CFD run sees
identically. Record the seed in the test log.

---

## 5. If you need more bandwidth than the fan can give

The standard answer in the literature is **do not modulate the fan.** Physical
gust generators put the actuation downstream where inertia is small:

| Method | Bandwidth | Notes |
|---|---|---|
| Fan speed modulation | ~0.1–0.3 Hz | What you have. Free. Whole-flow, uniform. |
| Oscillating vanes upstream of the test section | 1–20 Hz | Standard gust-generator design. Servo-driven airfoils. Buildable in the shop. |
| Rotating slotted cylinder / chopper | 5–50 Hz | Simple, but produces wake as well as gust. |
| Active grid | 1–10 Hz | Best turbulence control, most complex to build. |

Fan modulation and vanes are complementary rather than competing: the fan sets
the mean and slow variation, vanes add the fast content. If the project grows
toward higher-frequency work, that combination is the natural path, and the
software here is already the mean-flow half of it.

Worth saying plainly to Sodhi and Jeong early: **fan modulation gets you
long-period gusts and atmospheric-scale turbulence, which is genuinely useful
for structural and wind-energy questions.** It does not get you the sharp
discrete gusts used in aeroelastic certification work. Better to scope that in
now than to discover it in three weeks.

---

## 6. Suggested commissioning order

1. `monitor` — prove comms, nothing moves
2. `jog 10` — first motion, low speed
3. `characterize` — get τ and the corner frequency. **Write these down.**
4. Shorten `2202`/`2203` if the ramp is the bottleneck, re-run `characterize`
5. `freqresp` — measure attenuation across the band you care about
6. `velocity_cal()` with a probe — get Hz ↔ m/s so profiles can be specified
   in velocity, which is what everyone else wants to talk about
7. Design gusts inside the measured band, checking each with
   `check_realizable()`
8. Run with fixed seeds, log everything, hand the logs to Jeong's DAQ side

Steps 3 and 5 produce the two numbers that determine what the rest of the
project can promise. Do them before the test matrix is written, not after.
