#!/usr/bin/env python3
"""Stable entry: resolve the newest test prerelease and verify its assets."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import urllib.request

REPOSITORY = "gdrencn/my-ai-sandbox"


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "my-ai-sandbox-installer"})
    with urllib.request.urlopen(request, timeout=600) as response:
        return response.read()


def release(version=None):
    base = f"https://api.github.com/repos/{REPOSITORY}/releases"
    if version:
        if not re.fullmatch(r"v\d+\.\d+\.\d+-test\.\d+", version):
            raise RuntimeError("Expected a test version such as v0.1.0-test.1")
        result = json.loads(download(base + "/tags/" + version))
        if result.get("draft") or not result.get("prerelease"):
            raise RuntimeError("Requested release is not a published test prerelease.")
        return result
    for page in range(1, 101):
        releases = json.loads(download(base + f"?per_page=100&page={page}"))
        matches = [item for item in releases if not item["draft"] and item["prerelease"]
                   and re.fullmatch(r"v\d+\.\d+\.\d+-test\.\d+", item["tag_name"])]
        if matches:
            return max(matches, key=lambda item: item["published_at"])
        if len(releases) < 100:
            break
    raise RuntimeError("No published test release exists yet.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="install matching test tool and run it")
    parser.add_argument("--release", help="install an exact test version")
    args, test_args = parser.parse_known_args()
    if test_args and not args.test:
        parser.error("Extra arguments are accepted only with --test")
    selected = release(args.release)
    print("Installing " + selected["tag_name"], flush=True)
    assets = {asset["name"]: asset["browser_download_url"] for asset in selected["assets"]}
    checksums = {}
    for line in download(assets["SHA256SUMS"]).decode().splitlines():
        digest, name = line.split(maxsplit=1)
        checksums[name.lstrip("*")] = digest
    with tempfile.TemporaryDirectory(prefix="mas-install-") as directory:
        paths = {}
        for name in ("mas.pyz", "mas-test.pyz"):
            data = download(assets[name])
            if hashlib.sha256(data).hexdigest() != checksums[name]:
                raise RuntimeError("Checksum mismatch: " + name)
            paths[name] = Path(directory) / name
            paths[name].write_bytes(data)
        sys.path.insert(0, str(paths["mas.pyz"]))
        from mas.install import install
        return install(paths["mas.pyz"], paths["mas-test.pyz"], args.test, test_args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
