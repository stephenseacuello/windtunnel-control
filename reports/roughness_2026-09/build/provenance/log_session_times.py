"""Tunnel-session evidence from the repo's own logs: file birth/modify times,
in-file t_unix spans, and header clocks. Read-only; prints a table and writes
log_session_times.csv next to this script."""
import os, glob, csv, datetime as dt
REPO = '/Users/stepheneacuello/Projects/windtunnel-control'
here = os.path.dirname(os.path.abspath(__file__))
fmt = lambda t: dt.datetime.fromtimestamp(t).strftime('%Y-%m-%d %a %H:%M:%S')
rows = []
for f in sorted(glob.glob(f'{REPO}/logs/*.csv')) + sorted(glob.glob(f'{REPO}/data/snapshots/*.json')):
    st = os.stat(f)
    hdr, t0, t1, n = {}, '', '', ''
    if f.endswith('.csv'):
        lines = open(f, encoding='utf-8', errors='replace').read().splitlines()
        for l in lines:
            if l.startswith('# '):
                k, _, v = l[2:].partition(',')
                hdr[k] = v
        body = [l for l in lines if l and not l.startswith('#')]
        r = list(csv.DictReader(body))
        n = len(r)
        if r and 't_unix' in r[0]:
            ts = [float(x['t_unix']) for x in r if x.get('t_unix')]
            t0, t1 = fmt(min(ts)), fmt(max(ts))
    rows.append(dict(file=os.path.relpath(f, REPO), born=fmt(st.st_birthtime), modified=fmt(st.st_mtime),
                     rows=n, t_unix_first=t0, t_unix_last=t1, header_clock=hdr.get('clock', ''),
                     blade=hdr.get('blade', ''), notes=hdr.get('notes', '').strip('"')))
with open(os.path.join(here, 'log_session_times.csv'), 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
for r in rows:
    print(f"{r['file']:45s} born {r['born']}  mod {r['modified'][11:]}  n={r['rows']!s:5s} "
          f"t_unix {r['t_unix_first'][11:]}->{r['t_unix_last'][11:]}  clock={r['header_clock']}  {r['blade']}")
