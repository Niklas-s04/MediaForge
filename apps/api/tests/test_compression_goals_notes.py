import json

from apps.api.app.compression_goals import GOALS_PATH, load_compression_goals


def test_load_goals_includes_notes():
    load_compression_goals.cache_clear()
    goals = load_compression_goals()
    # Runtime notes must ship with the application, independently of local docs.
    assert goals["notes"] == json.loads(GOALS_PATH.read_text(encoding="utf-8"))["notes"]
    assert "notes" in goals
    # notes should be a short summary (reduced)
    assert isinstance(goals["notes"], str)
    assert len(goals["notes"]) < 500
    assert "Risiken" in goals["notes"] or "Risks" in goals["notes"]
