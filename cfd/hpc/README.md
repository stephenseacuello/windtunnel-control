# cfd/hpc/: running the CFD queues on Unity

The three queues (section2d, rotor2d, stage2) run on the Unity cluster with one Slurm job per
case, so many cases run at once and the laptop can be closed. Each job runs the same case
the local queue would run: the same queue line, `run_case.py`, mesh and OpenFOAM version.
Records (plots, ParaView renders) are still made on the Mac, after the results are downloaded.

## How it works

| Piece | What it does |
|---|---|
| OpenFOAM | v2606 in the official image `opencfd/openfoam-run:2606` (Apptainer), at `$ROOT/containers/openfoam-run_2606.sif`. It has the same source commit (481094f) as the Mac app; only the compiler differs (gcc against clang), so expect round-off-level differences. |
| `../post/foam_launch.py` | `run_case.py` builds every OpenFOAM call as `openfoam2606 -c "..."`. With `CFD_FOAM_LAUNCH=container` (set by `job_env.sh`) the call runs as `apptainer exec <image> bash -c "source <bashrc> && ..."`. Unset (the Mac), nothing changes. It also handles cases moved from the Mac (`MIGRATED`). |
| Ranks | `--np`, else `$SLURM_NTASKS`, else 4. 8 ranks for medium meshes, 16 for fine and resolved-texture meshes (`DEFAULT_NTASKS` in `hpc_common.py`). |
| Meshes | Made on the Mac (`premesh.py`), uploaded by `sync_up.sh` to `<stage>/runs/_mesh/` on Unity. A missing mesh is made inside the job with the Unity venv (gmsh 4.15.2, as on the Mac). |
| Python on Unity | `$ROOT/venv` (Python 3.12, numpy, scipy, matplotlib, gmsh); `repo/cfd/.venv` links to it. |
| Jobs | `submit.py`: partition `uri-cpu` (URI nodes, 64 cores, not preemptible, 30-day limit), account `pi_sodhi_uri_edu`, 1 node, time limit 3 × estimate + 30 min. The lab can use up to 768 cores on uri-cpu; jobs beyond that wait in the queue. |
| Stop and resume | Slurm sends SIGTERM 15 min before the time limit. The solver is stopped and the case keeps its last written time, so the next `submit.py` run resumes it. A job never runs a case that is complete or already queued. |

`$ROOT` = `/work/pi_sodhi_uri_edu/seacuello/windtunnel-cfd` (1 TB group quota; snapshots for
2–3 days; no backup). The code mirror is `$ROOT/repo/cfd`; case folders are
`$ROOT/repo/cfd/<stage>/runs/<case>`; Slurm logs are `<stage>/runs/_slurm/`.

## Commands (from the repository root, on the Mac)

```zsh
bash   cfd/hpc/sync_up.sh                 # code + meshes up (never deletes on Unity)
python3 cfd/hpc/submit.py --dry-run       # plan: state, ranks, estimate, time limit per case
python3 cfd/hpc/submit.py --sense-variants
python3 cfd/hpc/status.py                 # progress of every case; --jobs for the Slurm list
python3 cfd/hpc/pull_results.py           # finished cases down, records made, CSVs rebuilt
```

Useful options:
- `submit.py --stage rotor2d`: one stage.
- `submit.py --only 'a090'`: a regular expression on case names.
- `submit.py --ntasks 16`: ranks per job.
- `submit.py --max-jobs 20`: submit at most this many.
- `submit.py --sense-variants`: also the rotating rotor cases with the rotation sense reversed.
  Both senses are run because the static sweep has not yet settled which way each hypothesis
  turns (`rotor2d/README.md`).

On Unity: `squeue --me`, `scancel --name=cfd.section2d.<case>`, `scancel -u $USER` (all).

SSH must reach `unity.rc.umass.edu` on port 22. Some networks block it; the result is
"Connection refused" for every host on port 22, including github.com.

## Moving a half-finished Mac case to Unity

```zsh
python3 cfd/section2d/queue.py --pause        # likewise rotor2d, stage2: the solver writes and stops
python3 cfd/hpc/migrate.py                    # list the partial cases
python3 cfd/hpc/migrate.py --go               # reconstruct the latest time, upload, mark MIGRATED
python3 cfd/hpc/submit.py
```

On Unity, `run_case.py` sees `MIGRATED`. It decomposes the reconstructed time for the job's
rank count and continues to the same end time, appending to the same `log.pimpleFoam`. The
local folder gets a `MOVED_TO_UNITY` marker. Do not resume it on the Mac as well.
`pull_results.py` later replaces it with the finished case and moves the old `processor*/`
folders to `<stage>/runs/_pre_unity/`.

## Files

| File | Role |
|---|---|
| `hpc_common.py` | Paths on Unity, queue files per stage, cost model (steps per case, s/step), helpers |
| `job_env.sh` | Sourced by every job: container, Python, environment |
| `run_one.py` | Runs one case inside a job (the stage's `run_case.run`) and appends to `hpc_jobs.jsonl` |
| `submit.py`, `status.py`, `pull_results.py`, `migrate.py`, `sync_up.sh` | As above |
| `remote_status.py` | Run on the login node by the others: case states and squeue as JSON |
| `premesh.py` | Makes the meshes on the Mac, into `mesh_cache/` (git-ignored) |
| `test_job.sh` | 45-min end-to-end test of each stage and of the migration path |

## Speed

Measured on 9 Oct 2026 (job 65445993, uri-cpu063, Xeon 6730P). Benchmark case: the Stage 1
medium mesh (131k cells, SST) run from t = 0.

| Run | Rate |
|---|---|
| Unity, 16 ranks | 16.2 steps/s, about 5× the Mac on 4 ranks |
| Mac, 4 ranks (3 queues sharing the machine) | 3.6–4.1 steps/s |

- A medium case takes about 2 h on 16 ranks and about 4–5 h on 8, against 9.4 h on the Mac.
- The rotor and Stage 2 rates in `S_PER_STEP` are estimates until `test_job.sh` and the first
  production jobs measure them; `status.py` shows s/step for every running case.
