#!/usr/bin/env python3
"""Build a self-contained developer handoff from committed Git refs, offline."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/gdrencn/my-ai-sandbox.git"


def git(*arguments, directory=ROOT):
    return subprocess.check_output(
        ["git", "-C", str(directory), *arguments], stderr=subprocess.PIPE
    ).decode("utf-8").strip()


def committed_bytes(commit, path):
    return subprocess.check_output(["git", "-C", str(ROOT), "show", f"{commit}:{path}"])


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def build(commit_argument, output, include_prior_archives=False):
    if output.exists() or output.is_symlink():
        raise ValueError(f"Output already exists; choose a new directory: {output}")
    if not output.parent.is_dir():
        raise ValueError(f"Output parent must exist: {output.parent}")
    if commit_argument.startswith("-"):
        raise ValueError("Commit must not start with '-'")
    if git("rev-parse", "--is-shallow-repository") != "false":
        raise ValueError("A complete repository is required; shallow history is unsupported")
    commit = git("rev-parse", "--verify", f"{commit_argument}^{{commit}}")
    git("merge-base", "--is-ancestor", commit, "refs/heads/main")
    version_source = committed_bytes(commit, "mas/__init__.py").decode()
    match = re.search(r'__version__\s*=\s*[\'"]([0-9]+\.[0-9]+\.[0-9]+)[\'"]', version_source)
    if match is None:
        raise ValueError("Committed numeric version is missing")
    version = match.group(1)
    refs = {"refs/heads/main": commit,
            "refs/heads/release": git("rev-parse", "refs/heads/release")}
    for line in git("for-each-ref", "--format=%(refname) %(objectname)", "refs/tags").splitlines():
        name, object_id = line.split()
        refs[name] = object_id
    for tag in (f"v{version}", f"stable/{version}"):
        if f"refs/tags/{tag}" not in refs:
            raise ValueError(f"Both accepted test and stable tags are required: {tag}")

    # Preserve published history only with explicit opt-in; never silently filter it.
    prior_archives = []
    for line in git("rev-list", "--objects", commit, *list(refs)[1:]).splitlines():
        object_id, separator, path = line.partition(" ")
        if separator and path.startswith("handoff/") and path.endswith((".tar.gz", ".git.bundle")):
            data = subprocess.check_output(["git", "-C", str(ROOT), "cat-file", "blob", object_id])
            prior_archives.append({"path": path, "git_blob": object_id,
                                   "sha256": sha256(data), "size": len(data)})
    if prior_archives and not include_prior_archives:
        raise ValueError("Selected history contains prior handoff binaries; use --include-prior-archives to retain them explicitly")

    payload = {name: committed_bytes(commit, f"handoff/{name}")
               for name in ("START_HERE.md", "RESTORE.sh", "RELEASES.json")}
    catalog = json.loads(payload["RELEASES.json"])
    selected_releases = {item["tag_name"]: item for item in catalog["releases"]
                         if item["tag_name"] in (f"v{version}", f"stable/{version}")}
    if len(selected_releases) != 2 or catalog["latest_stable"] != f"stable/{version}":
        raise ValueError("Release catalog does not describe this accepted version")
    tracked_files = []
    for entry in git("ls-tree", "-r", commit).splitlines():
        fields, path = entry.split("\t", 1)
        mode, kind, object_id = fields.split()
        if kind != "blob":
            raise ValueError(f"Unsupported tracked object: {path}")
        tracked_files.append({"path": path, "mode": mode, "git_blob": object_id})

    with tempfile.TemporaryDirectory(prefix="mas-handoff-") as temporary:
        stage = Path(temporary)
        bare = stage / "repository.git"
        git("init", "--bare", "--quiet", str(bare))
        refspecs = [f"{object_id}:{name}" for name, object_id in refs.items()]
        git("fetch", "--quiet", "--no-tags", str(ROOT), *refspecs, directory=bare)
        git("symbolic-ref", "HEAD", "refs/heads/main", directory=bare)
        actual_refs = dict(line.split() for line in
                           git("for-each-ref", "--format=%(refname) %(objectname)", directory=bare).splitlines())
        if refs != actual_refs:
            raise ValueError("Fetched ref identities do not match the selected snapshot")
        git("fsck", "--full", directory=bare)
        # Normalize fetched representations; otherwise bundle reuse can vary with
        # the source's loose/packed objects even when all selected refs are equal.
        git("-c", "pack.threads=1", "repack", "-a", "-d", "-f", "-F", directory=bare)
        bundle_path = stage / "my-ai-sandbox.git.bundle"
        git("-c", "pack.threads=1", "bundle", "create", str(bundle_path), *refs, directory=bare)
        empty = stage / "empty.git"
        git("init", "--bare", "--quiet", str(empty))
        git("bundle", "verify", str(bundle_path), directory=empty)
        payload[bundle_path.name] = bundle_path.read_bytes()
        manifest = {
            "schema_version": 1, "product_version": version, "repository": REPOSITORY,
            "baseline_main_commit": commit,
            "baseline_commit_date": git("show", "-s", "--format=%cI", commit),
            "snapshot_scope": "Full reachable history for the frozen main, release and every existing tag; no prerequisites",
            "publication_commits": "Archive upload and subsequent verification receipts are outside this frozen baseline",
            "prior_handoff_archives": sorted(prior_archives, key=lambda item: (item["path"], item["git_blob"])),
            "refs": {name: {"object": object_id,
                            "commit": git("rev-parse", f"{name}^{{commit}}", directory=bare)}
                     for name, object_id in sorted(refs.items())},
            "branch_commit_counts": {branch: int(git("rev-list", "--count", f"refs/heads/{branch}", directory=bare))
                                     for branch in ("main", "release")},
            "baseline_tracked_files": tracked_files,
            "latest_stable": catalog["latest_stable"], "numeric_test": catalog["numeric_test"],
            "release_catalog_count": len(catalog["releases"]),
            "accepted_releases": selected_releases,
            "payloads": {name: {"sha256": sha256(data), "size": len(data)}
                         for name, data in sorted(payload.items())},
            "excluded": ["Untracked host files", "Git config/hooks/credentials", "Installed binaries",
                         "Global/personal configuration", "Container images and LXD data", "Release asset binaries"],
        }
        payload["MANIFEST.json"] = json_bytes(manifest)
        payload["SHA256SUMS"] = "".join(f"{sha256(data)}  {name}\n" for name, data in sorted(payload.items())).encode()
        archive_name = f"my-ai-sandbox-{version}.tar.gz"
        archive_path = stage / archive_name
        with archive_path.open("wb") as archive_file:
            with gzip.GzipFile(filename="", mode="wb", fileobj=archive_file, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for name, data in sorted(payload.items()):
                        info = tarfile.TarInfo(f"my-ai-sandbox-handoff-{version}/{name}")
                        info.size = len(data)
                        info.mode = 0o755 if name == "RESTORE.sh" else 0o644
                        archive.addfile(info, io.BytesIO(data))
        archive_data = archive_path.read_bytes()
        external_manifest = json_bytes({**manifest, "archive": {
            "name": archive_name, "sha256": sha256(archive_data), "size": len(archive_data),
            "members": sorted(payload), "root_directory": f"my-ai-sandbox-handoff-{version}"}})
        # The new directory is claimed only after all generation/verification succeeds.
        output.mkdir()
        (output / archive_name).write_bytes(archive_data)
        (output / "MANIFEST.json").write_bytes(external_manifest)
        (output / "SHA256SUMS").write_text(
            f"{sha256(external_manifest)}  MANIFEST.json\n{sha256(archive_data)}  {archive_name}\n")
    print(f"Built {output / archive_name}: {len(archive_data)} bytes; main {commit}; {len(refs)} refs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD", help="Committed main baseline (default: HEAD)")
    parser.add_argument("--output", type=Path, required=True, help="New output directory; must not exist")
    parser.add_argument("--include-prior-archives", action="store_true",
                        help="Explicitly retain and inventory earlier handoff binaries in complete Git history")
    args = parser.parse_args()
    try:
        build(args.commit, args.output.absolute(), args.include_prior_archives)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        detail = error.stderr.decode().strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
        parser.exit(2, f"build_handoff: {detail}\n")


if __name__ == "__main__":
    main()
