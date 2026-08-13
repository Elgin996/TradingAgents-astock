from web import model_history


def test_model_history_keeps_most_recent_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(model_history, "_MODEL_HISTORY_FILE", tmp_path / "models.json")

    model_history.record_model_usage("openrouter", "vendor/quick-a", "vendor/deep-a")
    model_history.record_model_usage("openrouter", "vendor/quick-b", "vendor/deep-a")

    assert model_history.get_used_models("openrouter", "quick") == [
        "vendor/quick-b",
        "vendor/quick-a",
    ]
    assert model_history.get_used_models("openrouter", "deep") == ["vendor/deep-a"]
