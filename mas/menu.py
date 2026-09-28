"""Shared terminal menus and input widgets; no lifecycle or configuration logic."""
import curses
from dataclasses import dataclass, field
import os
import sys
import unicodedata

from .i18n import t


class Cancelled(Exception):
    pass


def cells(text):
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1 for char in text)


@dataclass
class Selection:
    options: list
    index: int = 0
    multiple: bool = False
    checked: set = field(default_factory=set)

    def move(self, step):
        self.index = max(0, min(len(self.options) - 1, self.index + step))

    def toggle(self):
        value = self.options[self.index][0]
        self.checked.symmetric_difference_update({value})

    def result(self):
        return [value for value, _ in self.options if value in self.checked] if self.multiple else self.options[self.index][0]


def read_key(screen):
    key = screen.get_wch()
    special = {curses.KEY_UP: 'up', curses.KEY_DOWN: 'down', curses.KEY_LEFT: 'back',
               curses.KEY_RIGHT: 'activate', curses.KEY_ENTER: 'activate', curses.KEY_RESIZE: 'resize',
               curses.KEY_BACKSPACE: 'erase'}
    if key in special:
        return special[key]
    if key in ('\n', '\r'):
        return 'activate'
    if key in ('\x7f', '\b'):
        return 'erase'
    if key == '\x03':
        raise KeyboardInterrupt
    if key == '\x1b':
        # Some terminals send CSI arrows even after keypad application mode is enabled.
        sequence = ''
        screen.timeout(120)
        try:
            for _ in range(8):
                try:
                    char = screen.get_wch()
                except curses.error:
                    break
                if not isinstance(char, str):
                    break
                sequence += char
                if char.isalpha() or char == '~':
                    if sequence == 'O':
                        continue
                    break
        finally:
            screen.timeout(-1)
        return {'[A': 'up', '[B': 'down', '[C': 'activate', '[D': 'back',
                'OA': 'up', 'OB': 'down', 'OC': 'activate', 'OD': 'back', '': 'back'}.get(sequence, 'ignore')
    return key


class Screen:
    def __init__(self, screen):
        self.screen = screen
        self.screen.keypad(True)
        curses.curs_set(0)
        self.current = None
        self.message = ''

    def line(self, row, text, focused=False):
        height, width = self.screen.getmaxyx()
        if row < 0 or row >= height:
            return
        text = str(text).replace('\n', ' ')
        while text and cells(text) > max(0, width - 1):
            text = text[:-1]
        try:
            self.screen.addstr(row, 0, text, curses.A_REVERSE if focused else curses.A_NORMAL)
        except curses.error:
            pass

    def draw(self, title, selection, radio=False):
        self.current = (title, selection, radio)
        self.screen.clear()
        self.line(0, title)
        height = self.screen.getmaxyx()[0]
        count = max(1, height - 5)
        offset = max(0, selection.index - count + 1)
        for index in range(offset, min(len(selection.options), offset + count)):
            value, label = selection.options[index]
            focused = index == selection.index
            marker = ('☑' if value in selection.checked else '☐') if selection.multiple else ('●' if focused else '○') if radio else ''
            self.line(index - offset + 2, ('❯ ' if focused else '  ') + (marker + ' ' if marker else '') + label, focused)
        self.line(height - 2, t('menu_multi_keys' if selection.multiple else 'menu_keys'))
        self.line(height - 1, self.message)
        self.screen.refresh()

    def choose(self, title, options, default=None, multiple=False, checked=(), radio=False):
        index = next((i for i, (value, _) in enumerate(options) if value == default), 0)
        selection = Selection(options, index, multiple, set(checked))
        if not options:
            raise ValueError('Menu requires at least one option')
        while True:
            self.draw(title, selection, radio)
            key = read_key(self.screen)
            if key in ('up', 'down'):
                selection.move(-1 if key == 'up' else 1)
            elif key == ' ' and multiple:
                selection.toggle()
            elif key == 'activate':
                return selection.result()
            elif key == 'back':
                raise Cancelled

    def confirm(self, message):
        try:
            return self.choose(message, [(False, t('choice_no')), (True, t('choice_yes'))], default=False, radio=True)
        except Cancelled:
            return False

    def input(self, prompt):
        value = ''
        self.current = None
        try:
            curses.curs_set(1)
            while True:
                self.screen.clear()
                self.line(0, prompt)
                width = max(1, self.screen.getmaxyx()[1] - 2)
                visible = value
                while visible and cells(visible) > width:
                    visible = visible[1:]
                self.line(2, visible)
                self.line(self.screen.getmaxyx()[0] - 2, t('input_keys'))
                self.screen.move(min(2, self.screen.getmaxyx()[0] - 1), min(cells(visible), width))
                self.screen.refresh()
                key = read_key(self.screen)
                if key == 'activate':
                    return value
                if key == 'back':
                    raise Cancelled
                if key == 'erase':
                    value = value[:-1]
                elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                    value += key
        finally:
            curses.curs_set(0)

    def progress(self, message):
        self.message = message
        if self.current:
            self.draw(*self.current)
        else:
            self.line(self.screen.getmaxyx()[0] - 1, message)
            self.screen.refresh()


def interactive(callback):
    """Use the controlling terminal, including curl | bash installation."""
    saved = []
    try:
        with open('/dev/tty', 'r+b', buffering=0) as terminal:
            for fd in (0, 1):
                saved.append((fd, os.dup(fd)))
                os.dup2(terminal.fileno(), fd)
            return curses.wrapper(lambda window: callback(Screen(window)))
    finally:
        for fd, duplicate in saved:
            os.dup2(duplicate, fd)
            os.close(duplicate)


def confirm(message):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    return interactive(lambda ui: ui.confirm(message))


def language_options():
    return [('zh_cn', t('language_zh')), ('en_us', t('language_en'))]


def language(ui, current):
    return ui.choose(t('language_title'), language_options(), default=current, radio=True)
