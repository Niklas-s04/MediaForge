# Centralize untrusted-file admission and containment

## Recommendation

Adopt the dedicated fail-closed ClamAV gate and container containment option.
It directly covers upload, remote download, parser entry, converted output and
batch release boundaries. It is selected because validation alone cannot detect
known malicious payloads and does not protect downstream downloaders.

## Option comparison

| Dimension | Validation and updates only | Dedicated ClamAV gate |
|---|---|---|
| Security effect | Compatibility control only | Known-malware detection at all material file boundaries |
| Availability | No new dependency | Scanner failure blocks admission/release |
| Performance | Negligible overhead | Multiple file streams; ClamAV memory/CPU |
| Operability | Patch parsers promptly | Also monitor signatures and scanner health |
| Cost | No new service | About 3 GiB configured scanner memory ceiling |
| Delivery risk | Low change, high residual risk | UID migration and first-start scanner warm-up |

## Evidence coverage

The selected option covers E001-E009 from [context.md](context.md). The
alternative covers only E001-E003 indirectly and leaves their core malware
detection gap open.

## Decision consequences

Files that cannot be completely scanned are intentionally unavailable. Encrypted
archives/documents and ClamAV limit hits are rejected. Operators must preserve
the signature volume, watch `/health`, keep images updated and maintain TrueNAS
snapshots. ClamAV port 3310 is private and the scanner has no MediaForge data
mount.

## Residual risk

No antivirus engine detects every malicious file. The deployment must remain
restricted to trusted networks or authenticated ingress, the worker must not
receive unrelated NAS mounts, and converter images must be rebuilt regularly.
