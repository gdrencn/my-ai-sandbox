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


class ReturnToMenu(Exception):
    """Skip the ordinary operation-result page after a terminal decision."""
    pass


class UI:
    def __init__(self, view, manager):
        self.view = view
        self.manager = manager
        self.terminal_failed = False

    def write(self, message, error=False):
        before_output()
        print(message, file=sys.stderr if error else sys.stdout, flush=True)

    def choose(self, title, actions, default=None, **options):
        return self.view.choose(title, [(key, t(label)) for key, label in actions], default=default, **options)

    def present(self, title, callback, back=True):
        """Actions own entry headings; navigation selectors own their titles."""
        if back:
            self.view.heading(title)
        result = None
        failure = None
        try:
            result = callback()
        except menu.Cancelled:
            if back:
                self.write(t('cancelled'))
        except config.ConfigError as exc:
            failure = t(exc.key, **exc.values)
        except (Error, OSError) as exc:
            failure = t('error', error=exc)
        if failure is not None:
            if not back:
                self.view.heading(title)
            self.write(failure, error=True)
        if back or failure is not None:
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
        instance = self.manager.info(target)
        record = self.manager.gpu.record(instance)
        gpu = t('state_enabled' if record['enabled'] else 'state_disabled') if record else t('gpu_unconfigured')
        summary = [t('info_name', name=instance['name']),
                   t('info_state', status=state(instance['status'])), t('info_gpu', value=gpu)]
        selected = 'configuration'
        while True:
            selected = self.choose(t('menu_info_title', target=target),
                [('configuration', 'menu_configuration'), ('back', 'menu_back')], selected,
                description=summary)
            if selected == 'back':
                return
            self.present(t('page_configuration', target=target), lambda: self.write(format_info(instance)))

    def enter(self, target):
        try:
            choice = self.manager.enter(target, lambda message: menu.post_terminal(message, self.view))
        except ShellExitError as exc:
            if exc.return_to_menu:
                self.write(t('error', error=exc), error=True)
                self.terminal_failed = True
                raise ReturnToMenu() from exc
            raise LeaveMenu(exc) from exc
        if choice == 'menu':
            raise ReturnToMenu()
        raise LeaveMenu()

    def container(self, target):
        selected = 'info'
        actions = [(key, 'menu_' + key) for key in ('info', 'start', 'enter', 'stop', 'restart', 'export', 'delete', 'filesystem', 'hardware', 'back')]
        while True:
            selected = self.choose(t('page_container', target=target), actions, selected)
            if selected == 'back':
                return
            if selected in ('info', 'filesystem', 'hardware'):
                title = t('menu_info_title' if selected == 'info' else 'page_' + selected, target=target)
                self.present(title, lambda: getattr(self, selected)(target), back=False)
                continue
            deleted = False
            def action():
                nonlocal deleted
                if selected == 'enter':
                    self.enter(target)
                elif selected == 'delete':
                    deleted = self.manager.delete(target, self.view.confirm)
                    self.write(t('menu_done' if deleted else 'cancelled'))
                elif selected == 'export':
                    done = self.manager.export(target, self.view.input(t('export_file')), self.view.confirm)
                    self.write(t('menu_done' if done else 'cancelled'))
                else:
                    getattr(self.manager, selected)(target)
            try:
                self.present(t('page_action', action=t('menu_' + selected), target=target), action)
            except ReturnToMenu:
                continue
            if deleted:
                return

    def filesystem(self, target):
        selected = 'mountedfs'
        actions = [(key, 'menu_' + key) for key in ('mountedfs', 'mountfs', 'unmountfs', 'back')]
        while True:
            selected = self.choose(t('page_filesystem', target=target), actions, selected)
            if selected == 'back':
                return
            def action():
                if selected == 'mountfs':
                    self.write(t('fs_path_help'))
                    path = self.view.input(t('fs_path_prompt'))
                    destination = self.manager.mountfs(target, path or None)
                    self.write(t('fs_mounted_at', path=destination))
                    return
                from .presentation import show_mounts
                entries = self.manager.mountedfs(target)
                if selected == 'mountedfs' or not entries:
                    show_mounts(entries, self.write)
                if selected == 'unmountfs' and entries:
                    status_column = any(e['status'] != 'mounted' for e in entries)
                    rows = menu.column_rows([(e['path'], menu.status_cell(state(e['status']), e['status']))
                                             if status_column else (e['path'],) for e in entries])
                    path = self.view.choose(t('fs_unmount_select'),
                        [(e['path'], row) for e, row in zip(entries, rows)] + [(None, t('menu_back'))])
                    if path is not None:
                        self.manager.unmountfs(target, path)
                        self.write(t('menu_done'))
                    else:
                        self.write(t('cancelled'))
            self.present(t('page_action', action=t('menu_' + selected), target=target), action)

    def hardware(self, target):
        status = None
        while True:
            if status is None:
                status = self.manager.hardware(target)
            choices = []
            if status['available']:
                choices.append(('gpu', t('gpu_switch', value=t('state_enabled' if status['enabled'] else 'state_disabled'))))
            notice = ([t('gpu_pending')] if not status.get('configured', True) else []) if status['available'] else [t('gpu_unavailable')]
            choices.append((None, t('menu_back')))
            if self.view.choose(t('page_hardware', target=target), choices,
                                default='gpu' if status['available'] else None, description=notice) is None:
                return
            def change():
                nonlocal status
                enabled = self.view.choose(t('gpu_choose'), [(True, t('state_enabled')), (False, t('state_disabled'))],
                                           default=status['enabled'], radio=True)
                capability = status
                try:
                    record = self.manager.hardware(target, enabled, capability=capability)
                except (Error, OSError):
                    # Configuration may have changed before the failure. Observe it
                    # again, without repeating host discovery for this menu flow.
                    status = None
                    try:
                        status = self.manager.hardware(target, capability=capability)
                    except (Error, OSError) as refresh_error:
                        self.write(t('error', error=refresh_error), error=True)
                    raise
                status = {**capability, 'enabled': record['enabled'],
                          'configured': True, 'resources': record}
            self.present(t('gpu_choose'), change)
            if status is None:
                return

    def containers(self):
        selected = None
        while True:
            items = self.manager.list()
            rows = menu.column_rows([(item['name'], menu.status_cell(state(item['status']), item['status'])) for item in items])
            choices = [(item['name'], row) for item, row in zip(items, rows)]
            if len(items) > 1 and any(item['status'] != 'Stopped' for item in items):
                choices.append((STOP_ALL, t('menu_stop_all')))
            choices.append((None, t('menu_back')))
            selected = self.view.choose(t('page_list'), choices,
                default=selected if selected is not None else (items[0]['name'] if items else None),
                description=[] if items else [t('menu_empty')])
            if selected is None:
                return
            if selected is STOP_ALL:
                self.present(t('menu_stop_all'), self.manager.stop_all)
            else:
                self.present(t('page_container', target=selected), lambda: self.container(selected), back=False)

    def migration(self):
        items = self.manager.legacy_list()
        if not items:
            self.view.choose(t('menu_migrate'), [(None, t('menu_back'))],
                             description=[t('migration_help'), t('migration_empty')])
            return
        rows = menu.column_rows([(i['name'], menu.status_cell(state(i['status']), i['status'])) for i in items])
        target = self.view.choose(t('menu_migrate'), [(i['name'], row) for i, row in zip(items, rows)]
                                  + [(None, t('menu_back'))], default=items[0]['name'],
                                  description=[t('migration_help')])
        if target is None:
            return
        def migrate():
            done = self.manager.migrate(target, self.view.confirm)
            self.write(t('menu_done' if done else 'cancelled'))
        self.present(t('page_action', action=t('menu_migrate'), target=target), migrate)

    def loop(self):
        selected = 'list'
        actions = [(key, 'menu_' + key) for key in ('list', 'new', 'import', 'migrate')]
        actions += [('settings', 'page_settings'), ('exit', 'menu_exit')]
        while True:
            try:
                selected = self.choose(t('page_main'), actions, selected, cancel='exit')
            except menu.Cancelled:
                return
            if selected == 'exit':
                return
            def action():
                if selected == 'list':
                    self.containers()
                elif selected == 'settings':
                    self.settings()
                elif selected == 'migrate':
                    self.migration()
                elif selected == 'new':
                    target = self.view.input(t('new_target'))
                    image = self.view.input(t('new_image'))
                    self.manager.new(target, image or None)
                elif selected == 'import':
                    target = self.view.input(t('import_target'))
                    self.manager.import_container(target, self.view.input(t('backup_file')))
            title = t('page_settings' if selected == 'settings' else 'menu_' + selected)
            self.present(title, action, back=selected not in ('list', 'settings', 'migrate'))


def run(manager, target=None):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Error(t('menu_terminal'))
    ui = None
    try:
        def application(view):
            nonlocal ui
            ui = UI(view, manager)
            if target is not None:
                ui.present(t('page_container', target=target), lambda: ui.container(target), back=False)
            ui.loop()
        menu.interactive(application)
    except LeaveMenu as done:
        if done.error:
            raise done.error
    return 1 if ui is not None and ui.terminal_failed else 0
