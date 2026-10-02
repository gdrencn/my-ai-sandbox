#!/usr/bin/env python3
"""Stable entry: resolve the newest test prerelease and verify its assets."""

import os
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import subprocess
import urllib.request

from mas import config
from mas.i18n import Parser, choose_language, t

REPOSITORY = "gdrencn/my-ai-sandbox"


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "my-ai-sandbox-installer"})
    with urllib.request.urlopen(request, timeout=600) as response:
        return response.read()


def release(version=None, *, channel="test"):
    if channel == "stable":
        result = json.loads(download(f"https://api.github.com/repos/{REPOSITORY}/releases/latest"))
        if result.get("draft") or result.get("prerelease") or not re.fullmatch(r"stable/\d+\.\d+\.\d+", result.get("tag_name", "")):
            raise RuntimeError(t("no_release"))
        if version and result["tag_name"].split("/")[-1] != version.removeprefix("v"):
            raise RuntimeError(t("stable_version_mismatch"))
        return result
    base = f"https://api.github.com/repos/{REPOSITORY}/releases"
    if version:
        if not re.fullmatch(r"v?\d+\.\d+\.\d+", version):
            raise RuntimeError(t("invalid_version"))
        result = json.loads(download(base + "/tags/v" + version.removeprefix("v")))
        if result.get("draft"):
            raise RuntimeError(t("release_unpublished"))
        return result
    matches = []
    for page in range(1, 101):
        releases = json.loads(download(base + f"?per_page=100&page={page}"))
        matches.extend(item for item in releases if not item["draft"]
                       and re.fullmatch(r"v\d+\.\d+\.\d+", item["tag_name"]))
        if len(releases) < 100:
            break
    if matches:
        return max(matches, key=lambda item: tuple(map(int, item["tag_name"][1:].split("."))))
    raise RuntimeError(t("no_release"))


def asset_urls(selected):
    return {asset['name']: asset['browser_download_url'] for asset in selected['assets']}


def release_checksums(assets):
    result = {}
    for line in download(assets['SHA256SUMS']).decode().splitlines():
        digest, name = line.split(maxsplit=1)
        result[name.lstrip('*')] = digest
    return result


def main():
    parser = Parser()
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--test", action="store_true", help=t("help_install_test"))
    actions.add_argument("--security", action="store_true", help=t("help_install_security"))
    parser.add_argument("--channel", choices=("test", "stable"), default="test", help=t("help_channel"))
    parser.add_argument("--release", help=t("help_release"))
    parser.add_argument("--language", choices=config.LANGUAGES, default=os.environ.get("MAS_LANGUAGE"), help=t("help_language"))
    args, test_args = parser.parse_known_args()
    if not args.security:
        choose_language(args.language)
    if test_args and not (args.test or args.security):
        parser.error(t("extra_test_args"))
    selected = release(args.release) if args.channel == "test" else release(args.release, channel="stable")
    stable_product = selected if args.channel == "stable" and args.test else None
    if stable_product is not None:
        selected = release(stable_product["tag_name"].split("/")[-1])
    print(t("security_loading" if args.security else "installing", version=selected["tag_name"]), flush=True)
    assets = asset_urls(selected)
    checksums = release_checksums(assets)
    if stable_product is not None:
        stable_sums = release_checksums(asset_urls(stable_product))
        if any(not stable_sums.get(name) or stable_sums[name] != checksums.get(name)
               for name in ('mas.pyz', 'mas-install.pyz')):
            raise RuntimeError(t('stable_version_mismatch'))
    with tempfile.TemporaryDirectory(prefix="mas-install-") as directory:
        paths = {}
        legacy = "mas-install.pyz" not in assets
        names = ["mas-test.pyz"] if args.security else ["mas.pyz"] if legacy else ["mas.pyz", "mas-install.pyz"]
        if args.test:
            names.append("mas-test.pyz")
        for name in names:
            data = download(assets[name])
            if hashlib.sha256(data).hexdigest() != checksums[name]:
                raise RuntimeError(t("checksum_error", name=name))
            paths[name] = Path(directory) / name
            paths[name].write_bytes(data)
        if args.security:
            command = [sys.executable, str(paths["mas-test.pyz"]), "--security", *test_args]
        elif legacy:
            # Historical numeric releases predate the standalone installer.
            code = ("import sys;sys.path.insert(0," + repr(str(paths["mas.pyz"])) + ");"
                    "from mas.install import install;raise SystemExit(install(" + repr(str(paths["mas.pyz"])) + "," +
                    repr(str(paths["mas-test.pyz"]) if args.test else None) + "," + repr(args.test) + "," + repr(test_args) + "))")
            command = [sys.executable, "-c", code]
        elif args.test:
            command = [sys.executable, str(paths["mas-test.pyz"]), "--install", str(paths["mas-install.pyz"]),
                       "--product", str(paths["mas.pyz"]), *test_args]
        else:
            command = [sys.executable, str(paths["mas-install.pyz"]), "--product", str(paths["mas.pyz"])]
        return subprocess.call(command)



if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        detail = t(exc.key, **exc.values) if isinstance(exc, config.ConfigError) else str(exc)
        print(t("install_failed", error=detail), file=sys.stderr)
        raise SystemExit(1)
