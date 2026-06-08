from apps.api.app.compression_goals import load_compression_goals


def test_load_goals_includes_notes():
    goals = load_compression_goals()
    assert "notes" in goals
    # notes should be a short summary (reduced)
    assert isinstance(goals["notes"], str)
    assert len(goals["notes"]) < 500
    assert "Risiken" in goals["notes"] or "Risks" in goals["notes"]
