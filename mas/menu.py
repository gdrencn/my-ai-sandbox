"""Inline terminal menus. Only the active block is redrawn; history is preserved."""
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import os
import select
import sys
import termios
import unicodedata

from .i18n import t
from .output import boundary


class Cancelled(Exception):
    pass


def cells(text):
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1 for char in text)


def clipped(text, width):
    # User-provided labels must not inject terminal control sequences.
    text = ''.join(char if char.isprintable() else ' ' for char in str(text))
    result, used = '', 0
    for char in text:
        size = cells(char)
        if used + size > width:
            break
        result += char
        used += size
    return result


def wrapped(text, width):
    """Keep input instructions readable without terminal-controlled wrapping."""
    remaining = clipped(text, 100000)
    lines = []
    while remaining:
        line = clipped(remaining, max(2, width))
        lines.append(line)
        remaining = remaining[len(line):]
    return lines or ['']


@dataclass(frozen=True)
class Cell:
    text: str
    tone: str = ''


def status_cell(text, status):
    tone = 'green' if status in ('Running', 'mounted') else 'yellow' if status in ('Stopped', 'residual', 'disconnected') else 'red'
    return Cell(text, tone)


@dataclass(frozen=True)
class Columns:
    values: tuple
    widths: tuple
    prefix: str = ''


def column_rows(rows):
    """One column structure per list; widths adapt together on each redraw."""
    prepared = [tuple(cell if isinstance(cell, Cell) else Cell(str(cell)) for cell in row) for row in rows]
    if not prepared:
        return []
    if len({len(row) for row in prepared}) != 1:
        raise ValueError('Selection rows must have the same columns')
    widths = tuple(max(cells(clipped(row[i].text, 100000)) for row in prepared) for i in range(len(prepared[0])))
    return [Columns(row, widths) for row in prepared]


def rendered(label, width):
    if isinstance(label, str):
        return clipped(label, width)
    prefix = clipped(label.prefix, width)
    available = max(0, width - cells(prefix))
    widths = list(label.widths)
    gap = 2
    while sum(widths) + gap * max(0, len(widths)-1) > available and max(widths, default=0) > 1:
        largest = max(range(len(widths)), key=widths.__getitem__)
        widths[largest] -= 1
    result = prefix
    colors = {'green': '\x1b[32m', 'yellow': '\x1b[33m', 'red': '\x1b[31m'}
    for index, (cell, size) in enumerate(zip(label.values, widths)):
        value = clipped(cell.text, min(size, available))
        result += colors.get(cell.tone, '') + value + ('\x1b[39m' if cell.tone in colors else '')
        available -= cells(value)
        if index < len(widths)-1:
            padding = max(0, min(available, size - cells(value) + gap))
            result += ' ' * padding
            available -= padding
    return result


@dataclass
class Selection:
    options: list
    index: int = 0
    multiple: bool = False
    checked: set = field(default_factory=set)

    def move(self, step):
        self.index = (self.index + step) % len(self.options) if self.options else 0

    def toggle(self):
        self.checked.symmetric_difference_update({self.options[self.index][0]})

    def result(self):
        return [value for value, _ in self.options if value in self.checked] if self.multiple else self.options[self.index][0]


class Screen:
    """A small inline block, not a screen-owning UI. Input mode is scoped per prompt."""
    def __init__(self, terminal):
        self.terminal = terminal
        self.fd = terminal.fileno()
        self.rows = 0
        self.dimensions = None
        self.needs_gap = False

    def write(self, text):
        self.terminal.write(text.encode('utf-8'))

    def before_output(self):
        if self.needs_gap:
            self.write('\n')
            self.needs_gap = False

    def heading(self, title):
        self.write('\n' + clipped(title, 100000) + '\n')
        self.needs_gap = True

    def size(self):
        value = os.get_terminal_size(self.fd)
        return max(2, value.columns), max(4, value.lines)

    @contextmanager
    def prompt(self):
        original = termios.tcgetattr(self.fd)
        changed = termios.tcgetattr(self.fd)
        changed[3] &= ~(termios.ICANON | termios.ECHO)
        changed[6][termios.VMIN] = 1
        changed[6][termios.VTIME] = 0
        self.rows = 0
        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, changed)
            self.write('\n\x1b[?25l')
            self.needs_gap = False
            yield
        finally:
            termios.tcsetattr(self.fd, termios.TCSANOW, original)
            self.write('\x1b[0m\x1b[?25h')
            self.needs_gap = True
            self.rows = 0

    def key(self):
        if not select.select([self.fd], [], [], 0.2)[0]:
            return 'resize' if self.size() != self.dimensions else 'idle'
        char = os.read(self.fd, 1)
        if not char or char == b'\x04':
            raise Cancelled
        if char in (b'\r', b'\n'):
            return 'activate'
        if char in (b'\x7f', b'\x08'):
            return 'erase'
        if char == b'\x03':
            raise KeyboardInterrupt
        if char == b'\x1b':
            sequence = b''
            while len(sequence) < 8 and select.select([self.fd], [], [], 0.12)[0]:
                part = os.read(self.fd, 1)
                if not part:
                    break
                sequence += part
                if (part.isalpha() and sequence != b'O') or part == b'~':
                    break
            return {b'[A': 'up', b'[B': 'down', b'[C': 'right', b'[D': 'left',
                    b'OA': 'up', b'OB': 'down', b'OC': 'right', b'OD': 'left',
                    b'[H': 'home', b'[F': 'end', b'[3~': 'delete', b'': 'back'}.get(sequence, 'ignore')
        length = 1 if char[0] < 128 else 2 if char[0] < 224 else 3 if char[0] < 240 else 4
        for _ in range(length - 1):
            if not select.select([self.fd], [], [], 0.2)[0]:
                return 'ignore'
            char += os.read(self.fd, 1)
        return char.decode('utf-8', errors='replace')

    def draw(self, lines):
        dimensions = self.size()
        # Resizing may reflow earlier rows. Append a fresh block instead of
        # guessing cursor coordinates and overwriting historical output.
        if self.rows and self.dimensions == dimensions:
            self.write(f'\x1b[{self.rows}A')
        self.dimensions = dimensions
        width, height = dimensions
        lines = lines[:height - 1]
        for label, focused in lines:
            self.write('\r\x1b[2K' + ('\x1b[7m' if focused else '') +
                       rendered(label, width - 1) + '\x1b[0m\n')
        self.rows = len(lines)

    def choose(self, title, options, default=None, multiple=False, checked=(), radio=False):
        if not options:
            raise ValueError('Menu requires at least one option')
        index = next((i for i, (value, _) in enumerate(options) if value == default), 0)
        selection = Selection(options, index, multiple, set(checked))
        with self.prompt():
            while True:
                count = max(1, self.size()[1] - 3)
                offset = max(0, selection.index - count + 1)
                lines = [(title, False)]
                for index in range(offset, min(len(options), offset + count)):
                    value, label = options[index]
                    focused = index == selection.index
                    marker = ('☑' if value in selection.checked else '☐') if multiple else ('●' if focused else '○') if radio else ''
                    prefix = ('❯ ' if focused else '  ') + (marker + ' ' if marker else '')
                    row = prefix + label if isinstance(label, str) else replace(label, prefix=prefix)
                    lines.append((row, focused))
                lines.append((t('menu_multi_keys' if multiple else 'menu_keys'), False))
                self.draw(lines)
                key = self.key()
                while key == 'idle':
                    key = self.key()
                if key in ('up', 'down'):
                    selection.move(-1 if key == 'up' else 1)
                elif key == ' ' and multiple:
                    selection.toggle()
                elif key in ('activate', 'right'):
                    return selection.result()
                elif key in ('back', 'left'):
                    raise Cancelled

    def confirm(self, message):
        try:
            return self.choose(message, [(False, t('choice_no')), (True, t('choice_yes'))], default=False, radio=True)
        except Cancelled:
            return False

    def input(self, prompt):
        value, cursor = '', 0
        with self.prompt():
            while True:
                left, right = value[:cursor], value[cursor:]
                width = max(1, self.size()[0] - 3)
                while cells(left) > width:
                    left = left[1:]
                instructions = wrapped(prompt, self.size()[0] - 1)[:max(1, self.size()[1] - 3)]
                self.draw([(line, False) for line in instructions] +
                          [(left + '▏' + right, False), (t('input_keys'), False)])
                key = self.key()
                while key == 'idle':
                    key = self.key()
                if key == 'activate':
                    return value
                if key == 'back':
                    raise Cancelled
                if key == 'left':
                    cursor = max(0, cursor - 1)
                elif key == 'right':
                    cursor = min(len(value), cursor + 1)
                elif key == 'home':
                    cursor = 0
                elif key == 'end':
                    cursor = len(value)
                elif key == 'erase' and cursor:
                    value = value[:cursor-1] + value[cursor:]
                    cursor -= 1
                elif key == 'delete':
                    value = value[:cursor] + value[cursor+1:]
                elif len(key) == 1 and key.isprintable():
                    value = value[:cursor] + key + value[cursor:]
                    cursor += 1


def interactive(callback):
    """The controlling terminal also works when installation stdin is a pipe."""
    with open('/dev/tty', 'r+b', buffering=0) as terminal:
        screen = Screen(terminal)
        token = boundary.set(screen.before_output)
        try:
            return callback(screen)
        finally:
            screen.before_output()
            boundary.reset(token)


def confirm(message):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    return interactive(lambda ui: ui.confirm(message))


def language_options():
    return [('zh_cn', t('language_zh')), ('en_us', t('language_en'))]


def language(ui, current):
    return ui.choose(t('language_title'), language_options(), default=current, radio=True)
