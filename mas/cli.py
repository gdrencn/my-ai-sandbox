"""Argument handling and terminal presentation; lifecycle logic lives in core."""

import json

import sys

from . import __version__
from . import config
from .core import Error, LXD, Manager
from .diagnostics import diagnostic_lines

from .i18n import t, state, progress_text, Parser


def progress(event):
    print(progress_text(event), file=sys.stderr, flush=True)
    if not event.get("native_failure"):
        for line in diagnostic_lines(event.get("native_stdout", ""), event.get("native_stderr", "")):
            print(line, file=sys.stderr, flush=True)


def parser():
    result = Parser(prog="mas", description=t('cli_description'))
    result.add_argument("--version", action="version", version=__version__, help=t("help_version"))
    result.add_argument("--timeout", type=int, default=600, help=t('help_timeout'))
    commands = result.add_subparsers(dest="command")
    settings = commands.add_parser("config", help=t("help_config"))
    actions = settings.add_subparsers(dest="config_action")
    for action in ("get", "set"):
        item = actions.add_parser(action)
        item.add_argument("key", choices=["language"])
        if action == "set":
            item.add_argument("value", choices=config.LANGUAGES)
    for name in ("new", "list", "start", "stop", "delete", "info", "import", "export", "enter"):
        command = commands.add_parser(name)
        if name != "list":
            command.add_argument("target", metavar="TARGET", **({"nargs": "?"} if name == "stop" else {}))
        if name in ("delete", "export", "enter"):
            consent = command.add_mutually_exclusive_group()
            consent.add_argument("--yes", dest="consent", action="store_const", const=True, help=t("help_yes"))
            consent.add_argument("--no", dest="consent", action="store_const", const=False, help=t("help_no"))
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
        ask = input if getattr(args, "consent", None) is None else lambda _: args.consent
        manager = manager or Manager(LXD(timeout=args.timeout), report=progress)
        if args.command is None:
            from .terminal_ui import run
            run(manager)
        elif args.command == "list":
            for item in manager.list():
                print(f"{item['name']}\t{state(item['status'])}")
        elif args.command == "info":
            print(json.dumps(manager.info(args.target), indent=2))
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
        print(t(exc.key, **exc.values), file=sys.stderr)
        return 1
    except (Error, OSError) as exc:
        print(f"mas: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n" + t("interrupted"), file=sys.stderr)
        return 130
