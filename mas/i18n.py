"""Small standard-library catalog reader; all interfaces use the same messages."""

import argparse
from contextlib import ExitStack
from functools import lru_cache
from importlib.resources import files
import json

from . import config


@lru_cache(maxsize=2)
def catalog(language):
    return json.loads(files("mas.locales").joinpath(language + ".json").read_text(encoding="utf-8"))


def t(message_id, *, locale=None, **values):
    return catalog(locale or config.language())[message_id].format(**values)


def state(value):
    key = "state_" + value.lower().replace(" ", "_")
    return t(key) if key in catalog(config.language()) else value


def progress_text(event):
    return t("progress", status=state(event["status"]), action=catalog(config.language()).get("action_" + event["action"], event["action"]),
             target=event["target"], observation=state(event["observation"]), elapsed=event["elapsed"])


def choose_language(selected=None, ask=None):
    if selected:
        config.set_value("language", selected)
        return selected
    current = config.get("language")
    if ask is None:
        with ExitStack() as stack:
            try:
                reader = stack.enter_context(open("/dev/tty", "r", encoding="utf-8"))
                writer = stack.enter_context(open("/dev/tty", "w", encoding="utf-8", buffering=1))
            except OSError as exc:
                raise ValueError(t("language_terminal_required")) from exc
            def read(prompt):
                writer.write(prompt)
                writer.flush()
                answer = reader.readline()
                if not answer:
                    raise EOFError(t("language_terminal_required"))
                return answer.strip()
            return choose_language(ask=read)
    while True:
        answer = ask(t("choose_language", current=current)).strip()
        language = {"1": "en_us", "2": "zh_cn", "": current}.get(answer, answer)
        if language in config.LANGUAGES:
            config.set_value("language", language)
            return language


class Parser(argparse.ArgumentParser):
    """Localize argparse-owned headings and common validation messages too."""
    def __init__(self, *args, **kwargs):
        argparse._ = lambda message: catalog(config.language()).get("argparse:" + message, message)
        super().__init__(*args, **kwargs)
