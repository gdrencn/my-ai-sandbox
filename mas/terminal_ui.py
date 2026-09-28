"""Inline text-menu application; operations reuse the ordinary CLI backend."""
import json
import sys
from . import config, menu
from .core import Error
from .i18n import t, state


class UI:
    def __init__(self, view, manager):
        self.view = view
        self.manager = manager

    def choose(self, title, actions, default=None):
        return self.view.choose(title, [(key, t(label)) for key, label in actions], default=default)

    def guarded(self, callback):
        try:
            callback()
        except menu.Cancelled:
            print(t('cancelled'), flush=True)
        except config.ConfigError as exc:
            print(t(exc.key, **exc.values), file=sys.stderr, flush=True)
        except (Error, OSError) as exc:
            print(t('error', error=exc), file=sys.stderr, flush=True)

    def settings(self):
        while True:
            choice = self.view.choose(t('page_settings'), [('language', t('menu_language', language=config.get('language'))), ('back', t('menu_back'))])
            if choice == 'back':
                return
            def change_language():
                selected = menu.language(self.view, config.get('language'))
                config.set_value('language', selected)
                print(t('language_saved', language=selected), flush=True)
            self.guarded(change_language)

    def info(self, target):
        print(t('menu_info_title', target=target), flush=True)
        print(json.dumps(self.manager.info(target), indent=2), flush=True)
        try:
            self.view.choose(t('menu_info_title', target=target), [(None, t('menu_back'))])
        except menu.Cancelled:
            pass

    def enter(self, target):
        self.manager.enter(target)

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
                    print(t('menu_done' if deleted else 'cancelled'), flush=True)
                elif selected == 'export':
                    done = self.manager.export(target, self.view.input(t('export_file')), self.view.confirm)
                    print(t('menu_done' if done else 'cancelled'), flush=True)
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
                print(t('menu_empty'), flush=True)
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
        selected = 'management'
        while True:
            try:
                selected = self.choose(t('page_main'), [('management', 'page_management'), ('settings', 'page_settings'), ('exit', 'menu_exit')], selected)
            except menu.Cancelled:
                return
            if selected == 'exit':
                return
            self.guarded(self.management if selected == 'management' else self.settings)


def run(manager):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Error(t('menu_terminal'))
    menu.interactive(lambda view: UI(view, manager).loop())
