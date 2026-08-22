#!/usr/bin/env python3
"""
gust_demo.py — generate, check and plot profiles WITHOUT touching hardware.

Run this first, on any machine. Seeing the shapes and the feasibility warnings
before a 15 HP fan is involved is worth the two minutes.

    python gust_demo.py --tau 3.0
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import gusts  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tau", type=float, default=3.0,
                   help="tunnel time constant from characterize.py")
    p.add_argument("--max-slew", type=float, default=6.0, dest="max_slew",
                   help="Hz/s the drive ramp allows = MAX FREQ / par 2202")
    p.add_argument("--plot", action="store_true", help="requires matplotlib")
    a = p.parse_args()

    cases = [
        ("1-cosine, 20 s  (realistic)",
         gusts.one_minus_cosine(25, 8, 20)),
        ("1-cosine, 2 s   (too fast)",
         gusts.one_minus_cosine(25, 8, 2)),
        ("step            (system ID)",
         gusts.sharp_edged(25, 8, 30)),
        ("sine 0.05 Hz    (in band)",
         gusts.sinusoid(25, 5, 0.05, 120)),
        ("sine 0.5 Hz     (attenuated)",
         gusts.sinusoid(25, 5, 0.5, 60)),
        ("von Karman      (turbulence)",
         gusts.von_karman(25, 2.0, 40, 180, seed=42)),
    ]

    for name, (t, u) in cases:
        print(f"\n{name}")
        gusts.check_realizable(t, u, tau=a.tau, max_slew_hz_s=a.max_slew)

    print("\nThe two flagged cases are the point of this demo: they look")
    print("perfectly reasonable on a plot and will not come out of the tunnel")
    print("the way they went in.")

    if a.plot:
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(len(cases), 1, figsize=(10, 14), sharex=False)
        for ax, (name, (t, u)) in zip(axes, cases):
            ax.plot(t, u, lw=1.2)
            ax.set_title(name, fontsize=10, loc="left")
            ax.set_ylabel("Hz")
            ax.grid(alpha=0.3)
        axes[-1].set_xlabel("time (s)")
        plt.tight_layout()
        plt.savefig("gust_profiles.png", dpi=120)
        print("\nwrote gust_profiles.png")


if __name__ == "__main__":
    main()
