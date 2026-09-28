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

    def present(self, title, callback, back=True):
        """One entry/result/return contract for actions and navigation sections."""
        print('\n' + title + '\n', flush=True)
        result = None
        failed = False
        try:
            result = callback()
        except menu.Cancelled:
            if back:
                print(t('cancelled'), flush=True)
        except config.ConfigError as exc:
            failed = True
            print(t(exc.key, **exc.values), file=sys.stderr, flush=True)
        except (Error, OSError) as exc:
            failed = True
            print(t('error', error=exc), file=sys.stderr, flush=True)
        if back or failed:
            try:
                self.view.choose(t('page_result'), [(None, t('menu_back'))])
            except menu.Cancelled:
                pass
        return result

    def settings(self):
        while True:
            choice = self.view.choose(t('page_settings'), [('language', t('menu_language', language=config.get('language'))), ('back', t('menu_back'))])
            if choice == 'back':
                return
            def change_language():
                selected = menu.language(self.view, config.get('language'))
                config.set_value('language', selected)
                print(t('language_saved', language=selected), flush=True)
            self.present(t('language_title'), change_language)

    def info(self, target):
        print(json.dumps(self.manager.info(target), indent=2), flush=True)

    def enter(self, target):
        self.manager.enter(target)

    def container(self, target):
        selected = 'info'
        actions = [(key, 'menu_' + key) for key in ('info', 'start', 'enter', 'stop', 'export', 'delete', 'mountedfs', 'mountfs', 'unmountfs', 'back')]
        while True:
            selected = self.choose(t('page_container', target=target), actions, selected)
            if selected == 'back':
                return
            deleted = False
            def action():
                nonlocal deleted
                if selected == 'info':
                    self.info(target)
                elif selected == 'mountfs':
                    path = self.view.input(t('fs_path_prompt'))
                    destination = self.manager.mountfs(target, path or None)
                    print(t('fs_mounted_at', path=destination), flush=True)
                elif selected in ('mountedfs', 'unmountfs'):
                    from .cli import show_mounts
                    entries = self.manager.mountedfs(target)
                    show_mounts(entries)
                    if selected == 'unmountfs' and entries:
                        path = self.view.choose(t('fs_unmount_select'), [(e['path'], e['path']) for e in entries] + [(None, t('menu_back'))])
                        if path is not None:
                            self.manager.unmountfs(target, path)
                            print(t('menu_done'), flush=True)
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
            self.present(t('page_action', action=t('menu_' + selected), target=target), action)
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
            self.present(t('page_container', target=selected), lambda: self.container(selected), back=False)

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
            self.present(t('menu_' + selected), action, back=selected != 'list')

    def loop(self):
        selected = 'management'
        while True:
            try:
                selected = self.choose(t('page_main'), [('management', 'page_management'), ('settings', 'page_settings'), ('exit', 'menu_exit')], selected)
            except menu.Cancelled:
                return
            if selected == 'exit':
                return
            self.present(t('page_' + selected), self.management if selected == 'management' else self.settings, back=False)


def run(manager):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Error(t('menu_terminal'))
    menu.interactive(lambda view: UI(view, manager).loop())
