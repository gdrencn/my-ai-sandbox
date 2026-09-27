"""Standard-library curses UI. Every action calls the shared Manager."""

import curses
import json
import sys

from .core import Error


class UI:
    def __init__(self, screen, manager):
        self.screen = screen
        self.manager = manager
        self.items = []
        self.selected = 0
        self.message = "Ready"

    def line(self, row, text, selected=False):
        height, width = self.screen.getmaxyx()
        if row >= height:
            return
        try:
            self.screen.addnstr(row, 0, str(text).replace("\n", " "), max(0, width - 1),
                                curses.A_REVERSE if selected else curses.A_NORMAL)
        except curses.error:
            pass

    def draw(self, refresh=True):
        self.screen.erase()
        self.line(0, "my-ai-sandbox | managed containers")
        self.line(1, "n:new  s:start  t:stop  a:stop all  e:enter  d:delete  i:info")
        self.line(2, "m:import  x:export  r:refresh  q:quit | arrows:select")
        height = self.screen.getmaxyx()[0]
        count = max(1, height - 6)
        offset = max(0, self.selected - count + 1)
        for row, item in enumerate(self.items[offset:offset + count], 4):
            self.line(row, f"{item['name']:<40} {item['status']}", row - 4 + offset == self.selected)
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
            value = self.screen.getstr(row, min(len(prompt), self.screen.getmaxyx()[1] - 2), 1024)
            return value.decode("utf-8")
        finally:
            curses.noecho()
            curses.curs_set(0)

    def progress(self, event):
        self.message = (f"{event['action']} {event['target']} {event['status']}: "
                        f"{event['observation']}; waited {event['elapsed']:.1f}s")
        self.draw()

    def info(self, target):
        lines = json.dumps(self.manager.info(target), indent=2).splitlines()
        offset = 0
        while True:
            self.screen.erase()
            height = self.screen.getmaxyx()[0]
            self.line(0, f"Info: {target} | arrows:scroll q:back")
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
                    if key == ord("n"):
                        target = self.ask("New TARGET: ")
                        image = self.ask("Image (Enter = host Ubuntu): ")
                        self.manager.new(target, image or None)
                    elif key == ord("m"):
                        target = self.ask("Import TARGET: ")
                        path = self.ask("Backup FILE: ")
                        self.manager.import_container(target, path)
                    elif key == ord("a"):
                        self.manager.stop_all()
                    elif key == ord("r"):
                        pass
                    elif key in map(ord, "stedix"):
                        if not self.items:
                            raise Error("Select a container first.")
                        target = self.items[self.selected]["name"]
                        if key == ord("s"):
                            self.manager.start(target)
                        elif key == ord("t"):
                            self.manager.stop(target)
                        elif key == ord("e"):
                            self.enter(target)
                        elif key == ord("d"):
                            if not self.manager.delete(target, self.ask):
                                self.message = "Cancelled."
                        elif key == ord("i"):
                            self.info(target)
                        elif key == ord("x"):
                            if not self.manager.export(target, self.ask("Export FILE: "), self.ask):
                                self.message = "Cancelled."
                    else:
                        continue
                    self.refresh()
                except (Error, OSError) as exc:
                    self.message = "Error: " + str(exc)
        finally:
            self.manager.report = previous


def run(manager):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Error("The TUI needs an interactive terminal. Use mas --help for CLI commands.")
    try:
        curses.wrapper(lambda screen: UI(screen, manager).loop())
    except curses.error as exc:
        raise Error(f"Cannot open the TUI: {exc}") from exc
