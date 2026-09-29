"""Formatting shared by command and menu entry points."""
import json
from .diagnostics import diagnostic_lines
from .output import Output
from .i18n import t, state, progress_text
import sys


class Progress:
    """One reporter shared by CLI commands and the inline menu application."""
    def __init__(self, stream=None):
        self.output = Output(stream if stream is not None else sys.stderr)

    def __call__(self, event):
        message = progress_text(event)
        if event["status"] == "waiting" or (event.get("scope") == "native" and event["status"] == "ok"):
            self.output.progress(message)
        else:
            self.output.keep(message)
        if not event.get("native_failure"):
            for line in diagnostic_lines(event.get("native_stdout", ""), event.get("native_stderr", "")):
                self.output.keep(line)


def show_mounts(entries, write=print):
    if not entries:
        write(t("fs_empty"))
    for entry in entries:
        write(f"{entry['path']}\t{entry['destination']}\t{state(entry['status'])}")


def format_info(instance):
    return json.dumps(instance, indent=2)
