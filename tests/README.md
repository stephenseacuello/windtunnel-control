# Tests

```bash
pip install pytest
cd tests && python -m pytest -v
```

Two suites:

| File | What it protects |
|---|---|
| `test_tunnel.py` | the safety and physics properties — 108 tests |
| `test_docs.py` | the documentation's claims — 13 tests, instant |

Everything runs against the simulator — no hardware, no serial port. About
20 seconds.

## What these are for

This is research code. It will be modified — by you, by a student next
semester, by whoever inherits the tunnel. The tests that matter are not the
ones checking arithmetic; they are the ones checking that the **safety
properties still hold** after somebody refactors something:

| Test | Property |
|---|---|
| `test_profile_over_limit_is_refused_not_clipped` | Over-limit profiles are refused, never silently flattened |
| `test_midrun_fault_aborts` | A trip mid-run stops the loop instead of commanding a dead drive |
| `test_lost_comms_aborts` | A dead bus aborts rather than writing into the void |
| `test_local_mode_is_detected` | LOC/REM on the keypad is caught, not silently ignored |
| `test_context_manager_always_stops` | Every exit path leaves the fan stopped |
| `test_partial_log_survives_abort` | A five-minute run does not lose everything at minute four |
| `test_rpm_domain_refuses_to_command_velocity` | No drive map means no velocity commands |

If one of those breaks, the failure on real hardware is a 15 HP fan doing
something nobody asked for.

## Bugs these have already caught

**Simulator dead-time model (found on first run).** The transport delay used a
pop-based queue that assumed `_advance()` was called at a fine, regular
interval. In reality it is called whenever something reads or writes — which
may be milliseconds or seconds apart — so the simulated flow lagged by the
*call interval* rather than by `dead_time`, and under sparse polling never
caught up at all. A dry run would report 0 Hz after a full settle, and the
dashboard showed a flat line. Now interpolates by timestamp.

**Two tests that were themselves wrong.** `test_taper_prevents_step_at_onset`
originally asserted on overall maximum slew, which conflates two different
mechanisms: the taper fixes the *onset discontinuity* (45 → 0 Hz/s at the
junction), while band-limiting fixes general high-frequency content. Testing
the junction specifically is both correct and a better test.


---

## test_docs.py — the documentation is tested too

Roughly 1,500 lines of documentation make specific claims: commands you can
run, parameters to set, wind speeds you will get. Each is a chance for docs and
code to drift, and the drift is **silent** — nothing breaks until somebody
follows the instructions at the tunnel and it does not work.

| Test | Catches |
|---|---|
| every documented command parses | a renamed flag or removed mode |
| every CLI mode is documented | a feature nobody can find |
| wind speed tables match the calibration | a corrected calibration leaving stale tables behind |
| the formula matches | rounding is fine; wrong is not |
| referenced files exist | the classic rename-and-forget |
| playbook phase 1 parameters are in the dashboard | having to walk to the keypad |
| safety parameters never called optional | a doc suggesting the watchdog is disposable |
| no duplicate wiring procedures | four documents nobody can rank |

**Found on first run:** `calibrate` was a working CLI mode documented in no
file at all. It is now phase 12B of the playbook.

**Not tested:** prose. Whether an explanation is *good* is not something a test
can tell you. What is testable is whether the commands exist, the numbers
agree, and the cross-references resolve.
