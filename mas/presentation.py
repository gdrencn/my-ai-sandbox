"""Formatting shared by command and menu entry points."""
import json
from .diagnostics import diagnostic_lines
from .output import Output
from .i18n import t, state, progress_text
from .menu import column_rows, rendered
import sys


class Progress:
    """One reporter shared by CLI commands and the inline menu application."""
    def __init__(self, stream=None):
        self.output = Output(stream if stream is not None else sys.stderr)

    def __call__(self, event):
        message = progress_text(event)
        if event["status"] == "waiting" or (event.get("scope") == "native" and event["status"] == "ok"):
            self.output.progress_lines([message, *event['live_lines']] if event.get('live_lines') else [message])
        else:
            self.output.keep(message)
        if not event.get("native_failure"):
            if event.get('live_output') and event['status'] == 'error':
                self.output.keep('\n'.join(event.get('native_stdout', '').splitlines()[-60:]))
            for line in diagnostic_lines(event.get("native_stdout", ""), event.get("native_stderr", "")):
                self.output.keep(line)


def show_mounts(entries, write=print):
    if not entries:
        write(t("fs_empty"))
    rows = column_rows([(entry['path'], entry['destination'], state(entry['status'])) for entry in entries])
    for row in rows:
        write(rendered(row, sum(row.widths) + 2 * (len(row.widths) - 1), color=False))


def format_info(instance):
    return json.dumps(instance, indent=2)
