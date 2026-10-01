import csv, hashlib, os, io
P="/Users/stepheneacuello/Projects/windtunnel-control/reports/roughness_2026-09/build/review/package/unzipped/URI_VAWT_Roughness_Data_2026-09-30"
rows=list(csv.DictReader(open(os.path.join(P,"MANIFEST.csv"),encoding="utf-8")))
listed=set()
for r in rows:
    p=os.path.join(P,r["path"]); listed.add(r["path"])
    b=open(p,"rb").read()
    sha=hashlib.sha256(b).hexdigest()
    ok_sha = sha==r["sha256"]; ok_b = len(b)==int(r["bytes"])
    dr=""
    if p.endswith(".csv"):
        txt=b.decode("utf-8","replace").splitlines()
        noncomment=[l for l in txt if not l.startswith("#")]
        nonempty=[l for l in noncomment if l.strip()]
        dr=f"lines={len(txt)} noncomment={len(noncomment)} nonempty_minus_header={len(nonempty)-1}"
    print(("OK " if ok_sha and ok_b else "BAD"), r["path"], r["bytes"], len(b), r["data_rows"], dr)
allf=set()
for d,_,fs in os.walk(P):
    for f in fs: allf.add(os.path.relpath(os.path.join(d,f),P))
print("unlisted:", allf-listed-{"MANIFEST.csv"})
print("missing:", listed-allf)
