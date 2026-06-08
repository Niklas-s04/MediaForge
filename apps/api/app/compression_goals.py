from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Optional


GOALS_PATH = Path(__file__).with_name("compression_goals.json")


@lru_cache(maxsize=1)
def load_compression_goals() -> dict[str, Any]:
    with GOALS_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    # Try to attach a short human-readable summary from docs/compression_risks.md
    try:
        repo_root = Path(__file__).resolve().parents[3]
        notes_path = repo_root / "docs" / "compression_risks.md"
        if notes_path.exists():
            raw = notes_path.read_text(encoding="utf-8")
            # split into paragraphs by blank lines and take first non-empty paragraph
            parts = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
            summary = parts[0] if parts else raw.strip()
            # Cap summary length to 400 chars
            if len(summary) > 400:
                summary = summary[:400].rsplit(" ", 1)[0] + "..."
            data["notes"] = summary
    except Exception:
        # non-fatal: ignore if we cannot read notes
        pass

    return data


def _normalize_extension(file_name_or_ext: Optional[str]) -> Optional[str]:
    if not file_name_or_ext:
        return None
    ext = os.path.splitext(file_name_or_ext)[1].lower().lstrip(".")
    if ext:
        return ext
    return file_name_or_ext.lower().lstrip(".")


def resolve_compression_family(mime_type: Optional[str] = None, file_name_or_ext: Optional[str] = None) -> str:
    goals = load_compression_goals()
    families = goals.get("families", {})
    normalized_ext = _normalize_extension(file_name_or_ext)

    if mime_type:
        for family_name, family in families.items():
            prefixes = family.get("mime_prefixes", [])
            if any(mime_type.startswith(prefix) for prefix in prefixes):
                return family_name

    if normalized_ext:
        for family_name, family in families.items():
            if normalized_ext in family.get("extensions", []):
                return family_name

    return goals.get("fallback", {}).get("family", "archive")


def get_compression_profile(
    family: Optional[str],
    profile_name: str = "balanced",
) -> dict[str, Any]:
    goals = load_compression_goals()
    selected_family = family or goals.get("fallback", {}).get("family", "archive")
    family_block = goals.get("families", {}).get(selected_family)
    if not family_block:
        raise KeyError(f"Unknown compression family: {selected_family}")

    profiles = family_block.get("profiles", {})
    if profile_name not in profiles:
        raise KeyError(f"Unknown compression profile '{profile_name}' for family '{selected_family}'")

    profile = dict(profiles[profile_name])
    profile["family"] = selected_family
    profile["profile"] = profile_name
    return profile


def summarize_profile_warning(profile: dict[str, Any], lang: str = "de") -> Optional[str]:
    """Return a short warning string for UI if profile is aggressive or lossy.

    `lang` supports 'de' (default) and 'en'.
    """
    if not profile:
        return None
    parts: list[str] = []
    pname = (profile.get("profile") or "").lower()

    # helper messages
    msgs = {
        "de": {
            "aggressive": "Aggressives Profil: deutliche Qualitätsverluste möglich.",
            "strip": "Metadaten werden entfernt.",
            "low_bitrate": "Niedrige Bitrate: Sprach-/Musikqualität kann leiden.",
            "high_crf": "Hoher CRF-Wert: sichtbare Qualitätsverluste möglich.",
            "image_lossy": "Verlustbehaftete Bildkonvertierung möglich.",
        },
        "en": {
            "aggressive": "Aggressive profile: noticeable quality loss possible.",
            "strip": "Metadata will be removed.",
            "low_bitrate": "Low bitrate: speech/music quality may suffer.",
            "high_crf": "High CRF value: visible quality loss possible.",
            "image_lossy": "Lossy image conversion possible.",
        },
    }

    m = msgs.get(lang, msgs["en"]) if lang else msgs["en"]

    if pname in ("small", "low", "aggressive"):
        parts.append(m["aggressive"])

    if profile.get("strip_metadata"):
        parts.append(m["strip"])

    # bitrate like '96k'
    br = profile.get("bitrate")
    if isinstance(br, str):
        try:
            num = int(br.lower().rstrip("k"))
            if num < 128:
                parts.append(m["low_bitrate"])
        except Exception:
            pass

    crf = profile.get("crf")
    if isinstance(crf, (int, float)) and crf >= 32:
        parts.append(m["high_crf"])

    fmt = profile.get("format")
    if fmt and fmt.lower() in ("webp", "avif") and profile.get("quality", 100) < 80:
        parts.append(m["image_lossy"])

    if parts:
        return " ".join(parts)
    return None