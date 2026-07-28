# Dedicated fail-closed ClamAV admission and release gate

## Goal

Prevent known malicious or incompletely inspected files from reaching converters,
persistent release storage or users, while reducing the blast radius of a
scanner or parser compromise.

## Control design

The API streams uploads to ClamAV before job creation. The worker repeats the
scan immediately before parser invocation, scans remote downloads and scans
converted output before success. The API performs a final release scan for
individual and batch downloads. A finding deletes the rejected file and records
a generic error; the malware signature is logged but not reflected to an
untrusted client. A scanner outage produces `503` and never bypasses scanning.

ClamAV runs as its unprivileged `clamav` user with no Linux capabilities, a
read-only root filesystem and only its signature database as persistent writable
storage. Files use `INSTREAM`; the scanner does not mount `/data`. Port 3310 is
not published and exists only on an isolated Compose network.

API and worker run as UID/GID 10001, with all capabilities removed,
`no-new-privileges`, read-only roots and constrained temporary filesystems.
Known-vulnerable upload/framework/downloader and frontend build dependencies are
updated, and CI fails when `pip-audit` or `npm audit` finds a published
vulnerability.
Remote fetches also reject local/non-public targets and enforce a byte ceiling
before the downloaded content reaches persistent release storage.
TrueNAS supplies the outer boundary: dedicated unshared dataset, quota,
snapshots/replication, firewall restriction and authenticated ingress.

## Failure behavior

- Finding or encrypted/limit-exceeded content: block, remove and mark failed.
- Scanner unavailable during upload: remove the unscanned upload and return 503.
- Scanner unavailable during worker processing: remove the transient file and
  fail the job.
- Scanner unavailable during final release recheck: retain the already scanned
  output and return 503 so release can be retried.
- Signature database not ready: ClamAV health remains unhealthy and API/worker
  startup waits.

## Tradeoffs

The control adds latency proportional to file size and a significant ClamAV RAM
requirement. It also turns scanner health into an availability dependency by
design. Those costs are preferable to silently processing or releasing an
unscanned file. Repeated boundary scans protect against post-scan replacement
and compromised conversion output at the cost of extra I/O.

## Rollout

Follow [implementation-plan.md](implementation-plan.md). Roll out to a staging
dataset first, verify clean, EICAR-test and unavailable-scanner cases, then
recreate production containers. Do not expose the scanner port during debugging.

## Residual risk

Signature evasion and parser zero-days remain possible. This option does not add
application user authentication or a general outbound firewall for yt-dlp.
Use VPN/authenticated reverse proxy ingress and a dedicated network/VLAN where
possible.
