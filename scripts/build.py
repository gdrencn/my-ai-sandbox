#!/usr/bin/env python3
"""Build architecture-independent zipapps without pip or external tools."""

import hashlib
import argparse
import json
import shlex
from pathlib import Path
import shutil
import tempfile
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stable', action='store_true', help='Build product and installer without test files.')
    args = parser.parse_args(argv)
    DIST.mkdir(exist_ok=True)
    messages = json.loads((ROOT / "mas/locales/zh_cn.json").read_text())
    installer = (ROOT / "scripts/install.template.sh").read_text()
    for token, key in {"LANGUAGE_TITLE": "language_title", "LANGUAGE_ZH": "language_zh",
                       "LANGUAGE_EN": "language_en", "LANGUAGE_KEYS": "menu_keys",
                       "LANGUAGE_TERMINAL_REQUIRED": "language_terminal_required", "CANCELLED": "cancelled"}.items():
        value = messages[key].format(action=messages['menu_cancel']) if key == 'menu_keys' else messages[key]
        installer = installer.replace("@" + token + "@", shlex.quote(value))
    from mas.text import cells
    minimum = max(cells(messages['language_title']), cells(messages['language_zh']) + 6,
                  cells(messages['language_en']) + 6,
                  cells(messages['menu_keys'].format(action=messages['menu_cancel']))) + 1
    installer = installer.replace('@LANGUAGE_MIN_WIDTH@', str(minimum))
    installer = installer.replace('@BOOTSTRAP_TERMINAL_NARROW@',
        shlex.quote(messages['bootstrap_terminal_narrow'].format(columns=minimum)))
    installer = installer.replace('@DEPENDENCIES@', (ROOT / 'mas/dependencies.sh').read_text())
    installer = installer.replace('@SOURCE_BRANCH@', 'release' if args.stable else 'main')
    installer = installer.replace('@CHANNEL_ARGUMENTS@', '--channel stable' if args.stable else '')
    for language, suffix in (('zh_cn', 'ZH'), ('en_us', 'EN')):
        catalog = json.loads((ROOT / 'mas/locales' / (language + '.json')).read_text())
        for key in ('apt_setup', 'apt_done', 'apt_failed'):
            installer = installer.replace('@' + key.upper() + '_' + suffix + '@', shlex.quote(catalog[key]))
    (ROOT / "install.sh").write_text(installer)

    entries = {"stable/install.sh": ("--channel", "stable"),
               "test/install.sh": ("--channel", "test"),
               "test/test.sh": ("--channel", "test", "--test"),
               "test/test-stable.sh": ("--channel", "stable", "--test"),
               "test/security.sh": ("--channel", "test", "--security")}
    for path, arguments in (() if args.stable else entries.items()):
        branch = 'release' if '--channel' in arguments and arguments[1] == 'stable' else 'main'
        wrapper = (ROOT / 'scripts/channel.template.sh').read_text().replace('@ARGUMENTS@', shlex.join(arguments))
        wrapper = wrapper.replace('@SOURCE_BRANCH@', branch)
        target = ROOT / path
        target.parent.mkdir(exist_ok=True)
        target.write_text(wrapper)
        target.chmod(0o755)

    archives = [("mas.pyz", "mas.cli:main"), ("mas-install.pyz", "mas.install:main")]
    if not args.stable:
        archives.append(("mas-test.pyz", "mas.testing:main"))
    for filename, entry in archives:
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            excluded = ["__pycache__"]
            if filename != "mas-test.pyz":
                excluded += ["testing.py", "test_output.py", "security_testing.py", "test"]
            if filename == "mas-install.pyz":
                excluded += ["cli.py", "terminal_ui.py", "__main__.py"]
            if filename == "mas.pyz":
                excluded += ["install.py", "dependencies.sh", "socket_access.py"]
            shutil.copytree(ROOT / "mas", stage / "mas", ignore=shutil.ignore_patterns(*excluded))
            if filename == "mas-test.pyz":
                shutil.copyfile(ROOT / "bootstrap.py", stage / "bootstrap.py")
                shutil.copyfile(ROOT / "install.sh", stage / "install.sh")
                shutil.copytree(ROOT / "tests", stage / "tests", ignore=shutil.ignore_patterns("__pycache__"))
                for name in ('guest_security_probe.py', 'host_security_probe.py'):
                    shutil.copyfile(ROOT / 'test' / name, stage / 'tests' / name)
            module, function = entry.split(":")
            (stage / "__main__.py").write_text(f"from {module} import {function}\nraise SystemExit({function}())\n")
            archive = DIST / filename
            archive.write_bytes(b"#!/usr/bin/env python3\n")
            with zipfile.ZipFile(archive, 'a', compression=zipfile.ZIP_DEFLATED) as package:
                for source in sorted(stage.rglob('*')):
                    if source.is_file():
                        info = zipfile.ZipInfo(source.relative_to(stage).as_posix(), (2020, 1, 1, 0, 0, 0))
                        info.compress_type = zipfile.ZIP_DEFLATED
                        info.external_attr = 0o100644 << 16
                        package.writestr(info, source.read_bytes())
            archive.chmod(0o755)
    for name in (() if args.stable else ("bootstrap.py", "install.sh")):
        shutil.copyfile(ROOT / name, DIST / name)
    entry_assets = {"install-stable.sh": "stable/install.sh", "install-test.sh": "test/install.sh",
                    "test.sh": "test/test.sh", "test-stable.sh": "test/test-stable.sh",
                    "security.sh": "test/security.sh"}
    for name, path in (() if args.stable else entry_assets.items()):
        shutil.copyfile(ROOT / path, DIST / name)
    names = ("mas.pyz", "mas-install.pyz") if args.stable else ("mas.pyz", "mas-install.pyz", "mas-test.pyz", "bootstrap.py", "install.sh", *entry_assets)
    (DIST / "SHA256SUMS").write_text("".join(
        hashlib.sha256((DIST / name).read_bytes()).hexdigest() + "  " + name + "\n" for name in names))
    print("Built " + ", ".join(names))


if __name__ == "__main__":
    main()
