"""Standard-library curses UI. Every action calls the shared Manager."""

import curses
import json

import sys
import unicodedata

from . import config

from .core import Error

from .i18n import t, state, progress_text


def cells(text):
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


class UI:
    def __init__(self, screen, manager):
        self.screen = screen
        self.manager = manager
        self.items = []
        self.selected = 0
        self.message = t('ready')

    def line(self, row, text, selected=False):
        height, width = self.screen.getmaxyx()
        if row >= height:
            return
        try:
            text = str(text).replace("\n", " ")
            while text and cells(text) > max(0, width - 1):
                text = text[:-1]
            self.screen.addstr(row, 0, text, curses.A_REVERSE if selected else curses.A_NORMAL)
        except curses.error:
            pass

    def draw(self, refresh=True):
        self.screen.erase()
        self.line(0, t('tui_title'))
        self.line(1, t('tui_keys1'))
        self.line(2, t("tui_keys2"))
        height = self.screen.getmaxyx()[0]
        count = max(1, height - 6)
        offset = max(0, self.selected - count + 1)
        for row, item in enumerate(self.items[offset:offset + count], 4):
            self.line(row, f"{item['name']:<40} {state(item['status'])}", row - 4 + offset == self.selected)
        self.line(height - 1, self.message)
        if refresh:
            self.screen.refresh()

    def refresh(self):
        self.items = self.manager.list()
        self.selected = min(self.selected, max(0, len(self.items) - 1))

    def ask(self, prompt):
        self.screen.clear()
        self.draw(refresh=False)
        row = self.screen.getmaxyx()[0] - 1
        self.screen.move(row, 0)
        self.screen.clrtoeol()
        self.line(row, prompt)
        self.screen.refresh()
        curses.echo()
        try:
            curses.curs_set(1)
            value = self.screen.getstr(row, min(cells(prompt), self.screen.getmaxyx()[1] - 2), 1024)
            return value.decode("utf-8")
        finally:
            curses.noecho()
            curses.curs_set(0)

    def progress(self, event):
        self.message = progress_text(event)
        self.draw()

    def settings(self):
        while True:
            self.screen.erase()
            self.line(0, t("settings_title"))
            self.line(2, t("settings_language", language=config.get("language")))
            self.screen.refresh()
            key = self.screen.getch()
            if key in (ord("q"), 27):
                self.message = t("ready")
                return
            if key in (ord("1"), ord("2")):
                language = "en_us" if key == ord("1") else "zh_cn"
                config.set_value("language", language)

    def info(self, target):
        lines = json.dumps(self.manager.info(target), indent=2).splitlines()
        offset = 0
        while True:
            self.screen.erase()
            height = self.screen.getmaxyx()[0]
            self.line(0, t("tui_info", target=target))
            for row, line in enumerate(lines[offset:offset + max(1, height - 2)], 1):
                self.line(row, line)
            self.screen.refresh()
            key = self.screen.getch()
            if key in (ord("q"), 27):
                return
            if key == curses.KEY_DOWN:
                offset = min(offset + 1, max(0, len(lines) - 1))
            if key == curses.KEY_UP:
                offset = max(0, offset - 1)

    def enter(self, target):
        curses.def_prog_mode()
        curses.endwin()
        previous = self.manager.report
        from .cli import progress
        self.manager.report = progress
        try:
            self.manager.enter(target)
        finally:
            self.manager.report = previous
            curses.reset_prog_mode()
            self.screen.clear()
            self.screen.refresh()

    def loop(self):
        curses.curs_set(0)
        self.screen.keypad(True)
        previous = self.manager.report
        self.manager.report = self.progress
        try:
            self.refresh()
            while True:
                self.draw()
                key = self.screen.getch()
                if key == ord("q"):
                    return
                if key in (curses.KEY_DOWN, curses.KEY_UP):
                    self.selected = max(0, min(len(self.items) - 1,
                                              self.selected + (1 if key == curses.KEY_DOWN else -1)))
                    continue
                try:
                    if key == ord("c"):
                        self.settings()
                    elif key == ord("n"):
                        target = self.ask(t('new_target'))
                        image = self.ask(t('new_image'))
                        self.manager.new(target, image or None)
                    elif key == ord("m"):
                        target = self.ask(t('import_target'))
                        path = self.ask(t('backup_file'))
                        self.manager.import_container(target, path)
                    elif key == ord("a"):
                        self.manager.stop_all()
                    elif key == ord("r"):
                        pass
                    elif key in map(ord, "stedix"):
                        if not self.items:
                            raise Error(t('select_container'))
                        target = self.items[self.selected]["name"]
                        if key == ord("s"):
                            self.manager.start(target)
                        elif key == ord("t"):
                            self.manager.stop(target)
                        elif key == ord("e"):
                            self.enter(target)
                        elif key == ord("d"):
                            if not self.manager.delete(target, self.ask):
                                self.message = t('cancelled')
                        elif key == ord("i"):
                            self.info(target)
                        elif key == ord("x"):
                            if not self.manager.export(target, self.ask(t('export_file')), self.ask):
                                self.message = t('cancelled')
                    else:
                        continue
                    self.refresh()
                except config.ConfigError as exc:
                    self.message = t(exc.key, **exc.values)
                except (Error, OSError) as exc:
                    self.message = t("error", error=exc)
        finally:
            self.manager.report = previous


def run(manager):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Error(t('tui_terminal'))
    try:
        curses.wrapper(lambda screen: UI(screen, manager).loop())
    except curses.error as exc:
        raise Error(t("tui_failed", error=exc)) from exc
