"""
selftest.py — verify, against the actual drive, every assumption this code makes.

    python run.py --port /dev/ttyVFD selftest

**Read-only. Nothing is written. The fan cannot move.**

═══════════════════════════════════════════════════════════════════════════
WHY THIS EXISTS
═══════════════════════════════════════════════════════════════════════════
Several things in this package are inferred from ABB's documentation rather
than observed on your drive:

  · that drive parameter P is readable at Modbus wire address P − 1
  · that parameter 1105 is stored in tenths of a Hz
  · that parameters 5310/5311 point at output frequency and motor current
  · that this pymodbus build takes `slave=` rather than `device_id=`

Each is probably right. But if one is wrong, the failure does not announce
itself — the 1105 scaling in particular would make every commanded speed off
by exactly 10x, silently, and every dataset you took would be wrong in a way
that looks plausible.

Ten seconds of read-only checks turns four assumptions into four facts. Run it
once after wiring, and again any time the drive is reconfigured.
"""

from __future__ import annotations

from acs550 import ACS550, DriveError

PASS, FAIL, WARN, INFO = "PASS", "FAIL", "WARN", "INFO"


def _line(status, name, detail=""):
    mark = {PASS: " ok ", FAIL: "FAIL", WARN: "warn", INFO: "    "}[status]
    print(f"  [{mark}] {name}")
    if detail:
        for d in detail.split("\n"):
            print(f"         {d}")


def run(drive: ACS550, interactive=True):
    """Returns (n_pass, n_fail, findings)."""
    results = []

    def check(status, name, detail=""):
        results.append((status, name))
        _line(status, name, detail)

    print("\n" + "=" * 62)
    print("  SELF-TEST — read-only, the fan cannot move")
    print("=" * 62 + "\n")

    # 1 ── transport ------------------------------------------------------
    try:
        sw = drive._read(3)[0]
        check(PASS, "Modbus transport",
              f"status word 0x{sw:04X} read from wire address 3 (reg 40004)\n"
              f"pymodbus unit-id keyword resolved to '{drive._slave_kw}'")
    except DriveError as e:
        check(FAIL, "Modbus transport", f"{e}\n"
              "Nothing else can be checked. Work through section 7 of the\n"
              "wiring checklist — start by swapping X1-29 and X1-30.")
        return 0, 1, results

    # 2 ── parameter address mapping (P -> P-1) ---------------------------
    # 9904 MOTOR CTRL MODE is a small enum; 2008 MAX FREQ is a plausible
    # frequency. If the offset were wrong we would read garbage from both.
    try:
        max_freq_raw = drive.read_param(2008)
        plausible = 100 <= max_freq_raw <= 5000 or 10 <= max_freq_raw <= 500
        check(PASS if plausible else FAIL, "parameter mapping (address = P − 1)",
              f"par 2008 MAX FREQ raw = {max_freq_raw}\n"
              + ("consistent with a real frequency limit"
                 if plausible else
                 "NOT a plausible frequency — the address offset is wrong.\n"
                 "Every parameter read in this package is suspect."))
    except DriveError as e:
        check(FAIL, "parameter mapping", str(e))

    # 3 ── the 1105 tenths heuristic --------------------------------------
    raw = drive.read_param(1105)
    inferred = raw / 10.0 if raw > 200 else float(raw)
    check(INFO, "REF1 MAX (par 1105) scaling",
          f"raw register value = {raw}\n"
          f"code infers {inferred:.1f} Hz "
          f"({'tenths' if raw > 200 else 'whole Hz'})")
    if interactive:
        print(f"\n         >>> Check the keypad: PARAMETERS → 1105 REF1 MAX")
        ans = input(f"         >>> Does it read {inferred:.1f} Hz? [y/N] ").strip().lower()
        if ans == "y":
            check(PASS, "1105 scaling confirmed against the keypad")
        else:
            check(FAIL, "1105 scaling",
                  "MISMATCH. Every commanded speed will be wrong by the ratio\n"
                  "between these two numbers — most likely a factor of 10.\n"
                  "Fix: pass ref1_max_hz=<true value> to ACS550(), or correct\n"
                  "the heuristic in acs550.connect().")

    # 4 ── actual-value mapping (5310 / 5311) -----------------------------
    p5310, p5311 = drive.read_param(5310), drive.read_param(5311)
    ok10, ok11 = p5310 == 103, p5311 == 104
    check(PASS if ok10 else WARN, "par 5310 → 40005",
          f"points at parameter {p5310} "
          + ("(0103 OUTPUT FREQ, as expected)" if ok10 else
             f"— expected 103. actuals()[0] is NOT output frequency;\n"
             f"set 5310 = 103 or the readback means something else."))
    check(PASS if ok11 else WARN, "par 5311 → 40006",
          f"points at parameter {p5311} "
          + ("(0104 CURRENT, as expected)" if ok11 else
             f"— expected 104. actuals()[1] is NOT motor current."))

    # 5 ── control source: can Modbus actually command anything? ----------
    p1001, p1103 = drive.read_param(1001), drive.read_param(1103)
    comm_cmd, comm_ref = p1001 == 10, p1103 == 8
    if comm_cmd and comm_ref:
        check(PASS, "control source",
              "1001 = 10 (COMM) and 1103 = 8 (COMM)\n"
              "The drive WILL accept start/stop and speed over Modbus.\n"
              "The Aerolab panel pot and start button are inactive.")
    else:
        check(INFO, "control source",
              f"1001 EXT1 COMMANDS = {p1001} "
              f"({'COMM' if comm_cmd else 'not COMM'})\n"
              f"1103 REF1 SELECT   = {p1103} "
              f"({'COMM' if comm_ref else 'not COMM'})\n"
              "Modbus cannot move the fan yet. That is the correct state\n"
              "until you have finished section 7 of the checklist.")

    # 5b ── local/remote and the manual fallback --------------------------
    st = drive.status()
    if not st.get("REMOTE", True):
        check(WARN, "control location",
              "drive is in LOCAL keypad mode — status bit 9 REMOTE is clear.\n"
              "It will ignore the fieldbus while in this state, and writes\n"
              "will still report success. Press LOC/REM on the keypad.")
    else:
        check(PASS, "control location",
              "drive is in REMOTE — it is listening to the fieldbus.\n"
              "Note the keypad LOC/REM button always overrides this, which is\n"
              "a useful manual fallback and also a way for someone to take\n"
              "your script offline without telling you.")

    p1102 = drive.read_param(1102)
    if p1102 in (0, 1):
        check(INFO, "manual fallback",
              f"1102 EXT1/EXT2 SEL = {p1102} — control location is fixed.\n"
              "If 1001/1103 are set to COMM, the Aerolab pot and start button\n"
              "are inactive. Wiring 1102 to a digital input gives you a\n"
              "manual/remote selector — see Phase 10B of the playbook.")
    else:
        check(PASS, "manual fallback",
              f"1102 EXT1/EXT2 SEL = {p1102} (a digital input)\n"
              "A selector switch chooses between the Aerolab panel and Modbus,\n"
              "so the tunnel still works normally for anyone not scripting.")

    # 6 ── the watchdog ---------------------------------------------------
    p3018, p3019 = drive.read_param(3018), drive.read_param(3019)
    t_out = p3019 / 10.0 if p3019 > 100 else float(p3019)
    if p3018 == 0:
        check(FAIL, "comm-loss watchdog",
              "3018 COMM FAULT FUNC = 0 (NOT SEL).\n"
              "If the host dies mid-run the fan keeps turning at its last\n"
              "setpoint, unattended, indefinitely. Set 3018 = 1 before any\n"
              "unattended operation. This is the main safety argument for\n"
              "running a 15 HP fan from a Pi.")
    else:
        check(PASS, "comm-loss watchdog",
              f"3018 = {p3018}, 3019 = {t_out:.1f} s\n"
              f"keep-alive runs at 0.5 s — "
              f"{t_out / 0.5:.0f}x margin")

    # 7 ── ramp times vs gust ambitions -----------------------------------
    accel, decel = drive.get_ramp_times()
    max_f = drive.ref1_max_hz
    check(INFO, "ramp rates",
          f"accel {accel:.1f} s, decel {decel:.1f} s over 0–{max_f:.0f} Hz\n"
          f"→ max slew {max_f / accel:.1f} Hz/s up, "
          f"{max_f / decel:.1f} Hz/s down\n"
          f"decel is {'slower — expected without a brake chopper'
                     if decel > accel else 'faster than accel — unusual'}")

    # 8 ── comm health ----------------------------------------------------
    c = drive.comm_counters()
    if c["crc_err"] or c["uart_err"]:
        check(WARN, "link quality",
              f"CRC errors {c['crc_err']}, UART errors {c['uart_err']}\n"
              "CRC → noise, termination, or baud mismatch.\n"
              "UART → parity or framing. Check par 5304 against --parity.")
    else:
        check(PASS, "link quality",
              f"{c['ok']} good frames, no CRC or UART errors")

    # 9 ── fault state ----------------------------------------------------
    if drive.is_faulted():
        check(WARN, "drive state",
              f"FAULTED, par 0401 = {drive.last_fault()}.\n"
              "Find out why before resetting.")
    else:
        check(PASS, "drive state", "no active fault")

    npass = sum(1 for s, _ in results if s == PASS)
    nfail = sum(1 for s, _ in results if s == FAIL)
    nwarn = sum(1 for s, _ in results if s == WARN)

    print("\n" + "=" * 62)
    print(f"  {npass} passed · {nwarn} warnings · {nfail} failures")
    if nfail:
        print("  Resolve the failures before commanding the fan.")
    elif nwarn:
        print("  Usable, but read the warnings — they change what the")
        print("  readback numbers mean.")
    else:
        print("  Every assumption in this package checks out against your drive.")
    print("=" * 62 + "\n")
    return npass, nfail, results
