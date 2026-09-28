#!/usr/bin/env python3
"""Build architecture-independent zipapps without pip or external tools."""

import hashlib
import json
import shlex
from pathlib import Path
import shutil
import tempfile
import zipapp

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def main():
    DIST.mkdir(exist_ok=True)
    messages = json.loads((ROOT / "mas/locales/zh_cn.json").read_text())
    installer = (ROOT / "scripts/install.template.sh").read_text()
    for token, key in {"LANGUAGE_TITLE": "language_title", "LANGUAGE_ZH": "language_zh",
                       "LANGUAGE_EN": "language_en", "LANGUAGE_KEYS": "menu_keys"}.items():
        installer = installer.replace("@" + token + "@", shlex.quote(messages[key]))
    (ROOT / "install.sh").write_text(installer)

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
                excluded += ["install.py"]
            shutil.copytree(ROOT / "mas", stage / "mas", ignore=shutil.ignore_patterns(*excluded))
            if filename == "mas-test.pyz":
                shutil.copyfile(ROOT / "bootstrap.py", stage / "bootstrap.py")
                shutil.copytree(ROOT / "tests", stage / "tests", ignore=shutil.ignore_patterns("__pycache__"))
            module, function = entry.split(":")
            (stage / "__main__.py").write_text(f"from {module} import {function}\nraise SystemExit({function}())\n")
            zipapp.create_archive(stage, DIST / filename, interpreter="/usr/bin/env python3", compressed=True)
    for name in ("bootstrap.py", "install.sh"):
        shutil.copyfile(ROOT / name, DIST / name)
    names = ("mas.pyz", "mas-install.pyz", "mas-test.pyz", "bootstrap.py", "install.sh")
    (DIST / "SHA256SUMS").write_text("".join(
        hashlib.sha256((DIST / name).read_bytes()).hexdigest() + "  " + name + "\n" for name in names))
    print("Built " + ", ".join(names))


if __name__ == "__main__":
    main()
