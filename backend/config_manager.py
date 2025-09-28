import json
from pathlib import Path
from threading import Lock


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
_config_lock = Lock()


class ConfigError(Exception):
    """Raised when configuration cannot be loaded or saved."""


def load_config() -> dict:
    """Load configuration from disk."""
    if not CONFIG_PATH.exists():
        raise ConfigError(f"Config file not found at {CONFIG_PATH}")

    with _config_lock:
        with CONFIG_PATH.open("r", encoding="utf-8") as fp:
            return json.load(fp)


def save_config(new_config: dict) -> None:
    """Persist configuration to disk."""
    with _config_lock:
        with CONFIG_PATH.open("w", encoding="utf-8") as fp:
            json.dump(new_config, fp, ensure_ascii=False, indent=2)


def update_config(updates: dict) -> dict:
    """Merge updates into the existing config and persist the result."""
    config = load_config()
    # Remove credential updates to avoid persisting sensitive data to disk.
    updates = {
        key: value for key, value in updates.items()
        if key != "credentials"
    }
    config.pop("credentials", None)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value

    save_config(config)
    return config
