# Drive parameter snapshots

Timestamped read-only records of what the ACS550 was actually holding.

```bash
python src/drive_profile.py snapshot --name baseline --note "as found"
python src/drive_profile.py diff --profile windtunnel
```

**Commit these.** A snapshot nobody can diff against is a file, not a record.
The point is that "somebody changed something" becomes a two-line diff.

`apply` writes one automatically before it changes anything, named
`*_before_<profile>.json`, and refuses to write at all if that backup cannot
be saved.
