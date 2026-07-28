# Security hardening context

## Decision scope

Protect the MediaForge application and the TrueNAS host from untrusted files
uploaded by users, fetched from remote URLs, processed by native media/document
parsers and returned as individual files or batch ZIP archives.

Target revision: `af62907e7b27ddb1a65d19f4142f34e6543b21ee`

Source collection SHA-256:
`bbfd4928bae495b0019366bc0b52a44c9d7be5662d24bf5aea49be3d52267c17`

The hash covers the target-revision versions of:

- `apps/api/app/main.py`
- `apps/worker/worker.py`
- `apps/api/Dockerfile`
- `apps/worker/Dockerfile`
- `apps/api/requirements.txt`
- `apps/worker/requirements.txt`
- `apps/frontend/package.json`
- `apps/frontend/package-lock.json`
- `docker/docker-compose.yml`

## Trust boundaries and protected assets

Untrusted inputs cross the HTTP upload or remote-download boundary and are then
read by ffmpeg, LibreOffice, Poppler, librsvg, vtracer, img2pdf and yt-dlp.
Protected assets are the TrueNAS host, other NAS datasets, the application
database, generated output, credentials available to containers and users who
download completed files.

## Source evidence

| ID | Evidence | Security consequence |
|---|---|---|
| E001 | `apps/api/app/main.py` stored uploads and dispatched jobs without content malware scanning. | A known malicious file could reach persistent NAS storage and the worker. |
| E002 | `apps/worker/worker.py` passed uploaded and remotely downloaded files to multiple native parsers. | Parser vulnerabilities are reachable with attacker-controlled content. |
| E003 | `apps/api/app/main.py` returned successful output files and batch ZIPs based on job state and path checks only. | A malicious or compromised conversion result could be distributed. |
| E004 | Both original app images ran as root and `docker/docker-compose.yml` mounted the complete data directory read-write. | A parser compromise had unnecessarily broad container and application-data impact. |
| E005 | ClamAV documents `INSTREAM` scanning and states that the clamd TCP protocol has no authentication or encryption. | Stream files to an isolated scanner network; never publish port 3310. |
| E006 | Docker documents non-root users, capability removal, read-only filesystems, `no-new-privileges` and the default seccomp profile as containment controls. | Harden API, worker, Redis and scanner independently. |
| E007 | TrueNAS recommends least privilege, restricted shares/services and periodic snapshots. | Use a dedicated, unshared dataset with quotas, snapshots and restricted network access. |
| E008 | The pinned FastAPI, Starlette, Pydantic, multipart parser, dotenv, yt-dlp and frontend build dependency sets had published vulnerabilities in the July 2026 advisory databases. | Upgrade to compatible fixed releases and enforce `pip-audit` plus `npm audit` in CI. |
| E009 | `apps/api/app/main.py` and `apps/worker/worker.py` accepted user-selected remote URLs without a private-address policy or a remote byte limit. | Reject local/non-public targets before yt-dlp and enforce a download-size ceiling. |

## Assumptions

- The deployment uses Linux containers on TrueNAS SCALE.
- The configured maximum file size remains 2 GiB.
- Signature updates require outbound HTTPS/DNS access from the ClamAV container.
- MediaForge remains a trusted-network application; public identity and access
  management is supplied by a VPN or authenticated reverse proxy.

## Constraints and residual exposure

ClamAV is a detection layer, not proof that a file is safe. New malware and
parser zero-days can evade signatures. The worker still needs read-write access
to application data and outbound access for remote downloads. TrueNAS snapshots,
network segmentation, prompt image updates and restricted dataset mounts remain
required containment layers.

## Primary references

- [ClamAV Docker images](https://docs.clamav.net/manual/Installing/Docker.html)
- [Clamd protocol](https://docs.clamav.net/manual/Usage/ClamdProtocol.html)
- [ClamAV scanning](https://docs.clamav.net/manual/Usage/Scanning.html)
- [Docker Engine security](https://docs.docker.com/engine/security/)
- [Docker seccomp](https://docs.docker.com/engine/security/seccomp/)
- [TrueNAS security recommendations](https://www.truenas.com/docs/solutions/optimizations/security/)
- [TrueNAS periodic snapshots](https://cdn.truenas.com/docs/scale/datasets/snapshots/creatingsnapshots/)
