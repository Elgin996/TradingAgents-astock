import tradingagents.default_config as default_config
import copy
from pathlib import Path
from typing import Dict, Optional

# Use default config but allow it to be overridden
_config: Optional[Dict] = None


def initialize_config():
    """Initialize the configuration with default values."""
    global _config
    if _config is None:
        _config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def set_config(config: Dict):
    """Update the configuration with custom values."""
    global _config
    if _config is None:
        _config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    _config.update(copy.deepcopy(config))


def get_config() -> Dict:
    """Get the current configuration."""
    if _config is None:
        initialize_config()
    return copy.deepcopy(_config)


def load_versioned_config(path: str | Path) -> dict:
    """Load a versioned YAML config without silently accepting a bad shape."""
    path = Path(path)
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - optional runtime fallback
        raise RuntimeError("PyYAML is required to load versioned config files") from exc
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"config must be a mapping: {path}")
    if not loaded.get("version"):
        raise ValueError(f"versioned config is missing version: {path}")
    return loaded


# Initialize with default config
initialize_config()
