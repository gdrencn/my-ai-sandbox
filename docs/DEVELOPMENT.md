# Development and release guide

Baseline is accepted stable/test 0.2.25. Read [AGENTS.md](../AGENTS.md), [current requirements](../REQUIREMENTS.md), [implementation/evidence](../IMPLEMENTED.md) and [decisions](DECISIONS.md) first. Historical proposals cannot authorize new features. Discuss scope/acceptance, obtain explicit execution authorization, update requirements, implement in the owning module, verify, then update implementation and affected documentation.

## Source map

| Path | Responsibility |
| --- | --- |
| mas/__init__.py | Shared numeric version. |
| mas/core.py | LXD command/state completion, Manager foundations/compositions, ownership, user setup and terminal lifetime. |
| mas/lxd_config.py | Local LXD API, valid ETag/If-Match, asynchronous operation completion and native diagnostics. |
| mas/isolation.py | Fixed Project/Profile policy, provisioning, observation and exact expanded device/config audit. |
| mas/imports.py | Explicit legacy migration and restricted-Project staged backup import. |
| mas/development.py | Exact 25-package cloud-init/APT new-only preparation, verification and payload retirement. |
| mas/gpu.py | NVIDIA capability/discovery, resource inventory, stopped identity-guarded config and runtime files. |
| mas/network.py | Exact approved NIC and persistent on/off metadata/updates. |
| mas/filesystems.py | Per-user native LXD/SSHFS registry, locks, one-path mount/unmount/recovery and lifecycle guards. |
| mas/cli.py, mas/__main__.py | Arguments, dispatch, exit status and product command entry. |
| mas/terminal_ui.py | Business menu pages composing shared Manager and view controls. |
| mas/menu.py | Shared inline Screen, keys/input/radio/multiple choice, language and post-shell controls. |
| mas/text.py | Escaping, display-cell widths, columns and semantic colors. |
| mas/output.py | Shared transient/permanent terminal output, APT fragments/prompts and scoped waiting. |
| mas/presentation.py | Product result/row/info/mount formatting and progress adapter. |
| mas/diagnostics.py | Native failure formatting, observer-safe reporting and primary/cleanup error preservation. |
| mas/config.py, mas/i18n.py | Atomic user preferences, language lookup and localized parser. |
| mas/locales/en_us.json, zh_cn.json | Product/installer messages; mas/locales/test catalogs are tester-only. |
| mas/install.py, mas/dependencies.sh, mas/socket_access.py | Shared host dependency/LXD/FUSE/socket/group/PATH and atomic install. |
| bootstrap.py | Channel/release discovery, downloads/checksums, exact stable pairing and entry routing. |
| scripts/install.template.sh, channel.template.sh | Root bootstrap and thin channel source; generated shell entries must not diverge. |
| scripts/build.py | Deterministic separated zipapps and generated entries/manifests. |
| mas/testing.py, mas/test_output.py | Packaged discovery, real command/PTy suite, reports and classified test presentation. |
| mas/security_testing.py | Shared host challenge selection/orchestration, identity/state restore and validation. |
| test/host_security_probe.py, guest_security_probe.py | Bounded host references and internal guest checks, bundled only into tester. |
| tests/ | Portable standard-library regressions, GPU compute fixture and shared probe source access. |
| scripts/test_guest_security_probe.py | Compatibility unit entry; normal discovery already includes its checks. |
| scripts/verify_wsl_socket.py | Supplemental controlled WSL socket check, not a default full-suite phase. |
| validation/ | Historical/current immutable measured receipts, not inputs to product runtime. |
| scripts/build_handoff.py, handoff/ | Developer archive generation and fresh-session handoff. |

## Artifacts and branches

`main` owns development, tester, tests, validation and complete documentation. `release` is the independent stable-only branch; current head equals stable/0.2.25, with two publication commits and 34 tracked files. Do not merge main history, tests or handoff artifacts into release. Current test source tag v0.2.25 is older than subsequent documentation/verification commits; do not move it.

```bash
python3 scripts/build.py
```

The main build generates eleven files in dist: mas.pyz, mas-install.pyz, mas-test.pyz, bootstrap.py, install.sh, install-stable.sh, install-test.sh, test.sh, test-stable.sh, security.sh, SHA256SUMS. Its manifest covers the ten generated payloads. Test publication additionally uploads the frozen local full report as WSL_REPORT.json and appends that report's SHA-256 to the published manifest, making twelve assets and eleven manifest entries. GitHub digest/byte review checks every published asset. The zipapps must not contain the handoff files or development docs.

Product excludes install/dependencies/socket setup and tester/probe code/catalogs. Installer excludes product entry/CLI/business menus and tester/probe code/catalogs, but includes shared setup/UI/output. Tester includes its shared code, all tests, exact two probes, bootstrap and generated installer entry. All share numeric version. Zip entries have fixed timestamps and stable order; documentation edits should reproduce current zipapp bytes exactly.

Stable build in a separate release checkout:

```bash
python3 scripts/build.py --stable
```

It generates only mas.pyz, mas-install.pyz, SHA256SUMS and rewrites root install.sh for release source/stable default. Use a separate clean worktree/output: dist is not purged and previous test artifacts should not be mistaken for stable inventory. Do not run --stable in main and commit the resulting installer branch change. Normal main generation must leave tracked product/entry source unchanged when no code/template changed.

## Portable and packaged units

Source discovery is useful during development:

```bash
python3 -m unittest discover -v
```

It has one intentional archive-only skip. Final no-skip evidence comes from the packaged tester, outside the checkout. This exact command only runs units and does not install mas or create LXD containers:

```bash
python3 -I - /absolute/path/dist/mas-test.pyz <<'PY'
import sys
import unittest
sys.path.insert(0, sys.argv[1])
from mas.testing import unit_modules
modules = unit_modules()
suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in modules)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
PY
```

Current discovery contains 449 tests. Use real PTYs/display-engine captures for terminal behavior, not just returned strings. Test subprocesses use mas.testing.python_command with an explicit archive/source root; do not depend on cwd/PYTHONPATH or optimized Python. For code changes run appropriate focused tests first, then frozen packaged/full native checks required by the batch. Docs/handoff changes require restore/rebuild/units and document/artifact checks; a new native run is justified only by a concrete concern.

## Native and public verification

Full native validation requires a prepared supported Linux/WSL host, LXD access, SSHFS/FUSE and applicable GPU resources. It can install the supplied product and create owned disposable Projects/containers; preserve user configuration using private XDG paths. Use absolute archive/result paths and a new output directory outside the checkout:

```bash
python3 /absolute/path/dist/mas-test.pyz --product /absolute/path/dist/mas.pyz --output /absolute/path/new-results
```

For explicit installer orchestration add `--install /absolute/path/dist/mas-install.pyz`. The complete run has one unit stage, 26 functional stages, one fresh-container final challenge, cleanup and summary. Do not insert repeated full challenges inside GPU/network toggles.

After publication verify actual public entries:

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/test.sh | bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/test-stable.sh | bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/test/security.sh | bash
```

The first uses latest numeric test, second actual latest stable and immutable same-version tester, third only tester and an existing selected mas container. Each shares the challenge module. Independent security is host-only and restores initial UUID/state; see GUEST_SECURITY_PROBE.md for exact methods, report/exit behavior and bounds.

Review JSON failures/errors/skips/not_run and cleanup separately. Independently verify owned Project/staging/legacy resources, mount journal/directories/table/helpers and backup directories are reclaimed; preserve an empty retained mount journal as normal state. Confirm installed hashes and single final guest_boundary. Record real native versus fault-injected and user-reported evidence separately.

## Test publication

1. Confirm the authorized product batch and acceptance scope in REQUIREMENTS.md. Increment phase batch once, keep major 0 unless user explicitly permits 1; documentation-only commits and stable promotion do not increment. Update one shared version, catalogs/templates as needed and generated entries.
2. Build in isolation, verify all expected file/package boundaries, Python 3.10 grammar and shell checks, reproducibility and matching sources. Run the final frozen suite outside the checkout and independently review owned cleanup/hashes. Update IMPLEMENTED/current docs after verified phases.
3. Freeze product source in a commit/tag `vA.B.C`. Keep subsequent receipts/docs on main; never rebuild published bytes from a later changed source. Upload the eleven build assets plus exact frozen WSL_REPORT.json as a prerelease using gh, recording tested scope/results. Do not replace an earlier release/tag/asset.
4. Download every published asset to a new directory and compare bytes, manifests/GitHub digests and source identity. Test actual public install/test/security paths applicable to the change, ordinary-install tester preservation, source/channel URLs and old publication metadata. Exclude only automatically increasing download counters from metadata equality.
5. Publish the verification receipts/docs on main and complete the agreed test batch. Stable is a separate user acceptance/publication decision. Use structured tools or --notes-file for multiline release bodies; keep literal newlines and do not interpolate untrusted shell text.

## Stable promotion

1. After user acceptance, freeze the immutable numeric test product/installer and existing publication identities. Advance release from the previous stable with only accepted product/installer/shared-build source and relevant product docs; no main/test/validation/handoff content. Keep stable history limited to its publications.
2. In an isolated stable-only checkout build twice with --stable. Verify absence of excluded files, exact three-file asset inventory and byte-identical product/installer versus the accepted published test. Verify stable source/install entry uses release throughout.
3. Publish separate annotated `stable/A.B.C` and non-prerelease GitHub release, exactly three assets and explicit latest. Keep original numeric test unchanged. Stable uses the same program version and exact paired tester; no fallback on missing/mismatched tags/manifests.
4. Verify downloaded stable assets, source/download origins, preserved older metadata/tags, ordinary public release/install.sh preserving tester, and exact main/test/test-stable.sh full native run outside checkout. Independently check cleanup/installed hashes; record verified docs/results on main and new release notes. Do not rewrite frozen tags/old assets when adding receipts.

GitHub write authentication belongs to the new host; the handoff contains no credentials. `gh auth status` checks local setup; do not copy old token/helper files. Do not publish new product releases solely for a documentation/handoff update.

## Handoff update

See [handoff/README.md](../handoff/README.md). Freeze a committed documentation/source baseline before creating an archive; a later archive/receipt publication commit is intentionally outside that snapshot to avoid embedding the archive into itself. Generate from selected main/release/tag refs only. Do not use local untracked files, .git/config, global Codex directories or LXD backups. Verify an offline clean restore and byte-identical build/packaged units, then public download and metadata preservation. Future archives must start from an explicit baseline, avoid carrying earlier archive binaries in Git history, and state their included scope and verification clearly.

Primary format reference: [Git bundle documentation](https://git-scm.com/docs/git-bundle). The implementation/receipts establish this project's actual no-prerequisite restore behavior.
