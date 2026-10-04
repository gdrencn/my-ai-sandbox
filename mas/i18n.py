"""Small standard-library catalog reader; all interfaces use the same messages."""

import argparse
from functools import lru_cache
from importlib.resources import files
import json

from . import config


@lru_cache(maxsize=2)
def catalog(language):
    root = files("mas.locales")
    messages = json.loads(root.joinpath(language + ".json").read_text(encoding="utf-8"))
    optional = root.joinpath("test").joinpath(language + ".json")
    if optional.is_file():
        messages.update(json.loads(optional.read_text(encoding="utf-8")))
    return messages


def t(message_id, *, locale=None, **values):
    return catalog(locale or config.language())[message_id].format(**values)


def state(value):
    key = "state_" + value.lower().replace(" ", "_")
    return t(key) if key in catalog(config.language()) else value


def progress_text(event):
    return t("progress", status=state("native_done" if event.get("scope") == "native" and event["status"] == "ok" else event["status"]), action=catalog(config.language()).get("action_" + event["action"], event["action"]),
             target=event["target"], observation=state(event["observation"]), elapsed=event["elapsed"])


def choose_language(selected=None):
    if selected:
        config.set_value("language", selected)
        return selected
    from . import menu
    try:
        chosen = menu.interactive(lambda ui: menu.language(ui, config.get("language")))
    except OSError as exc:
        raise ValueError(t("language_terminal_required")) from exc
    config.set_value("language", chosen)
    return chosen


class Parser(argparse.ArgumentParser):
    """Localize argparse-owned headings and common validation messages too."""
    def __init__(self, *args, **kwargs):
        argparse._ = lambda message: catalog(config.language()).get("argparse:" + message, message)
        super().__init__(*args, **kwargs)
