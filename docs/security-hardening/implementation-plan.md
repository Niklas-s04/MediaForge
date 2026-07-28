# Implementation and TrueNAS rollout plan

## 1. Preconditions

- Reserve at least 3 GiB RAM and two CPU cores for ClamAV, adjusted after
  observing real workloads.
- Confirm a recent TrueNAS configuration backup and a restorable periodic
  snapshot of the MediaForge dataset.
- Confirm no unrelated NAS dataset is mounted into API, worker or scanner.
- Keep port 3310 unpublished.

## 2. Data ownership migration

The hardened application images run as UID/GID 10001. On TrueNAS:

```bash
cd /mnt/SSD/apps/mediaforge/source
sudo install -d -o 10001 -g 10001 -m 0750 \
  data data/uploads data/output data/logs data/tmp
sudo chown -R 10001:10001 data
```

Verify:

```bash
sudo find data -maxdepth 2 -printf '%u:%g %m %p\n'
```

## 3. Build and deploy

```bash
cd /mnt/SSD/apps/mediaforge/source
sudo git pull --ff-only
sudo docker build --no-cache -f apps/api/Dockerfile -t mediaforge-api:local .
sudo docker build --no-cache -f apps/worker/Dockerfile -t mediaforge-worker:local .
sudo docker build --no-cache -f docker/clamav/Dockerfile \
  -t mediaforge-clamav:local docker/clamav
sudo docker compose -f docker/docker-compose.yml config
sudo docker compose -f docker/docker-compose.yml up -d --force-recreate
```

The first signature download can take several minutes. Preserve the
`clamav-db` volume across normal upgrades.

## 4. Verification gates

```bash
sudo docker compose -f docker/docker-compose.yml ps
sudo docker compose -f docker/docker-compose.yml logs --tail=100 clamav
curl --fail http://127.0.0.1:8787/health
```

Require all of the following before production traffic:

- health reports `malware_scanner: ready`
- a normal upload converts and downloads successfully
- a multi-file batch downloads individually and as ZIP
- the standard EICAR antivirus test file is rejected with HTTP 422
- stopping ClamAV causes new uploads and downloads to fail with HTTP 503
- a `127.0.0.1`, RFC1918 or link-local remote URL is rejected and a remote
  download above `REMOTE_DOWNLOAD_MAX_BYTES` is stopped and removed
- `docker inspect` shows API and worker UID 10001, read-only roots,
  `CapDrop=["ALL"]` and no published ClamAV/Redis ports
- CI reports no known Python vulnerabilities via `pip-audit` and no high
  frontend dependency vulnerabilities via `npm audit`

Use only the standard EICAR test string from the official
[EICAR test file page](https://www.eicar.org/download-anti-malware-testfile/).
It is not malware, but it must still be handled only in the dedicated test
dataset and deleted after verification.

## 5. TrueNAS operational controls

- Place the app dataset under a quota and alert before the pool becomes full.
- Snapshot it frequently and replicate snapshots to a separately protected
  target.
- Do not publish the application directly to the Internet. Use VPN or an
  authenticated TLS reverse proxy and restrict ingress to trusted networks.
- Enable TrueNAS 2FA, least-privileged accounts and current security updates.
- Never expose the app dataset over SMB/NFS; keep SMB1 and NTLMv1 disabled.
- Rebuild application and ClamAV images regularly. Monitor ClamAV logs for
  signature update failures and the API health endpoint for scanner outages.

## 6. Rollback

Rollback should preserve protection rather than silently disable it:

1. Stop ingress at the reverse proxy.
2. Restore the previous application image tags and dataset snapshot if needed.
3. Keep the scanner port private and keep `MALWARE_SCAN_ENABLED=true`.
4. Reopen traffic only after the health and clean/EICAR tests pass.

Do not use `MALWARE_SCAN_ENABLED=false` as a production rollback. If scanning
cannot be restored, keep upload/download traffic closed.
