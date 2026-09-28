"""Transient terminal progress with permanent diagnostics and stage summaries."""
import re
import shutil
import sys
import unicodedata

# Raw external output is never translated. Unknown stderr is kept, not hidden.
PROGRESS = re.compile(r'^\[(?:waiting|ok|等待中|成功)\] .*?(?:waited|已等待) .*(?:s|秒)$')
from .diagnostics import WARNING


class Output:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.tty = self.stream.isatty()
        self.active = False

    def clear(self):
        if self.active:
            self.stream.write('\r\033[2K')
            self.stream.flush()
            self.active = False

    def progress(self, message):
        if not self.tty:
            return
        width = shutil.get_terminal_size().columns - 1
        text, used = '', 0
        for char in message.replace('\n', ' '):
            size = 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
            if used + size > width:
                break
            text += char
            used += size
        self.stream.write('\r\033[2K' + text)
        self.stream.flush()
        self.active = True

    def keep(self, message):
        self.clear()
        print(message, file=self.stream, flush=True)

    def diagnostics(self, stdout, stderr, failed=False):
        # All non-progress stderr is retained, including unknown warnings on exit 0.
        lines = [line for line in stderr.splitlines() if not PROGRESS.match(line)]
        lines += [line for line in stdout.splitlines() if failed or WARNING.search(line)]
        if lines:
            self.keep('\n'.join(lines))
