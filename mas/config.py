"""User preferences shared by installer, CLI and TUI."""

import json
import os
from pathlib import Path
import tempfile

LANGUAGES = ("en_us", "zh_cn")
DEFAULT_LANGUAGE = "zh_cn"


class ConfigError(ValueError):
    def __init__(self, message_id, **values):
        self.key, self.values = message_id, values
        super().__init__(message_id)


def path():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "my-ai-sandbox/config.json"


def load():
    try:
        values = json.loads(path().read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise ConfigError("config_object", path=path())
    except ConfigError:
        raise
    except FileNotFoundError:
        values = {}
    except (OSError, ValueError) as exc:
        raise ConfigError("config_read_error", path=path(), error=exc) from exc
    language = values.get("language", DEFAULT_LANGUAGE)
    if language not in LANGUAGES:
        raise ConfigError("invalid_language", value=language)
    return {**values, "language": language}


def get(key):
    if key != "language":
        raise ConfigError("unknown_setting", key=key)
    return load()[key]


def set_value(key, value):
    if key != "language":
        raise ConfigError("unknown_setting", key=key)
    if value not in LANGUAGES:
        raise ConfigError("invalid_language", value=value)
    values = load()
    values[key] = value
    destination = path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(values, output, ensure_ascii=False, indent=2)
            output.write("\n")
        temporary.replace(destination)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def language():
    try:
        return get("language")
    except ConfigError:
        return DEFAULT_LANGUAGE  # Lets error reporting describe a broken config.
