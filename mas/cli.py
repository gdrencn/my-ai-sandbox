"""Argument handling and terminal presentation; lifecycle logic lives in core."""

import json

import sys

from . import __version__
from . import config
from .core import Error, LXD, Manager
from .presentation import Progress, show_mounts, format_info

from .i18n import t, state, Parser


def parser():
    result = Parser(prog="mas", description=t('cli_description'))
    result.add_argument("--version", action="version", version=__version__, help=t("help_version"))
    result.add_argument("--timeout", type=int, default=600, help=t('help_timeout'))
    commands = result.add_subparsers(dest="command")
    hardware = commands.add_parser("hardware", help=t("help_hardware"))
    hardware.add_argument("target", metavar="TARGET")
    hardware.add_argument("item", nargs="?", choices=["gpu"])
    hardware.add_argument("value", nargs="?", choices=["on", "off"])
    settings = commands.add_parser("config", help=t("help_config"))
    actions = settings.add_subparsers(dest="config_action")
    for action in ("get", "set"):
        item = actions.add_parser(action)
        item.add_argument("key", choices=["language"])
        if action == "set":
            item.add_argument("value", choices=config.LANGUAGES)
    for name in ("new", "list", "start", "stop", "delete", "info", "import", "export", "enter", "mountfs", "unmountfs", "mountedfs"):
        command = commands.add_parser(name)
        if name != "list":
            command.add_argument("target", metavar="TARGET", **({"nargs": "?"} if name == "stop" else {}))
        if name in ("delete", "export", "enter"):
            consent = command.add_mutually_exclusive_group()
            consent.add_argument("--yes", dest="consent", action="store_const", const=True, help=t("help_yes"))
            consent.add_argument("--no", dest="consent", action="store_const", const=False, help=t("help_no"))
        if name in ("mountfs", "unmountfs"):
            command.add_argument("path", metavar="PATH", nargs="?", help=t("help_fs_path"))
        if name == "stop":
            command.add_argument("--all", action="store_true", help=t('help_all'))
        if name == "new":
            command.add_argument("--image", help=t('help_image'))
        if name in ("import", "export"):
            command.add_argument("file", metavar="FILE")
    return result


def main(argv=None, manager=None):
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.timeout < 300:
        arguments.error(t('cli_timeout'))
    if args.command == "stop" and bool(args.target) == args.all:
        arguments.error(t('cli_stop_args'))
    progress = Progress()
    try:
        if args.command == "config":
            if args.config_action == "set":
                config.set_value(args.key, args.value)
                print(t("language_saved", language=args.value))
            elif args.config_action == "get":
                print(config.get(args.key))
            else:
                print(json.dumps(config.load(), ensure_ascii=False, indent=2))
            return 0
        from .menu import confirm as ask_menu
        ask = ask_menu if getattr(args, "consent", None) is None else lambda _: args.consent
        manager = manager or Manager(LXD(timeout=args.timeout, diagnostic=progress.output.keep), report=progress)
        if args.command is None:
            from .terminal_ui import run
            run(manager)
        elif args.command == "hardware":
            result = manager.hardware(args.target, None if args.value is None else args.value == "on")
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "list":
            for item in manager.list():
                print(f"{item['name']}\t{state(item['status'])}")
        elif args.command == "info":
            print(format_info(manager.info(args.target)))
        elif args.command in ("mountfs", "unmountfs"):
            result = getattr(manager, args.command)(args.target, args.path)
            print(t("fs_mounted_at", path=result) if args.command == "mountfs" else t("menu_done"))
        elif args.command == "mountedfs":
            show_mounts(manager.mountedfs(args.target))
        elif args.command == "new":
            manager.new(args.target, args.image)
        elif args.command == "import":
            manager.import_container(args.target, args.file)
        elif args.command == "export":
            if not manager.export(args.target, args.file, ask):
                print(t('cancelled'))
        elif args.command == "delete":
            if not manager.delete(args.target, ask):
                print(t('cancelled'))
        elif args.command == "enter":
            manager.enter(args.target, ask)
        elif args.command == "stop" and args.all:
            manager.stop_all()
        else:
            getattr(manager, args.command)(args.target)
        return 0
    except config.ConfigError as exc:
        progress.output.keep(t(exc.key, **exc.values))
        return 1
    except (Error, OSError) as exc:
        progress.output.keep(f"mas: {exc}")
        return 1
    except KeyboardInterrupt:
        progress.output.keep(t("interrupted"))
        return 130
    finally:
        progress.output.clear()
