# scripts/

Standalone. No dependency on the rest of the package.

## rpm.py

```bash
pip install pymodbus pyserial
python rpm.py
```

```
rpm> 600      set 600 rpm
rpm> ?        read back actual
rpm> 0        stop
rpm> q        quit (always stops the fan)
```

130 lines, one file. Settings are the six constants at the top.

Use this when you want to spin the tunnel and nothing else. Use `src/run.py`
or the dashboard when you want profiles, logging, calibration, or gusts.

### Four things in it that look removable and are not

**The keep-alive thread.** Parameters 3018/3019 make the drive fault and stop
if it stops hearing from the host. That watchdog is what makes it safe to run a
15 HP fan from a laptop — but something has to keep talking while you sit at
the prompt. Delete it and the fan stops on its own after 3 seconds, and you
will think the script is broken.

**The `try/finally`.** Ramps down on every exit path including Ctrl-C. The
alternative is a fan still turning after you have closed the terminal.

**Reference before run, then READY→RUN.** Send the run bit first and the fan
accelerates toward whatever setpoint the previous session left in the register.
And the drive latches on the *rising* edge of the run bit — if the control word
already reads 0x047F from a session that died badly, writing it again does
nothing while every write reports success.

**The clamp.** `RPM_MAX = 1700` is the top of the tested band, not the drive's
capability.

### The one unverified number

`RPM_PER_HZ = 29.17` assumes a 4-pole 1750 rpm / 60 Hz motor on a direct drive.
It is self-consistent with the Feb 13 data but has not been checked against the
hardware. One anemometer reading settles it — see `verify` in the playbook.
Change that constant and everything else follows.
