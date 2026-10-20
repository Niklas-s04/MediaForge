"""Shared, validated compression choices. Archives preserve the original bytes."""
from pathlib import Path

from .compression_goals import resolve_compression_family

ARCHIVES = ["zip", "gz", "xz"]
OFFICE_FORMATS = {"docx", "xlsx", "pptx", "odt", "ods", "odp", "docm", "xlsm", "pptm", "epub"}
FORMATS = {
    "video": ["mp4", "webm", "mkv"],
    "audio": ["opus", "mp3", "m4a", "flac"],
    "image": ["webp", "avif", "jpg", "png"],
    "pdf": ["pdf"],
}


def compression_family(filename):
    try:
        family = resolve_compression_family(file_name_or_ext=filename)
    except (ValueError, KeyError):
        family = "other"
    # Animated images must never silently become single-frame images.
    if Path(filename).suffix.lower() in {".gif", ".webp", ".apng"}:
        return "other"
    return family


def normalize_compression(filename, item):
    family = compression_family(filename)
    extension = Path(filename).suffix.lower().lstrip(".")
    native = [extension] if extension in OFFICE_FORMATS else FORMATS.get(family, [])
    fmt = item.get("output_format", (native or ARCHIVES)[0])
    if fmt not in native + ARCHIVES:
        raise ValueError("Dieses Komprimierungsformat passt nicht zur Quelldatei.")
    quality = item.get("quality_preset", "balanced")
    if not isinstance(quality, str) or quality not in {"high", "balanced", "small"}:
        raise ValueError("Unbekannte Qualitätsstufe.")
    result = {
        "operation": "compress", "source": "upload", "source_family": family,
        "output_format": fmt, "quality_preset": quality,
        "strip_metadata": item.get("strip_metadata", False),
    }
    if not isinstance(result["strip_metadata"], bool):
        raise ValueError("Metadaten-Einstellung muss ein Wahrheitswert sein.")
    bounds = {"level": (1, 9), "crf": (18, 40), "max_width": (16, 7680),
              "max_fps": (1, 120), "image_quality": (1, 100),
              "audio_channels": (1, 2), "sample_rate": (8000, 48000), "pdf_dpi": (72, 300)}
    for key, (minimum, maximum) in bounds.items():
        value = item.get(key)
        if value not in (None, ""):
            try:
                number = int(value)
            except (ValueError, TypeError):
                raise ValueError(f"Ungültiger Wert für {key}.")
            if str(number) != str(value) or not minimum <= number <= maximum:
                raise ValueError(f"{key}: erlaubt sind {minimum} bis {maximum}.")
            result[key] = number
    bitrate = item.get("audio_bitrate")
    if bitrate:
        if not isinstance(bitrate, str) or bitrate not in {"48k", "64k", "96k", "128k", "192k", "256k", "320k"}:
            raise ValueError("Ungültige Audio-Bitrate.")
        result["audio_bitrate"] = bitrate
    rates = {8000, 12000, 16000, 24000, 48000} if fmt == "opus" else {8000, 16000, 22050, 24000, 32000, 44100, 48000}
    if "sample_rate" in result and result["sample_rate"] not in rates:
        raise ValueError("Diese Abtastrate wird vom Zielformat nicht unterstützt.")
    return result
