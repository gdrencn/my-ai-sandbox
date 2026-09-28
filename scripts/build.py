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
    messages = json.loads((ROOT / "mas/locales/en_us.json").read_text())
    installer = (ROOT / "scripts/install.template.sh").read_text().replace(
        "@LANGUAGE_PROMPT@", shlex.quote(messages["choose_language"].format(current="en_us")))
    (ROOT / "install.sh").write_text(installer)

    for filename, entry, tests in (("mas.pyz", "mas.cli:main", False),
                                   ("mas-test.pyz", "mas.testing:main", True)):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            shutil.copytree(ROOT / "mas", stage / "mas", ignore=shutil.ignore_patterns("__pycache__"))
            if tests:
                shutil.copyfile(ROOT / "bootstrap.py", stage / "bootstrap.py")
                shutil.copytree(ROOT / "tests", stage / "tests", ignore=shutil.ignore_patterns("__pycache__"))
            module, function = entry.split(":")
            (stage / "__main__.py").write_text(f"from {module} import {function}\nraise SystemExit({function}())\n")
            zipapp.create_archive(stage, DIST / filename, interpreter="/usr/bin/env python3", compressed=True)
    for name in ("bootstrap.py", "install.sh"):
        shutil.copyfile(ROOT / name, DIST / name)
    names = ("mas.pyz", "mas-test.pyz", "bootstrap.py", "install.sh")
    (DIST / "SHA256SUMS").write_text("".join(
        hashlib.sha256((DIST / name).read_bytes()).hexdigest() + "  " + name + "\n" for name in names))
    print("Built " + ", ".join(names))


if __name__ == "__main__":
    main()
