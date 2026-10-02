"""Shared transient terminal lines and permanent output for product and tester."""
from contextvars import ContextVar
from contextlib import contextmanager
import os
import shutil
import sys
from .text import clipped


boundary = ContextVar('mas_output_boundary', default=None)


def before_output():
    callback = boundary.get()
    if callback is not None:
        callback()


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

    def progress(self, message, *, separate=True):
        if not self.tty:
            return
        if separate:
            before_output()
        try:
            columns = os.get_terminal_size(self.stream.fileno()).columns
        except (AttributeError, OSError, ValueError):
            columns = shutil.get_terminal_size().columns
        text = clipped(message, max(0, columns - 1))
        self.stream.write('\r\033[2K' + text)
        self.stream.flush()
        self.active = True

    def keep(self, message):
        before_output()
        self.clear()
        print(message, file=self.stream, flush=True)

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
