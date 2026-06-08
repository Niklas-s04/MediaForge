from apps.api.app.compression_goals import get_compression_profile, summarize_profile_warning


def test_small_audio_profile_has_warning():
    p = get_compression_profile("audio", "small")
    w = summarize_profile_warning(p)
    assert w is not None
    assert "Qualität" in w or "Qualit" in w


def test_balanced_profile_no_aggressive_warning():
    p = get_compression_profile("audio", "balanced")
    w = summarize_profile_warning(p)
    # balanced may still warn about metadata, but shouldn't about aggressive loss
    assert w is None or "Aggressive" not in w


def test_warning_in_english():
    p = get_compression_profile("audio", "small")
    w = summarize_profile_warning(p, lang="en")
    assert w is not None
    assert "quality" in w or "loss" in w
