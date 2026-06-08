import os
import json
import time
from typing import Any, Dict


def _default_log_path() -> str:
    return os.environ.get('AUDIT_OVERRIDE_LOG', os.path.join(os.getcwd(), 'data', 'override_audit.log'))


def audit_override(payload: Dict[str, Any], username: str, profile: str | None, lang: str = 'de', log_path: str | None = None) -> str:
    """Append a JSON-line audit entry for a forced override of a compression warning.

    Returns the path written to.
    """
    path = log_path or _default_log_path()
    # ensure directory exists
    dirp = os.path.dirname(path)
    if dirp and not os.path.exists(dirp):
        try:
            os.makedirs(dirp, exist_ok=True)
        except Exception:
            # best-effort: if cannot create, fallback to cwd
            path = os.path.join(os.getcwd(), os.path.basename(path))

    entry = {
        "ts": int(time.time()),
        "username": username,
        "profile": profile,
        "lang": lang,
        "payload": payload,
    }
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        # swallow exceptions to avoid breaking job creation flow
        pass
    return path
