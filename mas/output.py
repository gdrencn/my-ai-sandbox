"""Shared transient terminal lines and permanent output for product and tester."""
from contextvars import ContextVar
from contextlib import contextmanager
import os
import shutil
import sys
import codecs
import select
from .text import cells, clipped


boundary = ContextVar('mas_output_boundary', default=None)
active_output = ContextVar('mas_active_output', default=None)


def terminal_size(stream):
    try:
        return os.get_terminal_size(stream.fileno())
    except (AttributeError, OSError, ValueError):
        return shutil.get_terminal_size()


def colored(text, tone, *, enabled=True, foreground_only=False):
    codes = {'green': 32, 'yellow': 33, 'red': 31}
    if not enabled or tone not in codes:
        return text
    return f'\033[{codes[tone]}m{text}\033[{39 if foreground_only else 0}m'


def before_output(preserve=None):
    current = active_output.get()
    if current is not None and current is not preserve:
        current.clear()
    callback = boundary.get()
    if callback is not None:
        callback()


class Output:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.tty = self.stream.isatty()
        self.active = False
        self.last = None

    def clear(self):
        if self.active:
            self.active = False
            if active_output.get() is self:
                active_output.set(None)
            self.stream.write('\r\033[2K')
            columns = max(1, terminal_size(self.stream).columns)
            # Shrinking the terminal may reflow the previously single row.
            for _ in range(max(0, (cells(self.last or '') - 1) // columns)):
                self.stream.write('\033[1A\r\033[2K')
            self.stream.flush()

    def progress(self, message, *, separate=True):
        self.progress_lines([message], separate=separate)

    def progress_lines(self, lines, *, separate=True):
        if not self.tty:
            return
        if separate:
            before_output(self)
        current = active_output.get()
        if current is not None and current is not self:
            current.clear()
        size = terminal_size(self.stream)
        # A status message is the fallback; the latest native output replaces it.
        lines = list(lines)
        text = clipped(lines[-1] if lines else '', max(0, size.columns - 1))
        if self.active and text == self.last:
            return
        active = self.active
        self.clear()
        self.stream.write(('' if active else '\r\033[2K') + text)
        self.stream.flush()
        self.active = True
        active_output.set(self)
        self.last = text

    def keep(self, message, *, end='\n'):
        before_output()
        self.clear()
        print(message, file=self.stream, end=end, flush=True)

    def foreground(self, text, tone):
        return colored(text, tone, enabled=self.tty)

    def consume(self, source, normal):
        """Render native fragments through the shared output boundary."""
        pending, committed, package_list = '', 0, False
        after_cr = False

        def emit(complete):
            nonlocal pending, committed, package_list
            if not committed and normal(pending, complete, package_list):
                if pending:
                    self.progress(pending)
            else:
                if len(pending) > committed or complete:
                    self.keep(pending[committed:], end='\n' if complete else '')
                committed = len(pending)
            if complete:
                if not pending.startswith((' ', '\t')):
                    package_list = pending.startswith(('The following ', 'Suggested packages:', 'Recommended packages:'))
                pending, committed = '', 0

        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        try:
            while True:
                if select.select([source], [], [], 0.05)[0]:
                    data = os.read(source.fileno(), 4096)
                    text = decoder.decode(data, final=not data)
                    for char in text:
                        if char == '\n' and after_cr:
                            after_cr = False
                            continue
                        after_cr = char == '\r'
                        if char in '\r\n':
                            emit(True)
                        else:
                            pending += char
                    if not data:
                        if pending:
                            emit(True)
                        break
                if pending:
                    emit(False)
        finally:
            self.clear()

    @contextmanager
    def waiting(self, message):
        """Scope a transient message, clearing it before any shared output."""
        # The next menu supplies its own gap. Do not leave an extra empty
        # line behind when this transient query message is erased.
        self.progress(message, separate=False)
        previous = boundary.get()

        def before_permanent_output():
            self.clear()
            if previous is not None:
                previous()

        token = boundary.set(before_permanent_output)
        try:
            yield
        finally:
            boundary.reset(token)
            self.clear()


def apt_stream():
    from .diagnostics import normal_apt_line
    Output().consume(sys.stdin.buffer, normal_apt_line)
