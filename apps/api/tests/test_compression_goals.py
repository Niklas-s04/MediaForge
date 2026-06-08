import pytest

from apps.api.app.compression_goals import resolve_compression_family, get_compression_profile, load_compression_goals


def test_load_goals_has_expected_keys():
    goals = load_compression_goals()
    assert "families" in goals
    assert "fallback" in goals


def test_resolve_by_mime_prefix():
    # audio mime should map to 'audio' family
    fam = resolve_compression_family(mime_type="audio/mpeg", file_name_or_ext=None)
    assert fam == "audio"


def test_resolve_by_extension():
    fam = resolve_compression_family(mime_type=None, file_name_or_ext="track.mp3")
    assert fam == "audio"


def test_resolve_fallback():
    fam = resolve_compression_family(mime_type="application/octet-stream", file_name_or_ext="archive.bin")
    # fallback in the goals file should be present
    goals = load_compression_goals()
    fallback = goals.get("fallback", {}).get("family", "archive")
    assert fam == fallback


def test_get_profile_valid():
    p = get_compression_profile("audio", "balanced")
    assert p["family"] == "audio"
    assert p["profile"] == "balanced"


def test_get_profile_unknown_family_raises():
    with pytest.raises(KeyError):
        get_compression_profile("nonexistent_family", "balanced")


def test_get_profile_unknown_profile_raises():
    with pytest.raises(KeyError):
        get_compression_profile("audio", "nope")
