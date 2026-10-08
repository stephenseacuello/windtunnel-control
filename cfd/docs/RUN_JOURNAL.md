# CFD run journal

One entry per working session: what ran, how long it took, what went wrong. Newest first.
Numbers come from the case records (`cfd/*/results/records/<case>/summary.json`,
`log_excerpt.txt`) or the solver logs; label anything else as calculated, assumed or estimated.

## Template

```markdown
## YYYY-MM-DD (machine, power: AC / battery, other jobs)

**Ran**
| Case | Stage | Ranks | Start | Status | Simulated | Steps | CPU / clock (h) | s per step |
|---|---|---|---|---|---|---|---|---|
| <name> | section / rotor | 4 | HH:MM | finished / stopped / failed | <t> c/U or rev | | / | |

**Issues** (observation -> cause, with evidence -> action)
- ...

**Records written**: `cfd/.../results/records/<case>/` (or "none, because ...")

**Next**: ...
```

How to fill it fast:
- `python3 cfd/post/record_all.py --dry-run` lists finished and stopped cases.
- Each record's `log_excerpt.txt` starts with the session table (start time, ranks, steps,
  CPU and clock seconds, clock/CPU). A clock/CPU ratio above about 1.3 means the solver waited:
  the machine slept or was throttled, or two jobs shared the cores.
- `pmset -g log | grep -E "Sleep|Wake"` gives the macOS sleep and wake times.

---

## 2026-10-08 (Apple M2 MacBook Air, fanless; AC; Stage 1 production queue) - in progress

**Queue launch, 07:33:03.** `queue.py --detach queues/priority1.txt priority2.txt priority3.txt`:
35 queue lines, 31 unique cases; pid 19767; log `section2d/results/queue_20261008_073303.log`.
Case 1, `a000.0_U23.0_SST_medium_Tu1.0`, started at once on 4 ranks (performance cores).

**Ran** (measured from the log at 07:48; the case was still running)

| Case | Stage | Ranks | Start | Status | Simulated | Steps | CPU / clock (h) | s per step |
|---|---|---|---|---|---|---|---|---|
| `a000.0_U23.0_SST_medium_Tu1.0` (queue case 1 of 31) | section | 4 | 07:33 | running | 4.53 c/U of 150 | 3859 | 0.250 / 0.252 | 0.23 |

At 08:01 (`queue.py --status`, measured): 8.5 of 150 c/U, 6630 steps, 0.320 s/step over the last
200 steps, about 8.0 h left at that rate (estimated). The rise from 0.170 s/step (steps 100-300)
follows the p-solver iterations per step, 21 -> 40, as the flow develops; CPU time per p-iteration
stayed at 7.1-8.1 ms throughout, so the machine is not throttling (`pmset -g therm`: no thermal or
performance warning recorded). The idle-machine cost estimates of `section2d/README.md` section 6
(0.17-0.21 s/step) are therefore low for developed flow; update them from case 1's `results.json`.

**Review, 07:34-07:53** (three reviewers; report-only for the running Stage 1 case)
- **Stage 1: ready**, no fix needed before running. Checked against the v2606 source:
  decayControl, kInf and omegaInf in `<model>Coeffs`; `ddt(gammaInt) Euler`; `maxLambdaIter` only
  gates a warning. The running case's generated files are byte-identical to `case_template`
  (caseParameters aside), and its far-field k and omega reproduce `section2d/README.md` section 3.
  First 731 steps (0.47 c/U): 0.172 s/step, Co max 4.99-5.01, omega bounding in 0 steps; upstream
  probe Tu 1.0044 % at 1.08 c/U (the precompensated smoke test: 1.81 %). Small issues (status
  totals, RUNNING marker, README wording) are fixed below.
- Records: ready with fixes (rendering, test records; Issues below, `RECORDS.md`).
- rotor2d: ready with fixes (`rotor2d/README.md`).

**Co-scheduling test, 07:37-07:42** (rotor2d reviewer; measured; `rotor2d/README.md`). A static
rotor case (A, theta 0, medium, 4 ranks, `--wall-limit 300`) under `taskpolicy -c background`, next
to Stage 1:
- Every rotor process (run_case, caffeinate, mpirun, pimpleFoam) ran at scheduling priority 4,
  which keeps it on the efficiency cores. `-c utility` gives priority 20 and may use the
  performance cores, so it is not suitable.
- Rotor on the efficiency cores: 530 steps in 295 s, 0.56 s/step wall (0.45 s CPU), about 5x the
  estimated 0.11 s/step on the performance cores. Rotor priority 0 (16 static cases) would take
  about 53 h +-40 % there (estimated).
- Stage 1: 0.185 s/step in the 180 s before, 0.237 during (280 s), 0.292 after (379 s), while its
  p-iterations per step rose from 24 to 36. Regressed on p-iterations per step with a
  during-test indicator, the slowdown is -2.9 +- 3.7 % (wall) and -2.4 +- 3.5 % (CPU): none
  detectable (2-sigma bound about +5 %). Wall and CPU time per step stayed equal (0.237 / 0.236 s),
  so its ranks were not descheduled. (The Stage 1 reviewer's raw reading, 0.170 -> 0.21-0.22 s/step
  over steps 1216-1416, is the same rise before this normalisation.)
- Caveat: the machine is a fanless MacBook Air. A 5-min test cannot show heat-soak throttling under
  a sustained 8-core load. If the rotor queue runs next to Stage 1, check Stage 1's CPU time per
  p-iteration and `pmset -g therm` after 1-2 h, and pause the rotor queue
  (`python3 cfd/rotor2d/queue.py --pause`) if Stage 1 has slowed by more than about 15 %.
- Stage 1's case 1 `s_per_step` includes these 5 min of overlap (of about 8-9 h).

**Fixes after the review** (Stage 1 code and docs; the running queue process keeps the code it
imported at 07:33, so the `run_case.py` change applies from the next launch; `--status` and
`record_all.py` use the new code at once)
- `section2d/run_case.py`: the RUNNING marker is removed in a `finally`, so an error or a stop signal
  no longer leaves it; it stays only if the process is killed outright (SIGKILL, crash, power
  loss). `cfd/post/record_lib.py` (`marker_state`): a marker with no solver process naming the case
  and no log write for 10 min is `stale`; `queue.py --status` and `record_all.py` report it so, and
  `record_all.py` handles such a case as stopped. Tested on scratch copies (error, SIGTERM and
  timeout paths; stale, fresh and live-process markers).
- `section2d/queue.py --status`: totals per unique case (31; before, per queue line: running 2,
  pending 33); a running case shows c/U of the end time and s/step over the last 200 steps from
  `log.pimpleFoam`.
- `section2d/README.md`: status line; hook output goes to `section2d/results/records/after_case.log`;
  kInf/omegaInf "used only when decayControl is on (zeroed otherwise)"; the fieldAverage "starting
  averaging at time 0" line is printed at construction, and averaging starts at `timeStart` (50 c/U).

**Issues** (observation -> cause, with evidence -> action)
- None in the solver so far: clock/CPU 1.01; the log header prints "Employing decay control with
  kInf 0.07935 and omegaInf 514.3" (the 8 Oct set-up, LEARNING_LOG section 3); Co max 5.0.
- deltaT had grown to 3.37 us at 4.5 c/U (2.13 us at 1.08 c/U in the 7 Oct smoke run), about
  620 steps per c/U. If it holds, the case needs about 93,000 steps, about 6 h at 0.23 s per step
  (estimated). The 0.23 s per step includes about 2 min of single-process record rendering
  (nice 10) during 07:45-07:47. Superseded at 08:01 by 0.32 s/step, about 8 h left (above).
- Record pipeline review: the field images were drawn about 25 % darker than their colour bars
  and the palette quantisation merged rare colours -> fixed in `render_fields.py` (RECORDS.md,
  "Rendering change, 8 Oct"); the kept test records were re-rendered.

**Records written**: test records re-rendered (`_test_pipeline_coarse_N0.3` through the queue hook
`after_case.sh` with the queue's PATH, 17 s; `_test_pipeline_coarse_LM_N0.3`,
`_smoke_a000_U23_SST_medium_Co5n2`; `_smoke_a000_U23_SST_medium_Co10n2` without images).
`_test_schemes_LL` removed. One `record_all.py` sweep at 07:47 skipped the running case ("RUNNING
marker present") and wrote nothing.

**Next**: the queue hook writes the first production record when case 1 completes; replace the
test figures of LEARNING_LOG sections 2, 3, 6 and 7 with it and fill the [pending] items. Update
`section2d/README.md` section 6 from case 1's seconds per step. If rotor priority 0 is started on the
efficiency cores, run the thermal check above after 1-2 h.

---

## 2026-10-07 (Apple M2 MacBook Air; battery and then AC; section and rotor jobs overlapping)

**Ran** (measured from the logs; CPU = ExecutionTime of rank 0, clock = ClockTime)

| Case | Stage | Ranks | Start | Status | Simulated | Steps | CPU / clock (h) | s per step |
|---|---|---|---|---|---|---|---|---|
| a000.0_U23.0_SST_medium_Tu1.0, session 1 (now `_smoke_a000_U23_SST_medium_Co5n2`) | section | 4 | 19:16 | stopped (`writeNow`) | 0.59 c/U | 875 | 0.122 / 0.157 | 0.50 |
| same, session 2 | section | 4 | 19:42 | stopped (wall limit) | 0.59 -> 1.08 c/U | 512 | 0.078 / 2.47 | 0.55 |
| `_smoke_a000_U23_SST_medium_Co10n2` (maxCo 10) | section | 4 | 19:29 | finished, diverged | 0.59 -> 0.68 c/U | 77 | 0.076 / 0.148 | 3.56 |
| `_test_pipeline_coarse_N0.3` | section | 4 | 22:13 | finished | 0.3 c/U | 377 | 0.018 / 0.019 | 0.17 |
| `_test_pipeline_coarse_LM_N0.3` | section | 4 | 22:18 | finished | 0.3 c/U | 380 | 0.019 / 0.020 | 0.18 |
| `_test_schemes_LL` (limitedLinear k, omega) | section | 4 | 22:16 | finished | 0.15 c/U | 224 | 0.012 / 0.013 | 0.20 |
| `A_sta_U23.0_th000.0_SST_coarse` | rotor | 2 | 19:37 | stopped (240 s limit) | 1.35 D/U | 730 | 0.050 / 0.063 | 0.25 |
| `A_sta_U23.0_th000.0_SST_medium` | rotor | 2 | 22:10 | stopped (420 s limit) | 3.14 D/U | 2443 | 0.113 / 0.116 | 0.17 |
| `B_sta_U23.0_th000.0_SST_medium` | rotor | 2 | 22:17 | stopped (420 s limit) | 2.05 D/U | 2154 | 0.114 / 0.116 | 0.19 |
| `A_rot_U23.0_lam0.150_SST_coarse` | rotor | 2 | 22:08 | stopped (90 s limit) | 0.040 rev | 403 | 0.023 / 0.024 | 0.20 |
| `A_rot_U23.0_lam0.150_SST_medium` | rotor | 2 | 22:24 | stopped (600 s limit) | 0.126 rev | 2297 | 0.165 / 0.166 | 0.26 |
| `B_rot_U23.0_lam0.150_SST_medium` | rotor | 2 | 22:34 | stopped (600 s limit) | 0.098 rev | 1644 | 0.165 / 0.166 | 0.36 |

The section and rotor smoke runs overlapped in time, so the seconds per step include contention.
The idle-machine figure for the medium section is 0.17-0.21 s per step (`section2d/README.md`
section 5).

**Issues**
- **Sleep stall.** The medium section case's second session logged ClockTime 8785 s against
  ExecutionTime 186 s when checked during the evening. At the wall-clock limit the values were
  8886 s against 282 s (clock/CPU = 31). Cause: the laptop ran on battery and slept at 1 % charge
  from 19:44 to 22:04 (pmset log, `section2d/README.md` section 5). `caffeinate -i` does not keep
  a closed laptop on battery awake. Action: run on AC power with the lid open. The queues now wait
  for AC power before each case and hold `caffeinate -is`. The record of this case shows the stall
  as a vertical jump in `timestep.png`:
  `section2d/results/records/_smoke_a000_U23_SST_medium_Co5n2/`.
- **maxCo 10 diverged.** The p residual rose from 0.012 to about 0.8 within 0.08 c/U, k reached
  2e7 m^2/s^2 and deltaT fell to 1e-8 s. maxCo stays at 5; queue 1 tests 2.5.
- **limitedLinear for k and omega** let omega go negative in 217 of 224 steps; upwind showed none.
  The template keeps upwind (`section2d/README.md` section 5).
- **Cost.** At maxCo 5, deltaT is about 2 us, set by the cells at the square corners, so a
  150 c/U medium case is about 147,000 steps, 7-8 h at 0.17-0.2 s per step on 4 idle ranks
  (calculated). The rotating rotor smoke runs reached 0.10-0.13 revolutions in 10 min on 2 ranks
  with other jobs running. Extrapolated linearly, 8 revolutions is 10-14 h per case (calculated;
  the time step may change after start-up).

**Records written** (record scripts first used this day; details in `RECORDS.md`):
- section: `_test_pipeline_coarse_N0.3`, `_test_pipeline_coarse_LM_N0.3`, `_test_decay_SST_a000_U23`,
  `_test_schemes_LL`, `_smoke_a000_U23_SST_medium_Co10n2`, `_smoke_a000_U23_SST_medium_Co5n2` (stopped);
- mesh-only: section `{coarse,medium,fine}_a000.0`; rotor `A_{coarse,medium,fine}_wf_U23.0_th000.0`,
  `A_medium_lowRe_U23.0_th000.0`, `A_medium_wf_U10.2_th000.0`, `B_medium_wf_U23.0_th000.0`.
- The rotor smoke-run folders were deleted by their owner before a record was made; their numbers
  above come from the logs read during the session.
- Later removed: `_test_decay_SST_a000_U23` (with its run folder, after the decay-control checks)
  and `_test_schemes_LL` (8 Oct; RECORDS.md, test records).

**Next**: production queues on AC power; a record for every finished case
(`after_case.sh` from the queues, or a periodic `record_all.py`).
