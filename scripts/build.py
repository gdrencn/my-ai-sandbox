#!/usr/bin/env python3
"""Build architecture-independent zipapps without pip or external tools."""

import hashlib
import json
import shlex
from pathlib import Path
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def main():
    DIST.mkdir(exist_ok=True)
    messages = json.loads((ROOT / "mas/locales/zh_cn.json").read_text())
    installer = (ROOT / "scripts/install.template.sh").read_text()
    for token, key in {"LANGUAGE_TITLE": "language_title", "LANGUAGE_ZH": "language_zh",
                       "LANGUAGE_EN": "language_en", "LANGUAGE_KEYS": "menu_keys"}.items():
        installer = installer.replace("@" + token + "@", shlex.quote(messages[key]))
    installer = installer.replace('@DEPENDENCIES@', (ROOT / 'mas/dependencies.sh').read_text())
    for language, suffix in (('zh_cn', 'ZH'), ('en_us', 'EN')):
        catalog = json.loads((ROOT / 'mas/locales' / (language + '.json')).read_text())
        for key in ('apt_setup', 'apt_done', 'apt_failed'):
            installer = installer.replace('@' + key.upper() + '_' + suffix + '@', shlex.quote(catalog[key]))
    (ROOT / "install.sh").write_text(installer)

    entries = {"stable/install.sh": ("--channel", "stable"),
               "test/install.sh": ("--channel", "test"),
               "test/test.sh": ("--channel", "test", "--test"),
               "test/test-stable.sh": ("--channel", "stable", "--test")}
    for path, arguments in entries.items():
        wrapper = (ROOT / 'scripts/channel.template.sh').read_text().replace('@ARGUMENTS@', shlex.join(arguments))
        target = ROOT / path
        target.parent.mkdir(exist_ok=True)
        target.write_text(wrapper)
        target.chmod(0o755)

    for filename, entry in (("mas.pyz", "mas.cli:main"),
                            ("mas-install.pyz", "mas.install:main"),
                            ("mas-test.pyz", "mas.testing:main")):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            excluded = ["__pycache__"]
            if filename != "mas-test.pyz":
                excluded += ["testing.py", "test_output.py", "test"]
            if filename == "mas-install.pyz":
                excluded += ["cli.py", "terminal_ui.py", "__main__.py"]
            if filename == "mas.pyz":
                excluded += ["install.py", "dependencies.sh"]
            shutil.copytree(ROOT / "mas", stage / "mas", ignore=shutil.ignore_patterns(*excluded))
            if filename == "mas-test.pyz":
                shutil.copyfile(ROOT / "bootstrap.py", stage / "bootstrap.py")
                shutil.copyfile(ROOT / "install.sh", stage / "install.sh")
                shutil.copytree(ROOT / "tests", stage / "tests", ignore=shutil.ignore_patterns("__pycache__"))
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
    for name in ("bootstrap.py", "install.sh"):
        shutil.copyfile(ROOT / name, DIST / name)
    entry_assets = {"install-stable.sh": "stable/install.sh", "install-test.sh": "test/install.sh",
                    "test.sh": "test/test.sh", "test-stable.sh": "test/test-stable.sh"}
    for name, path in entry_assets.items():
        shutil.copyfile(ROOT / path, DIST / name)
    names = ("mas.pyz", "mas-install.pyz", "mas-test.pyz", "bootstrap.py", "install.sh", *entry_assets)
    (DIST / "SHA256SUMS").write_text("".join(
        hashlib.sha256((DIST / name).read_bytes()).hexdigest() + "  " + name + "\n" for name in names))
    print("Built " + ", ".join(names))


if __name__ == "__main__":
    main()
