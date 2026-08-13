"""Persist model IDs used by the Web UI for later dropdown selection."""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG

_MODEL_HISTORY_FILE = Path(DEFAULT_CONFIG["results_dir"]).parent / "model_history.json"
_MODEL_HISTORY_LOCK = threading.Lock()
_MAX_MODELS_PER_ROLE = 30


def _load() -> dict[str, dict[str, list[str]]]:
    try:
        payload = json.loads(_MODEL_HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def get_used_models(provider: str, role: str) -> list[str]:
    values = _load().get(provider, {}).get(role, [])
    return [str(value) for value in values if str(value).strip()]


def record_model_usage(provider: str, quick_model: str, deep_model: str) -> None:
    provider = str(provider).strip().lower()
    if not provider:
        return
    with _MODEL_HISTORY_LOCK:
        payload = _load()
        provider_models = payload.setdefault(provider, {})
        for role, model in (("quick", quick_model), ("deep", deep_model)):
            model = str(model).strip()
            if not model:
                continue
            previous = [value for value in provider_models.get(role, []) if value != model]
            provider_models[role] = [model, *previous][:_MAX_MODELS_PER_ROLE]

        parent = _MODEL_HISTORY_FILE.parent
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=parent, suffix=".tmp", delete=False
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            temp_path = Path(handle.name)
        temp_path.replace(_MODEL_HISTORY_FILE)
