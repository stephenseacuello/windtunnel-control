# examples/

## gust_demo.py — no hardware needed

```bash
python gust_demo.py --tau 3.0
```

Generates six profiles and runs each through the realizability check. Two of
them are deliberately unrealizable, and that is the point of the demo: they
look perfectly reasonable plotted, and will not come out of the tunnel the way
they went in.

Run this before designing a test matrix. It costs two minutes and no fan time.

## daq_integration.py — connecting Jeong lab's acquisition

```bash
python daq_integration.py --explain
```

Three patterns. The question is not how to read a DAQ channel —
`velocity_source.py` already does that — but **which lab owns which risk**:

| | Sync | Coupling | Use when |
|---|---|---|---|
| **A** one process | sample-exact | shared codebase | one person runs both halves |
| **B** network service | timestamps | four HTTP endpoints | **two labs — recommended** |
| **C** independent | timestamps | none | you trust both clocks |

Pattern B is usually right here. Jeong's side never installs pymodbus, never
learns what a control word is, and cannot leave the fan running. One team owns
the hazard, the other owns the measurement.

`pattern_c_align()` is a working timestamp join if you go the independent
route — it reports how many samples actually overlap rather than silently
producing a shorter record than you expected.

Whichever you pick: **record the tunnel state at the start and end of every
acquisition window.** That is what lets the two records be aligned later
without anyone trusting a stopwatch.
