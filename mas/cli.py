"""Argument handling and terminal presentation; lifecycle logic lives in core."""

import argparse
import json
import sys

from . import __version__
from .core import Error, LXD, Manager


def progress(event):
    print(f"[{event['status']}] {event['action']} {event['target']}: "
          f"{event['observation']} — waited {event['elapsed']:.1f}s", file=sys.stderr, flush=True)


def parser():
    result = argparse.ArgumentParser(prog="mas", description="Manage your LXD containers. No command opens the TUI.")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--timeout", type=int, default=600, help="operation timeout in seconds (minimum 300, default 600)")
    commands = result.add_subparsers(dest="command")
    for name in ("new", "list", "start", "stop", "delete", "info", "import", "export", "enter"):
        command = commands.add_parser(name)
        if name != "list":
            command.add_argument("target", metavar="TARGET", **({"nargs": "?"} if name == "stop" else {}))
        if name == "stop":
            command.add_argument("--all", action="store_true", help="stop all mas-managed containers")
        if name == "new":
            command.add_argument("--image", help="override the image matching the host Ubuntu release")
        if name in ("import", "export"):
            command.add_argument("file", metavar="FILE")
    return result


def main(argv=None, manager=None):
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.timeout < 300:
        arguments.error("--timeout must be at least 300 seconds")
    if args.command == "stop" and bool(args.target) == args.all:
        arguments.error("stop requires either TARGET or --all, but not both")
    try:
        manager = manager or Manager(LXD(timeout=args.timeout), report=progress)
        if args.command is None:
            from .tui import run
            run(manager)
        elif args.command == "list":
            for item in manager.list():
                print(f"{item['name']}\t{item['status']}")
        elif args.command == "info":
            print(json.dumps(manager.info(args.target), indent=2))
        elif args.command == "new":
            manager.new(args.target, args.image)
        elif args.command == "import":
            manager.import_container(args.target, args.file)
        elif args.command == "export":
            if not manager.export(args.target, args.file):
                print("Cancelled.")
        elif args.command == "delete":
            if not manager.delete(args.target):
                print("Cancelled.")
        elif args.command == "stop" and args.all:
            manager.stop_all()
        else:
            getattr(manager, args.command)(args.target)
        return 0
    except (Error, OSError) as exc:
        print(f"mas: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Any LXD operation already submitted may still be running.", file=sys.stderr)
        return 130
