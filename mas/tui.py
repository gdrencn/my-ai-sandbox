"""Paged terminal menus calling the same lifecycle functions as the CLI."""
import curses
import json
import sys
from . import config, menu
from .core import Error
from .i18n import t, state, progress_text
from .menu import cells


class UI:
    def __init__(self, screen, manager):
        self.screen = screen
        self.view = menu.Screen(screen)
        self.manager = manager

    def choose(self, title, actions, default=None):
        return self.view.choose(title, [(key, t(label)) for key, label in actions], default=default)

    def guarded(self, callback):
        try:
            callback()
        except menu.Cancelled:
            self.view.message = t('cancelled')
        except config.ConfigError as exc:
            self.view.message = t(exc.key, **exc.values)
        except (Error, OSError) as exc:
            self.view.message = t('error', error=exc)

    def settings(self):
        while True:
            choice = self.view.choose(t('page_settings'), [('language', t('menu_language', language=config.get('language'))), ('back', t('menu_back'))])
            if choice == 'back':
                return
            def change_language():
                selected = menu.language(self.view, config.get('language'))
                config.set_value('language', selected)
                self.view.message = t('language_saved', language=selected)
            self.guarded(change_language)

    def info(self, target):
        lines = json.dumps(self.manager.info(target), indent=2).splitlines()
        offset = 0
        while True:
            self.screen.clear()
            self.view.line(0, t('tui_info', target=target))
            height = self.screen.getmaxyx()[0]
            for row, line in enumerate(lines[offset:offset + max(1, height - 2)], 1):
                self.view.line(row, line)
            self.screen.refresh()
            key = menu.read_key(self.screen)
            if key == 'back':
                return
            if key == 'down':
                offset = min(offset + 1, max(0, len(lines) - 1))
            if key == 'up':
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
            # The CLI exit menu owns a nested curses session. Re-establish the
            # outer session's input mode after its wrapper restores the shell.
            curses.noecho()
            curses.cbreak()
            self.screen.keypad(True)
            curses.curs_set(0)
            self.screen.clear()
            self.screen.refresh()

    def container(self, target):
        selected = 'info'
        actions = [(key, 'menu_' + key) for key in ('info', 'start', 'enter', 'stop', 'export', 'delete', 'back')]
        while True:
            selected = self.choose(t('page_container', target=target), actions, selected)
            if selected == 'back':
                return
            deleted = False
            def action():
                nonlocal deleted
                if selected == 'info':
                    self.info(target)
                elif selected == 'enter':
                    self.enter(target)
                elif selected == 'delete':
                    deleted = self.manager.delete(target, self.view.confirm)
                    self.view.message = t('menu_done' if deleted else 'cancelled')
                elif selected == 'export':
                    done = self.manager.export(target, self.view.input(t('export_file')), self.view.confirm)
                    self.view.message = t('menu_done' if done else 'cancelled')
                else:
                    getattr(self.manager, selected)(target)
            self.guarded(action)
            if deleted:
                return

    def containers(self):
        selected = None
        while True:
            items = self.manager.list()
            if not items:
                self.view.message = t('menu_empty')
            selected = self.view.choose(t('page_list'), [(item['name'], item['name'] + '  ' + state(item['status'])) for item in items] + [(None, t('menu_back'))], default=selected or (items[0]['name'] if items else None))
            if selected is None:
                return
            self.guarded(lambda: self.container(selected))

    def management(self):
        selected = 'list'
        actions = [(key, 'menu_' + key) for key in ('list', 'new', 'import', 'stop_all', 'back')]
        while True:
            selected = self.choose(t('page_management'), actions, selected)
            if selected == 'back':
                return
            def action():
                if selected == 'list':
                    self.containers()
                elif selected == 'new':
                    target = self.view.input(t('new_target'))
                    image = self.view.input(t('new_image'))
                    self.manager.new(target, image or None)
                elif selected == 'import':
                    target = self.view.input(t('import_target'))
                    self.manager.import_container(target, self.view.input(t('backup_file')))
                else:
                    self.manager.stop_all()
            self.guarded(action)

    def loop(self):
        previous = self.manager.report
        self.manager.report = lambda event: self.view.progress(progress_text(event))
        try:
            selected = 'management'
            while True:
                try:
                    selected = self.choose(t('page_main'), [('management', 'page_management'), ('settings', 'page_settings'), ('exit', 'menu_exit')], selected)
                except menu.Cancelled:
                    return
                if selected == 'exit':
                    return
                self.guarded(self.management if selected == 'management' else self.settings)
        finally:
            self.manager.report = previous


def run(manager):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Error(t('tui_terminal'))
    try:
        curses.wrapper(lambda screen: UI(screen, manager).loop())
    except curses.error as exc:
        raise Error(t('tui_failed', error=exc)) from exc
