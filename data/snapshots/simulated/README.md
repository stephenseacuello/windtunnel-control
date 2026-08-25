# Simulated captures — NOT the drive

These were taken while the dashboard was running `--dry-run`. The simulated
drive answers **any** register, so a scan reports every candidate as existing
(2178 of 2178). A real ACS550 has a few hundred parameters.

Kept as a worked example of the failure, not as data. `1105` reads 24350 here
against the real drive's 2435 — applying that would have made every commanded
speed wrong by exactly ten.

**How to tell them apart:** a real scan finds a few hundred, not thousands,
and `# via` in the file says which session wrote it. Check `connected` and
`dry_run` in the dashboard before capturing anything you intend to keep.
