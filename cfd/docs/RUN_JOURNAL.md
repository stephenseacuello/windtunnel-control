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

## 2026-10-14 (Unity: rough-blade rotor runs and alpha-0 restart test launched; records updated)

**Rotor roughness option.**
- Code: `rotor2d/run_case.py` keys `ks`, `cs`, `nutwf` (`rotor2d/README.md`). They put
  nutkRoughWallFunction with Ks and Cs on the three blades.
- Unchanged cases: smooth cases are byte-identical to the previous code. This was checked for
  every line of queues 0, A, B, C and D_rerun, the sense variants included.
- Smoke test (Mac): nutkRoughWallFunction was read with Ks 200 um on all 672 blade faces; Ks+
  median 13.5.
- Queue `rotor2d/queues/priorityE_rough.txt`: assembly A, sense CCW, 23 m/s, lambda 0.10 and
  0.12, 50 revolutions with the last 45 averaged, 16 ranks.
- Cases: rough wall function at Ks 0, 100 and 400 um, plus the smooth Spalding reference.
  Ks 0 with the same wall function isolates the roughness effect.
- Jobs 65666671-76 started 10:42 UTC. The two Spalding runs (65666807, 65666808) are pending.

**Fixes to `submit.py`:**
- sbatch's stderr note for 32 GB jobs leaked into the job id used for lane dependencies. Two
  submissions failed with "Unable to open file INFO:". The id is now parsed from stdout only.
- With lanes off, the loop's last test returned 1, so the script reported failure after
  submitting. It now uses an if.

**Alpha-0 flow states** (RESULTS.md, "Addendum (13 Oct): force histories"; computed):
- The state separates within the first 40 c/U, and no run switches state.
- The fine maxCo-2.5 run and LM at 10.2 m/s have force jumps that inflate Cd_std. Without the
  jumps their Cd_std falls from about 1.0 to about 0.1.
- 10 of the 28 healthy runs have such jumps.

**Restart test.** `cfd/hpc/hysteresis_restart.py`; jobs 65666875 and 65666876.
- The maxCo-5 high-drag field continued at maxCo 2.5, and the maxCo-2.5 low-drag field continued
  at maxCo 5, each for 60 c/U.
- If each keeps its state, the alpha-0 state depends on history (bistable), not only on the time
  step.

**Records updated.**
- LEARNING_LOG: grid table, St against alpha, the health flag, the two alpha-0 states, and the
  roughness sign and tripping.
- RUN_JOURNAL 12 Oct: correction added.
- section2d README section 6: measured costs.
- RECORDS.md: p_inf offset noted.

---

## 2026-10-13 (Unity: analysis of the 150 cases; re-run set submitted)

**Download.** `pull_results.py` brought 140 Unity cases to the Mac with records, with no failures.
The rebuilt tables match the analysed ones exactly: 150 cases, no differing value.

**Analysis.** See `cfd/analysis/2026-10-13/`: RESULTS.md, TEAM_SUMMARY.md, 18 figures. The team
page is private until shared (https://claude.ai/artifact/UDDDEKWUKaGdQQ37N21qpy).

**Re-run set, submitted 21:5x EDT** (RESULTS.md section 8.4; 106 jobs):

| Stage | Queue file | Jobs | Contents |
|---|---|---|---|
| Section | `section2d/queues/priority6_rerun.txt` | 74 | the 23 flagged runs at maxCo 2.5; a maxCo 1.25 check at alpha 0 and 180 (SST, LM); the transition test, LM against SST at alpha 150-210 at 10.2/23/38 m/s with LM also at Tu 0.5 and 3 % |
| Stage 2 | `stage2/queues/S2e_rerun.txt` | 26 | wall-function sweeps at alpha 90 and 180 at maxCo 2.5; meshed texture at maxCo 2.5 with 150 c/U averaged over the last 100 (SST and LM, alpha 0 and 180, t 0/0.2, LM also t 0.1); LM texture at 18.8, 20.9 and 25.2 m/s (alpha 180, t 0 and 0.2) |
| Rotor | `rotor2d/queues/priorityD_rerun.txt` | 5 | coarse and fine meshes for A (sense CCW) at lambda 0.10 and 0.15; the 38 m/s, lambda 0.30 case run longer (16 revolutions, last 8 averaged) |
| Section | manual job 65650307 | 1 | `_unity_a000.0_U23.0_SST_medium_Tu1.0`: the Mac's maxCo-5 case repeated on Unity, to separate time step from machine |

**Scheduling.**
- Lanes allow at most about 700 cores, of the lab's 768.
- uri-cpu was 97 % allocated, so every pending job was moved to `uri-cpu,cpu` (`scontrol
  update`), and `submit.py` now defaults to that.
- At submission, 17 jobs (192 cores) were running.
- Cost model, once running: section about 21 h, Stage 2 about 34 h (the texture runs).

**Not in this set:**
- a rough-blade rotor case (the rotor code has no rough-wall option yet);
- the alpha-0 hysteresis restart and the Cd(t) history plots (analysis tasks on the downloaded
  cases).

---

## 2026-10-12 (Unity: status after the weekend; fixes and resubmissions)

**Status at 06:53 EDT** (`cfd/hpc/status.py`; `sacct`, *measured*):
- 116 of 139 cases complete: 106 on Unity, 10 on the Mac.
- Of the 129 Unity jobs, 106 completed and 23 failed.

**The 23 failures, by cause:**

1. **No final write after a restart (3 cases).** These are the three cases moved from the Mac.
   - Each ran to "End", but its final time was never written.
   - Cause: OpenFOAM counts adjustableRunTime write times from each run's start time, and these
     runs restarted from a writeNow pause off the write grid.
   - Fix: `foam_launch.align_final_write`, called on every resume in all three `run_case.py`.
     It makes the end time a write time.
   - Resubmitted.
2. **Time limit (12 cases).** All are kOmegaSSTLM medium section cases, stopped at 36-99 %.
   - Their time step is 0.14-2.2 us, against 2-3.4 us for SST (*measured*), because the
     transition model is far stiffer.
   - *Correction, 13 Oct:* the small time steps (0.14-2.2 us) came from runs later flagged as
     corrupted (13 Oct analysis, `cfd/analysis/2026-10-13/RESULTS.md` section 2.2), not from the
     transition model's stiffness. All 12 cases are among the 23 flagged runs (each has 2-3 solver
     sessions in its record), and healthy LM runs step as fast as healthy SST runs.
   - Resubmitted with limits from each case's own measured speed, using the new estimate in
     `submit.py`.
   - The slowest two, a180 at 10.2 m/s and a165, need about 1.5-2 days (*estimated*).
3. **Divergence at maxCo 5 (8 cases).** The time step collapsed (to 1e-34 to 1e-103 s), followed
   by a floating-point exception (rc 136). The 8 cases are:

   | Group | Cases | Collapsed at |
   |---|---|---|
   | Section, fine mesh | a000, a090, a180 | 40-46 c/U |
   | Stage 2, alpha 0, 23 m/s | Ks0, Ks100 | |
   | Stage 2, alpha 0, 10.2 m/s | Ks0, Ks100, Ks200 | |

   Not resumed. They are re-run at maxCo 2.5 from new queue files:
   - `section2d/queues/priority5_co25.txt`: coarse, medium and fine at alpha 0, 90 and 180.
     a000 medium at maxCo 2.5 was already in priority 1.
   - `stage2/queues/S2d_co25.txt`: the whole alpha-0 Ks and speed sweeps at 10.2, 23 and 38 m/s.
     The cases that finished at maxCo 5 give the time-step sensitivity.
   - 19 jobs.

**Also changed:**
- The cost model scales the step count with 5/maxCo.
- `run_one.py` rebuilds the stage's results CSV on Unity after each completed case, so the CSVs
  can be read through Unity OnDemand.

**Next**: when everything is complete, run `pull_results.py` on a network that allows SSH. The
Co 2.5 fine cases take about 22 h; the slowest LM cases run to about Wednesday 14 Oct.

---

## 2026-10-09 (Mac queues paused; production moved to Unity HPC)

**Mac.** The three queues were paused at 06:45 (`queue.py --pause`) so the laptop could be closed.
- Finished on the Mac and kept: section a000 medium and a000/a090/a180 coarse; rotor static A θ0,
  θ30, θ60 and B θ0, θ60; Stage 2 a180 Ks0.
- Half-finished cases moved to Unity with `cfd/hpc/migrate.py`, each resumed from its
  reconstructed latest time on 8 ranks (*measured*, job logs: "[migrated] ... [resume]"):

  | Case | Moved at |
  |---|---|
  | section a090 SST medium | 138.5 of 150 c/U |
  | rotor B θ30 static | t = 0.415 of 0.437 s |
  | Stage 2 a180 Ks50 | t = 0.236 of 0.313 s |

**Unity set-up** (`cfd/hpc/README.md`):
- OpenFOAM v2606 through the `opencfd/openfoam-run:2606` image, the same source commit as the Mac
  app.
- One Slurm job per case on `uri-cpu`, account `pi_sodhi_uri_edu`.
- All 65 meshes made on the Mac and uploaded.

**Test job 65482767** (uri-cpu032, Xeon 8352Y, 8 ranks each, early flow, *measured*):

| Case | Rate | Notes |
|---|---|---|
| Section coarse a000 | 0.069 s/step | decay-control message present |
| Rotor static B θ90 medium | 0.091 s/step | forces, AMI weights and probes written |
| Stage 2 wf a000 Ks100 | 0.124 s/step | |

All three match the cost model in `hpc_common.py`.

Two checks did not run as intended:
- **Migration path.** Not exercised: the 240 s section run wrote no time folder to reconstruct.
  The three real moved cases above then resumed correctly.
- **Making a mesh inside the container.** It failed because `/work/.../tmp` is not visible in the
  container. Case folders under `repo/cfd`, the job's working directory, are visible. Production
  does not make meshes in jobs: `submit.py` holds any case without an uploaded mesh.

**Submitted at 18:32 EDT.** 129 jobs, all remaining cases of section priority 1-4, rotor
priority 0, A and C (rotating cases in both rotation senses) and Stage 2 S2a-S2c.
- Dealt into 26 lanes of 8 ranks and 19 of 16, at most 512 of the lab's 768 cores.
- About 5,100 core-hours, and about 14 h once running (*estimated*, cost model).
- The jobs still waiting were scheduled to start by 20:00 EDT (`squeue --start`).

**Next** (Monday 12 Oct, from a network that allows SSH; the 9 Oct wired network blocks port
22):
1. `python3 cfd/hpc/status.py`.
2. `python3 cfd/hpc/pull_results.py`, which downloads, makes records and rebuilds CSVs.
3. `python3 cfd/hpc/submit.py --sense-variants` resumes anything that stopped at its time limit.

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
