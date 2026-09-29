"""Inline text-menu application; operations reuse the ordinary CLI backend."""
import sys
from . import config, menu
from .core import Error, ShellExitError
from .output import before_output
from .i18n import t, state
from .presentation import format_info


STOP_ALL = object()  # A control key cannot collide with a legal container name.


class LeaveMenu(Exception):
    def __init__(self, error=None):
        self.error = error


class UI:
    def __init__(self, view, manager):
        self.view = view
        self.manager = manager

    def write(self, message, error=False):
        before_output()
        print(message, file=sys.stderr if error else sys.stdout, flush=True)

    def choose(self, title, actions, default=None):
        return self.view.choose(title, [(key, t(label)) for key, label in actions], default=default)

    def present(self, title, callback, back=True):
        """One entry/result/return contract for actions and navigation sections."""
        self.view.heading(title)
        result = None
        failed = False
        try:
            result = callback()
        except menu.Cancelled:
            if back:
                self.write(t('cancelled'))
        except config.ConfigError as exc:
            failed = True
            self.write(t(exc.key, **exc.values), error=True)
        except (Error, OSError) as exc:
            failed = True
            self.write(t('error', error=exc), error=True)
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
                self.write(t('language_saved', language=selected))
            self.present(t('language_title'), change_language)

    def info(self, target):
        self.write(format_info(self.manager.info(target)))

    def enter(self, target):
        try:
            self.manager.enter(target, self.view.confirm)
        except ShellExitError as exc:
            raise LeaveMenu(exc) from exc
        raise LeaveMenu()

    def container(self, target):
        selected = 'info'
        actions = [(key, 'menu_' + key) for key in ('info', 'start', 'enter', 'stop', 'export', 'delete', 'mountedfs', 'mountfs', 'unmountfs', 'hardware', 'back')]
        while True:
            selected = self.choose(t('page_container', target=target), actions, selected)
            if selected == 'back':
                return
            if selected == 'hardware':
                self.present(t('page_hardware', target=target), lambda: self.hardware(target), back=False)
                continue
            deleted = False
            def action():
                nonlocal deleted
                if selected == 'info':
                    self.info(target)
                elif selected == 'mountfs':
                    path = self.view.input(t('fs_path_prompt'))
                    destination = self.manager.mountfs(target, path or None)
                    self.write(t('fs_mounted_at', path=destination))
                elif selected in ('mountedfs', 'unmountfs'):
                    from .presentation import show_mounts
                    entries = self.manager.mountedfs(target)
                    if selected == 'mountedfs' or not entries:
                        show_mounts(entries, self.write)
                    if selected == 'unmountfs' and entries:
                        status_column = any(e['status'] != 'mounted' for e in entries)
                        rows = menu.column_rows([(e['path'], menu.status_cell(state(e['status']), e['status'])) if status_column else (e['path'],) for e in entries])
                        path = self.view.choose(t('fs_unmount_select'), [(e['path'], row) for e, row in zip(entries, rows)] + [(None, t('menu_back'))])
                        if path is not None:
                            self.manager.unmountfs(target, path)
                            self.write(t('menu_done'))
                elif selected == 'enter':
                    self.enter(target)
                elif selected == 'delete':
                    deleted = self.manager.delete(target, self.view.confirm)
                    self.write(t('menu_done' if deleted else 'cancelled'))
                elif selected == 'export':
                    done = self.manager.export(target, self.view.input(t('export_file')), self.view.confirm)
                    self.write(t('menu_done' if done else 'cancelled'))
                else:
                    getattr(self.manager, selected)(target)
            self.present(t('page_action', action=t('menu_' + selected), target=target), action)
            if deleted:
                return

    def hardware(self, target):
        while True:
            status = self.manager.hardware(target)
            choices = []
            if status['available']:
                if not status.get('configured', True):
                    self.write(t('gpu_pending'))
                choices.append(('gpu', t('gpu_switch', value=t('state_enabled' if status['enabled'] else 'state_disabled'))))
            else:
                self.write(t('gpu_unavailable'))
            choices.append((None, t('menu_back')))
            if self.view.choose(t('page_hardware', target=target), choices, default='gpu' if status['available'] else None) is None:
                return
            def change():
                enabled = self.view.choose(t('gpu_choose'), [(True, t('state_enabled')), (False, t('state_disabled'))],
                                           default=status['enabled'], radio=True)
                self.manager.hardware(target, enabled)
            self.present(t('gpu_choose'), change)

    def containers(self):
        selected = None
        while True:
            items = self.manager.list()
            if not items:
                self.write(t('menu_empty'))
            rows = menu.column_rows([(item['name'], menu.status_cell(state(item['status']), item['status'])) for item in items])
            choices = [(item['name'], row) for item, row in zip(items, rows)]
            if len(items) > 1 and any(item['status'] != 'Stopped' for item in items):
                choices.append((STOP_ALL, t('menu_stop_all')))
            choices.append((None, t('menu_back')))
            selected = self.view.choose(t('page_list'), choices, default=selected if selected is not None else (items[0]['name'] if items else None))
            if selected is None:
                return
            if selected is STOP_ALL:
                self.present(t('menu_stop_all'), self.manager.stop_all)
            else:
                self.present(t('page_container', target=selected), lambda: self.container(selected), back=False)

    def loop(self):
        selected = 'list'
        actions = [(key, 'menu_' + key) for key in ('list', 'new', 'import')]
        actions += [('settings', 'page_settings'), ('exit', 'menu_exit')]
        while True:
            try:
                selected = self.choose(t('page_main'), actions, selected)
            except menu.Cancelled:
                return
            if selected == 'exit':
                return
            def action():
                if selected == 'list':
                    self.containers()
                elif selected == 'settings':
                    self.settings()
                elif selected == 'new':
                    target = self.view.input(t('new_target'))
                    image = self.view.input(t('new_image'))
                    self.manager.new(target, image or None)
                elif selected == 'import':
                    target = self.view.input(t('import_target'))
                    self.manager.import_container(target, self.view.input(t('backup_file')))
            title = t('page_settings' if selected == 'settings' else 'menu_' + selected)
            self.present(title, action, back=selected not in ('list', 'settings'))


def run(manager):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Error(t('menu_terminal'))
    try:
        menu.interactive(lambda view: UI(view, manager).loop())
    except LeaveMenu as done:
        if done.error:
            raise done.error
