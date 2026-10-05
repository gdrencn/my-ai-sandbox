# Current implementation and evidence — 0.2.25

Stable [stable/0.2.25](https://github.com/gdrencn/my-ai-sandbox/releases/tag/stable/0.2.25) is GitHub latest and user-accepted. Test [v0.2.25](https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.2.25) remains an immutable prerelease. Product/installer bytes and numeric version are identical. This document records current state; the original 46 stage records and intermediate/failed attempts are retained in [IMPLEMENTED history](docs/history/IMPLEMENTED_0_2_25.md).

## Delivered functionality

| Area | Implemented scope | Source and current specification |
| --- | --- | --- |
| Container foundations | Local owned new/list/info/start/stop/delete/import/export; bounded native completion; shared failures/identity guards. | mas/core.py; CORE_BEHAVIOR.md |
| Lifecycle composition | Prepared new ends Stopped; restart stop→start/enter; sandbox login; four post-terminal destinations; stop-all ownership isolation. | mas/core.py, mas/development.py |
| Fixed isolation | Dedicated mas Project/Profile and compatible project-local default, restricted policy, expanded config/device audit, safe stop/recovery during drift. | mas/isolation.py; REQUIREMENTS.md |
| Configuration/migration/import | ETag If-Match, UUID checks, explicit compatible legacy migration, staged native import preserving rejected data. | mas/lxd_config.py, mas/imports.py |
| GPU | Official active WSL NVIDIA discovery, readonly resources and owned files, persistent stopped on/off; native CDI code path exists. | mas/gpu.py |
| Network | Persistent approved per-container NIC on/off, IPv4/IPv6 off and retained loopback, offline management/mount/backup behavior. | mas/network.py |
| Host filesystem access | Native LXD file mount + SSHFS, exact mount/unmount, journal identities, recovery, lifecycle reuse and delete guard. | mas/filesystems.py |
| Installation | Shared independent installer, grouped dependencies, FUSE/socket/group/PATH persistence, existing-system preservation, ordinary native sudo. | bootstrap.py, mas/install.py, mas/dependencies.sh, mas/socket_access.py |
| CLI/menu/language | Shared foundations and inline controls, progress/diagnostics, immediate zh_cn/en_us, resize correction, About/version/back. | mas/cli.py, mas/terminal_ui.py, mas/menu.py, mas/output.py, mas/text.py, catalogs |
| Testing/security | Standalone exact-version tester, portable units, isolated native stages, one final shared complete challenge and cleanup. | mas/testing.py, mas/security_testing.py, test probes |
| Distribution | Twelve test assets, three stable assets, release-only stable source, exact paired tester without fallback, preserved releases. | scripts/build.py, shared templates, bootstrap.py |

Detailed behavior is in [CORE_BEHAVIOR.md](CORE_BEHAVIOR.md); current requirements/pending decisions are in [REQUIREMENTS.md](REQUIREMENTS.md); module ownership/workflow is in [DEVELOPMENT.md](docs/DEVELOPMENT.md). The requirements history contains superseded official-Node provisioning, older default-Project management, old post-shell radio confirmation, guest/public security entry designs and pre-release-branch routing; none is current instruction.

## Immutable release identities

| Identity | Value |
| --- | --- |
| Numeric product/installer/tester version | 0.2.25 |
| Test tag peeled commit | ee6409d4d1a3a1a9ab4822b81ab0bffa69203ad2 |
| Stable tag peeled / release head | ddc6ab6caad9dd95b803693a8dd03b7e4ba26da8 |
| Previous stable parent | bf381456c0109237da296c02485dd6a6712522f1 |
| release history | Two stable-publication commits; 34 tracked product/installer/shared-build/document files. |
| mas.pyz SHA-256 | fc4acabba8c8974bd9c99f01b82f074b36424646d1c57c474d6eb763f8a50ffc |
| mas-install.pyz SHA-256 | 6b8a48d19f146f6bf750edf833af7bedbc330d7f7c05fff20c69d511163ca08b |
| mas-test.pyz SHA-256 | befd72eaf727736fc1a09e06c40728616ca3753e0c3c06b768e383e12a94bfa9 |

Do not move tags, replace published assets or turn release into main history. The handoff manifest captures the later documentation baseline separately from these frozen source identities.

## Final product validation

| Run | Packaged units | Reported stages | Final challenge | Seconds | Receipt |
| --- | --- | --- | --- | --- | --- |
| Frozen local v0.2.25 | 449 | 28 | 76 PASS / 0 FAIL | 1414.5 | [report](validation/V0_2_25_LOCAL_REPORT.json), [review](validation/V0_2_25_LOCAL_REVIEW.json) |
| Exact public test/test.sh | 449 | 28 | 76 PASS / 0 FAIL | 1433.9 | [report](validation/V0_2_25_PUBLIC_REPORT.json), [review](validation/V0_2_25_PUBLIC_REVIEW.json) |
| Exact public test/test-stable.sh | 449 unchanged paired units | 28 | 76 PASS / 0 FAIL | 1408.6 | [report](validation/STABLE_0_2_25_PUBLIC_REPORT.json), [review](validation/STABLE_0_2_25_PUBLIC_REVIEW.json) |

All three final runs have no unit skips, failed/unexecuted stages or cleanup errors. Each has one final complete challenge after functional tests. Independent verification confirmed owned Project/import-staging/legacy-profile/target, backup/mount/private helper reclamation, an empty retained mount journal and installed product/tester hashes. Detailed methods/ranges are in GUEST_SECURITY_PROBE.md; quantities refer to these actual runs.

About's 29 focused tests include real PTYs in both languages and Enter/Right/Escape/Left, current version, title/spacing, parent focus, unchanged preferences and terminal restoration. Native full-menu validation visits About in both languages before its normal container/backup operations. Packaging tests independently verified product/installer/tester boundaries, matching source, deterministic rebuild, Python 3.10 grammar and Shell checks.

Stable-only builds work without excluded tester/test/catalog/validation files and produce only three assets with exact accepted product/installer hashes. Actual ordinary stable install preserves tester bytes and modification time. Nine bootstrap source downloads match release, product/installer URLs belong to stable and the tester URL exactly to v0.2.25. All 42 earlier publication/asset records were unchanged at stable promotion, excluding automatic download counters; all previous tags remain.

Receipts: [test packaging](validation/V0_2_25_PACKAGING_REVIEW.json), [test release](validation/V0_2_25_RELEASE_CHECK.json), [test install](validation/V0_2_25_PUBLIC_INSTALL.json), [stable build](validation/STABLE_0_2_25_BUILD.json), [stable release](validation/STABLE_0_2_25_RELEASE_CHECK.json), [stable install](validation/STABLE_0_2_25_PUBLIC_INSTALL.json), [stable source trace](validation/STABLE_0_2_25_SOURCE_TRACE.json).

## User evidence and measurement limits

The user supplied a v0.2.25 full run passing 28 stages and one 76-check challenge with cleanup in 1770.4 seconds, including fresh host SSHFS/LXD installation and initialization, then explicitly accepted About/version and authorized stable. These are user-reported console results; the local report file was not available for independent inspection. User v0.2.24 reports also include terminal maximization/restoration acceptance and an independent challenge restoring Stopped.

Agent full-suite measurements use prepared Ubuntu 26.04 WSL/LXD 6.9/NVIDIA x86_64. Native tmux 3.6 reflow/resize and portable PTYs supplement the terminal evidence; graphical terminal acceptance is user-reported. Native Ubuntu/cloud, ARM64, native NVIDIA CDI/other GPUs/storage backends have no new native measurement. AppArmor is disabled on the current WSL kernel. See TEST_COVERAGE.md for fault-injection and Windows/ACL limitations. No broad security certification follows from listed checks passing.

## Documentation and handoff batch — Stage 47

Authorized after stable acceptance: “OK，现在可以做完整文档整理和交接bundle了。” Current requirements, usage, behavior, coverage, security, menu and release notes have been audited and consolidated; eight earlier root documents preserve their complete contents with only a historical notice and relative-link adjustments. Project-owned AGENTS/UI guidance, development/release instructions, decision/pending tables, public metadata for all 43 releases and a copyable fresh-Codex entry are present.

Preparation verified Markdown paths/anchors, exact historical preservation, unchanged pre-existing product/test/build/entry source, Python 3.10 grammar and Bash/ShellCheck for the handoff tooling. A private committed pilot produced a self-contained Git bundle with main/release/all 43 tags, restored offline with other protocols disabled, passed full fsck and exact branch/tag/file-inventory checks, refused existing empty/nonempty directories and dangling symlinks, and rejected internal/outer corruption before cloning. Restored builds reproduce all three zipapps and ten generated payloads at the accepted v0.2.25 hashes. Normalized repeated handoff builds match exactly. Evidence: [preparation review](validation/HANDOFF_0_2_25_PREPARATION.json).

The unit-only development command initially omitted the public tester's archive/product initialization, producing two fixture errors and one skip; [that attempt](validation/HANDOFF_0_2_25_UNITS_INITIAL.json) is retained separately. The corrected documented invocation passed all 449 distinct restored packaged units in 31.995 seconds, with zero failures, errors or skips; [unit receipt](validation/HANDOFF_0_2_25_UNITS.json). Product/tester bytes and tests are unchanged.

This is the corrected documentation/source freeze before generating the final public archive. Final archive/public download/restoration receipts belong to subsequent archive-publication commits, deliberately outside this bundle baseline to avoid embedding the archive into itself. The manifest identifies that baseline; see handoff/START_HERE.md for how to inspect later closing commits. Numeric version/product/test behavior and all stable publication identities remain unchanged.
