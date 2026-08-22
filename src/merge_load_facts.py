#!/usr/bin/env python3
"""
merge_load_facts.py — put the load-side measurements back into tunnel.json.

    python src/merge_load_facts.py            # merge
    python src/merge_load_facts.py --check    # report drift, change nothing

tunnel.json is shared with the drive side and has twice been replaced
wholesale, each time silently dropping every load-side measured fact in it:
the instrument's real range full scales, the absence of programmable
protection, the cut-out voltage, the proof that the load sinks current at all.

Rather than retype them a third time they live in data/load_facts.json, which
nothing else writes, and this folds them in. Deep merge, so drive-side keys are
never touched and existing values win only where this file says nothing.
"""

import argparse
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def deep_merge(dst, src, path=""):
    """src wins on leaves; dst keeps everything src does not mention."""
    changed = []
    for k, v in src.items():
        if k.startswith("_README"):
            continue
        here = f"{path}.{k}" if path else k
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            changed += deep_merge(dst[k], v, here)
        elif dst.get(k) != v:
            changed.append((here, dst.get(k), v))
            dst[k] = v
    return changed


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default=str(REPO / "data" / "tunnel.json"))
    p.add_argument("--facts", default=str(REPO / "data" / "load_facts.json"))
    p.add_argument("--check", action="store_true",
                   help="report what would change and exit non-zero if any")
    a = p.parse_args()

    cfg_p, facts_p = Path(a.config), Path(a.facts)
    cfg = json.loads(cfg_p.read_text(), object_pairs_hook=collections.OrderedDict)
    facts = json.loads(facts_p.read_text(),
                       object_pairs_hook=collections.OrderedDict)

    before = set(cfg.keys())
    changed = deep_merge(cfg, facts)

    if not changed:
        print("  tunnel.json already has every load-side fact. Nothing to do.")
        return 0

    print(f"  {len(changed)} value(s) {'would be' if a.check else ''} restored:")
    for where, old, new in changed:
        print(f"    {where}\n      was {str(old)[:56]}\n      now {str(new)[:56]}")

    if a.check:
        print("\n  --check: nothing written.")
        return 1

    assert set(cfg.keys()) >= before, "merge dropped a top-level key"
    cfg_p.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"\n  wrote {cfg_p} — drive-side keys untouched "
          f"({len(before)} top-level keys in, {len(cfg)} out)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
