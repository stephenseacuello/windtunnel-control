"""Small readers for OpenFOAM ASCII output, shared by the CFD post-processing.

    read_xy(path)                         sampled-line .xy / function-object .dat -> ndarray
    time_dirs(path)                       numeric sub-directories, sorted by value
    latest_time(path)                     the last of them (name as written)
    read_patch_field(case, time, field, patch)
                                          boundary values of one patch -> ndarray
                                          (needs writeFormat ascii; run
                                          'postProcess -func writeCellCentres' for C)
No OpenFOAM install is needed to use these.
"""
import re
from pathlib import Path

import numpy as np


def read_xy(path):
    """Whitespace-separated numeric table; '#' lines are skipped."""
    return np.loadtxt(path, comments="#")


def _is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def time_dirs(path):
    p = Path(path)
    return sorted((d.name for d in p.iterdir() if d.is_dir() and _is_number(d.name)), key=float)


def latest_time(path):
    t = time_dirs(path)
    if not t:
        raise FileNotFoundError(f"no time directories in {path}")
    return t[-1]


def read_patch_field(case, time, field, patch):
    """Values of `field` on boundary `patch` at `time` (ASCII field files only).
    Returns (n,) for scalars, (n,3) for vectors; a uniform value comes back as (1,) or (1,3)."""
    txt = (Path(case) / str(time) / field).read_text()
    bf = txt[txt.index("boundaryField"):]
    m = re.search(r"\n\s*" + re.escape(patch) + r"\s*\n\s*\{", bf)
    if not m:
        raise KeyError(f"patch {patch} not in {field}")
    body = bf[m.end():]
    vm = re.search(r"\bvalue\s+(uniform|nonuniform)\s+", body)
    if not vm:
        raise KeyError(f"no value entry for {patch} in {field}")
    rest = body[vm.end():]
    if vm.group(1) == "uniform":
        tok = rest.split(";", 1)[0].strip()
        return np.atleast_1d(np.array(tok.strip("()").split(), float)) if tok.startswith("(") \
            else np.array([float(tok)])
    lm = re.match(r"List<(\w+)>\s*(\d+)\s*\(", rest)
    kind, n = lm.group(1), int(lm.group(2))
    block = rest[lm.end():]
    if kind == "scalar":
        vals = np.array(block.split(")", 1)[0].split(), float)
    else:
        rows = re.findall(r"\(([^()]*)\)", block[: block.index("\n)")])
        vals = np.array([r.split() for r in rows], float)
    if len(vals) != n:
        raise ValueError(f"{field}/{patch}: expected {n} values, read {len(vals)}")
    return vals
