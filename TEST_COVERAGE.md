# Automated test coverage

This maps the checks present in current batch 0.2.11 to requirements and implementation. It is a behavioral coverage inventory, not a statement of 100% line/branch coverage. Final execution results are recorded in IMPLEMENTED.md and the versioned validation reports.

## Test layers

- Packaged unit and failure-injection tests import the matching tester's bundled shared code. All tests/test_*.py modules are discovered, including new modules. The JSON report lists module names, test identifiers, tests run, failures, errors, skipped reasons, expected failures and unexpected successes.
- Integration commands and PTY sessions invoke the separately supplied product archive. Product version is checked and its SHA-256 is recorded. Real tests use an isolated LXD project and test-<UUID> targets; cleanup is limited to those resources.
- Public-entry validation downloads published artifacts, verifies normal versus --test orchestration, checks the installed hashes and preserves the user's preferences. These publication checks supplement the portable tester; they are not silently counted as its unit tests.

## Coverage map

| Requirement / code | Real product coverage | Focused failure / unit coverage |
| --- | --- | --- |
| Target validation, local scope and ownership | missing targets; remote/snapshot names; start/stop/delete/info/enter/export reject unmarked fixture; native unmarked instance remains running under stop-all | instance-local marker, VM exclusion, profile-only marker exclusion, sorted managed list, invalid JSON/schema and query errors |
| new | matching host image, explicit override, duplicate target, unavailable image | host-release selection, collisions with unmarked instances, command/state/marker wait guarantees |
| list / info | managed listing, stopped state, unmarked/missing targets rejected, complete information in menu history | sorted filtering; malformed/failed query must not establish absence |
| start | running state, sandbox identity, passwordless sudo, outbound HTTPS, repeated start, existing UID/home/file/shell preservation | Running skips native start but still prepares user; unsupported state rejection; failed startup blocks shell entry |
| stop / stop --all | Running to Stopped, repeated stop, only managed fixtures affected | stopped no-op, unsupported states, continue after individual errors and aggregate failures |
| delete | running rejection, duplicate/missing targets, default-No and explicit Yes in CLI/menu, actual disappearance | state recheck after confirmation, unmarked protection, native/state wait failure paths |
| import | backup round trip with file contents, duplicate/missing/corrupt input rejection, stopped managed result; native unmarked backup restored then marked | failed import or VM never marked; marking occurs only after import and marking failure propagates |
| export | stopped-only guard, backup round trip, CLI overwrite Yes/default No, menu overwrite refusal | native failure, invalid archive, missing metadata, publish failure preserve existing destination; temporary cleanup; concurrent new destination is not overwritten; prompt-time state change; symlink/directory/missing-parent guards |
| enter / on_exit | running and stopped entry as sandbox, default keep-running, explicit stop, menu terminal exit returns to the host shell after either stop decision | shared start/stop reuse; startup failure prevents shell; nonzero shell exit still invokes exit handler then reports failure |
| Shared _run_lxd_until_state | one-second observations and elapsed events for real commands | state success alone cannot finish live command; exit code zero alone cannot skip state; marker required; nonzero native exit, LXD Error, failed query, interruption and 300-second simulated timeout; client termination and final events |
| Text menus | complete lifecycle, classification/navigation, settings persistence, cancellation, shell return, native progress and JSON history | CSI/SS3, radio/multiple choice, defaults, UTF-8 editing, viewport resize, Ctrl-C/Escape restoration, row-redraw history preservation, no alternate-screen/screen-clear sequences |
| Installation and packaging | separate installer invoked before final product testing; public normal/test entry; installed artifact hashes | missing snap/LXD sudo sequence, ready-system no-sudo, existing profile preservation, PATH idempotence, atomic copy-failure preservation and concurrent install publication, archive separation, mismatched version, bad download checksum prevents installation |
| Language / configuration | CLI get/set/help, menu language changes and cancellation, installation default in PTY | exact en_us/zh_cn identifiers, catalog keys/placeholders, saved defaults, broken config protection, unrelated preferences retained |
| Shared progress display | complete real menu/CLI lifecycle; permanent final results, separate structured waiting records | redirected output has no ticks/escapes; Chinese narrow width; actual output terminal sizing; query warnings without newlines; PTY results/diagnostics/menu/interruption history |
| Filesystem mounts | running/stopped reads and writes, root and default-home mounts, exact unmount, non-overlap, pre-existing paths, mount restoration across start/stop, deletion refusal, killed-helper cleanup/retry, lost PID-record recovery, changed account home, external marker removal without adoption, persisted native host key, CLI and real menu actions; original and newly created metadata recorded | normalization, symlink/unknown-parent refusal, inode replacement, nonempty cleanup, corrupt records, default-home changes, mount-table identity, PID reuse, failed-attempt ownership, shared missing-dependency preparation; full schema rejection, replacement-container recovery, real lock contention, mount ownership recheck, simulated reboot device change, unmount timeout/cleanup failure, unrelated live PID refusal |
| Fixed isolation / runtime | restricted-project native refusals, expanded configuration/device drift refusal, isolated root identity and namespaces, seccomp filtering, denied forbidden device access and absent unauthorized host paths | owned provisioning, fixed profile/project drift, forbidden keys, malformed records, exact GPU/root/NIC device audit and safe stop/list during drift |
| Explicit migration / staged import | stopped legacy migration preserving data/user/inherited settings, real menu cancellation, native staged backup round trips, rejected data retained outside the destination | source-preserving preflight, mount guard, shared CLI/menu operation, staged import/copy sequencing, autostart retention, owned cleanup, primary failure/interrupt preservation and asynchronous native deletion |
| Tester behavior | localized per-stage results, persistent diagnostics, detailed logs, elapsed events, isolated cleanup | failed/interrupted group and later not_run status; cleanup/report errors produce failure; unit skips/details recorded; automatic discovery; Python optimization rejected because it disables assertions |

## Current limits

- Full real runs are on the current Ubuntu WSL host. Native Ubuntu/cloud hosts and other architectures still require external-machine verification.
- Fresh installation, socket recreation and WSL restarts were verified in a separate Ubuntu 24.04 WSL fixture in 0.2.8. Batches 0.2.9–0.2.11 verify prepared-host behavior; they do not repeat destructive provisioning on the development host. Same-user sudo/PTY checks and actual APT inside disposable containers complement controlled installer/failure tests. Non-Snap installation-policy support remains outside these audit batches.
- Disk/publication failure, LXD query corruption, native Error state, VM import rejection, timeout and interruption branches use fault injection. They are not claims of live disk exhaustion, daemon destruction, VM boot or natural timeout testing.
- Terminal checks use real PTYs and CSI/SS3 input. They do not certify every terminal emulator or SSH client.
- GPU coverage and its platform limits are described in the 0.2.1–0.2.11 sections below. Fixed project/profile enforcement and approved GPU resource verification are implemented in 0.2.11. Non-GPU host-resource sharing and custom network controls remain pending. The current WSL kernel reports AppArmor disabled; verified isolation does not include AppArmor confinement.

The historical integration group identifier `tui` remains for report continuity; it now runs the inline text-menu application. New groups are `invalid-inputs`, `lifecycle-repeat` and `unmarked-import`.

0.1.9 adds filesystems, filesystem-recovery and filesystem-menu (20 real groups in total). At that stage, actual ACL-bearing files, Windows-side access to FUSE mounts and offline VHDX mounting were not verified. Development SSHFS was unpacked from the Ubuntu repository because host sudo was unavailable; the missing-package installer branch is covered by controlled tests.

Batch 0.1.10 also verifies reproducible builds by building twice and comparing all asset SHA-256 values. Reboot device-number changes and registry corruption are simulated; the development host is not rebooted or intentionally corrupted. Metadata checks cover UID/GID/mode and content; no claim of ACL-bearing live fixtures or universal filesystem-ID stability is made.

A separate live smoke check also mounted and cleaned a path beneath a report directory containing spaces, and verified the private known_hosts file was populated. This is supplementary evidence, not an extra portable-suite group.

## Batch 0.1.11 coverage additions

- Shared dependency detection covers missing Python/snapd/SSHFS combinations, already installed LXD, grouped installation, one index refresh, refresh failure preventing install, and no-op ready systems. The product archive excludes the dependency setup module.
- Real PTYs verify transient APT output, retained native warnings, a controlled sudo-style terminal prompt and an APT question without a trailing newline. Redirected output verifies diagnostic retention without cursor escapes; failed APT retains its full log and exit status. Authentication fixtures never invoke real sudo or consume passwords. Real host SSHFS installation used the same helper through WSL root; it did not exercise actual password authentication.
- Menu tests cover circular Up/Down, single-option lists, multiple-choice checked state and confirmation defaults. Real product PTYs cover dedicated result/Return ordering and retained parent selections for creation, information, start, enter/exit, stop, export, deletion, import, stop-all, language and all three filesystem actions. A real PTY failure fixture verifies that the parent is absent until explicit return. The pre-Python Bash language fallback also received focused PTY wrap verification.
- FUSE configuration checks preserve existing settings/mode, are idempotent and refuse a dangling config symlink. A live focused comparison reproduced Linux-readable/Windows-denied behavior without allow_root, then verified Windows UNC list/read/create/edit/delete/mkdir/rmdir with allow_root. Mounting-user and root reads passed; a process changed to UID/GID 65534 after root entered the mount was denied, isolating the FUSE check from parent-directory restrictions. Existing test-file metadata remained 1001:1001:600. Evidence: validation/V0_1_11_WINDOWS.json.
- The portable filesystems group now performs Windows UNC operations when WSL interop is available and records a filesystem-windows-unc event. On native Ubuntu or hosts without interop, that access route is explicitly recorded as not_run; Linux mount tests still run. No claim of human-driven Explorer GUI validation, live ACL-bearing fixtures, offline VHDX support or universal Windows/WSL version compatibility is made.

Host SSHFS is now installed normally from Ubuntu packages. Host /etc/fuse.conf enables user_allow_other, while mas mount options remain allow_root. Earlier environment limits in historical batch notes are retained as history, not descriptions of the current host.

For count clarity, the 0.1.11 report contains 20 stages in total: the unit-test stage and 19 real integration stages. The 118 individual unit tests are reported separately inside unit_tests. Both the frozen local run and the public installation/test run passed these stages; see validation/V0_1_11_REPORT.json and validation/V0_1_11_PUBLIC_REPORT.json.

## Batch 0.1.12 coverage additions

- Real product checks keep two independent mounts through stop/start, read original content afterward, and start/stop with an explicit root mount. Existing exact-unmount, deletion guard, cleanup, metadata and Windows UNC tests remain. Menu shell-exit sessions separately verify default No, explicit stop and Escape cancellation, native container state and absence of another mas result/container menu.
- Seven focused lifecycle tests verify ordered calls to shared single-path foundations, exact/default path preservation, first/middle unmount abort, unchanged native and user-preparation failures, continued restoration after failures, no-op requests and a real nested registry lock retaining cross-process exclusivity. Failure injection does not claim a live LXD outage.
- Eight display/exit contract tests verify left alignment with Unicode display widths and colors, narrow columns and sanitized controls, complete wrapped input instructions, a single output boundary gap, no duplicate unmount table and uniform status columns, normal/error shell completion leaving the menu, pre-entry failure retaining its result page, and classification of post-shell failures. The eighth test renders twelve real PTY cases across both languages for creation, mounting, no-input operations, errors, cancellation and empty results, asserting single blank-line boundaries and consecutive diagnostics. Existing PTYs cover terminal restoration, circular navigation, Escape/default confirmation, resize and output history; the native menu suite covers actual product interaction.
- Validation remains scoped to the current Ubuntu WSL/LXD host. Native Ubuntu/cloud, other architectures, live ACL-bearing fixtures and offline VHDX access are not established.

Final local 0.1.12 run: 133 packaged unit tests, no skips; 20 reported stages (unit plus 19 real integration stages), all passed in 362.6 seconds; cleanup verified. Evidence: validation/V0_1_12_REPORT.json. Public-entry verification is recorded after publication.

## Batch 0.1.13 bootstrap boundary

The 0.1.12 public-entry check exposed a missing minimal-bootstrap dependency despite successful product tests. The new regression executes the actual generated shell download block against controlled bytes, then imports bootstrap/menu in an isolated -I interpreter. The tester carries install.sh for this boundary check; ordinary product artifacts do not. This raises packaged unit coverage to 134 tests. Complete native/public outcomes are recorded after execution.

Final local 0.1.13 verification passed all 134 packaged units and 20 reported stages in 365.7 seconds, with no skips or cleanup errors; see validation/V0_1_13_REPORT.json.

Both public 0.1.13 entry modes passed; the public --test run passed 134 packaged units and all 20 stages in 368.5 seconds, without skips or cleanup errors. Installed hashes matched, ordinary installation preserved the tester, Windows UNC passed and isolated resources were reclaimed. Evidence: validation/V0_1_13_PUBLIC_REPORT.json.


## Batch 0.1.14 responsibility boundaries

Packaged coverage increases from 134 to 153 unit tests. Nineteen new checks cover:

- Internal start success after sandbox preparation; preparation failure produces no complete-function success and no external restoration.
- Distinct native/function success in both languages; redirected output omits normal intermediate completion while retaining final success and native warnings.
- Import marking failure cannot produce full import success.
- stop-all continues after OSError and names the failed target.
- A nonzero shell result and an exit-handler failure both survive in the host-shell error.
- A missing confirmation provider safely declines without importing menu code.
- Reporting failure cannot mask an operation failure; client cleanup failure reports its secondary diagnostic while preserving the original error.
- Shared resource cleanup preserves primary exceptions and interrupts, while a cleanup-only failure remains a failure.
- Initial mount-journal failure and listener launch failure reclaim owned resources; a pre-existing work directory is preserved with a recovery record.
- Listener/mount probes do not launch or publish; both readiness steps retain one deadline and function success follows identity publication.
- Stop's native failure skips restoration without rewriting the error; stop's middle-unmount failure stops further calls; a state change before the locked recheck follows the no-op path without external mount coordination.

Existing native cases exercise default/root and multiple-path mount restoration through both start and stop, Windows UNC access, shell exit/menu behavior, confirmations, backups, ownership isolation and cleanup. Installer/package regressions execute the shell entry's actual minimal bootstrap dependency list, including the diagnostics dependency introduced by shared config cleanup.

This is behavior/failure-boundary coverage, not exhaustive branch coverage. Injected errors do not establish live disk-full or LXD-outage behavior. Native Ubuntu/cloud and fresh privileged host installation have not been rerun for this refactor. Frozen local and public-entry results follow below after execution.

Final frozen 0.1.14 validation: 153 packaged units and all 20 report stages passed in 369.4 seconds; no skips or cleanup errors. Windows UNC passed; project, mount root and registry entries were reclaimed. Evidence: validation/V0_1_14_REPORT.json. Public-entry verification follows publication.

Public 0.1.14 verification also passed 153 packaged units and all 20 report stages in 367.1 seconds, without skips or cleanup errors. Both fixed entry modes succeeded, installed hashes matched, normal installation preserved the tester, Windows UNC passed and isolated resources were reclaimed. Evidence: validation/V0_1_14_PUBLIC_REPORT.json.


## Batch 0.1.15 installation and menu regression

Nine added unit tests bring the packaged suite to 162. They cover exact top-level actions, conditional bulk-stop visibility across zero/one/multiple and stopped/running/transitional states, default first-container selection, refresh and reuse after stop-all, legal-name/control separation, query failure, preferences return selection, fragmented normal/diagnostic output, and a real same-user sudo child-terminal-read/prompt probe in interactive and redirected modes. The real sudo test exercises its actual PTY machinery without a password or host privilege change; it is not a password-authentication test. Existing controlled authentication, APT failure-log/status and package-combination tests remain.

A new native dependency-install case runs the shared packaged helper inside an isolated test container as sandbox. It invokes system sudo for actual APT update and SSHFS installation, records sudo/APT versions, preserves the full PTY transcript and verifies the installed binary. This adds a 21st report stage (unit plus 20 integrations). It does not replace validation of a fresh host's complete snap/LXD/group/FUSE bootstrap.

Native menu automation uses the merged entry, visits bilingual mas preferences, exercises create/import/container actions, creates a second managed container to make bulk stop eligible, then returns through the refreshed list. Existing real entered-shell exit behavior remains covered.

The original same-user sudo-rs 0.2.13-0ubuntu1.2 terminal-input/piped-output probe reproduced a child stuck in T; direct terminal and noninteractive input variants completed. Source and observations are recorded in validation/V0_1_15_SUDO_REPRODUCTION.json. Related upstream issue 1598 is a diagnostic lead, not a claim that this exact stop was traced to its specific defect. Frozen local and public verification results follow after execution.

Final frozen 0.1.15 validation passed 162 packaged units and all 21 report stages in 420.6 seconds, without skips or cleanup errors. The dependency fixture recorded sudo-rs 0.2.13-0ubuntu1.2 / apt 3.2.0 (amd64); Windows UNC passed and isolated resources were reclaimed. Evidence: validation/V0_1_15_REPORT.json.

Public 0.1.15 normal installation and --test entry both passed. The public suite completed 162 packaged units and all 21 report stages in 389.2 seconds, without skips or cleanup errors. Real container sudo/APT, Windows UNC, merged navigation, installed hashes, normal-install tester preservation and resource reclamation passed. Evidence: validation/V0_1_15_PUBLIC_REPORT.json.


## Phase 1 stable promotion of 0.1.15

No code or coverage counts changed. A fresh frozen matching-tester run passed all 162 units and all 21 reported stages in 394.0 seconds, with no skips or cleanup errors. Independent cleanup and Windows UNC checks passed. Published product/installer/tester checksums match local archives and included source; product/installer contain no test code. Pinned public installation passed without modifying the existing tester. The stable release's three downloaded assets and unchanged test prerelease were verified, and the existing latest-test resolver was checked after promotion. Evidence: validation/V0_1_15_STABLE_REPORT.json, validation/V0_1_15_STABLE_INSTALL.json and validation/V0_1_15_STABLE_RELEASE.json. Review inventory and remaining environment limits: validation/STABLE_0_1_15_AUDIT.md. Stable status does not expand tested-platform claims.


## GPU coverage — 0.2.1

Fifteen GPU unit tests cover default enable/explicit off, absent hardware, unmanaged/running guards, inherited-device conflicts, corrupt metadata, unsafe driver paths, changed devices, foreign runtime files, atomic-edit failures, delayed file removal, driver-directory refresh, cleanup with broken discovery, internal start failure propagation, and shared hardware-menu behavior. Existing operation-unit fixtures mock the GPU module explicitly; GPU behavior is tested in its own fixtures and native integration.

The portable `gpu` stage creates its own random target in the isolated test project. It invokes the actual product CLI and terminal menu, verifies non-privileged configuration, evaluates a real CUDA PTX kernel as sandbox via Python ctypes, checks read-only WSL runtime mounts, disables through the menu, confirms access is absent after restart, re-enables through CLI, and repeats computation. Non-GPU devices must remain unchanged. Resource inventory and computation results are saved under `gpu` in report.json. Test source lives only in the tester archive. No CUDA toolkit or Python package is installed for this probe.

Current measured GPU platform is WSL2/NVIDIA RTX 5090 Laptop GPU. Hosts without supported hardware explicitly report compute=not_run; successful non-GPU tests do not imply GPU compute coverage there. Native Ubuntu NVIDIA CDI is implemented but not hardware-verified. AMD/Intel discovery/backends are not implemented. Driver-directory refresh and broken-discovery cleanup are fault tests, not evidence of a real Windows driver upgrade. Project/profile enforcement remains outside this batch.

Final 0.2.1 execution: local frozen run passed 177 units / 22 stages in 459.4 seconds; public --test passed the same counts in 462.2 seconds. Both had no skipped units, unexecuted stages or cleanup errors; GPU computation passed in both. Public normal installation and all release asset hashes were verified separately. See validation/V0_2_1_* reports.

## Terminal synchronization — 0.2.2

Two real PTY regressions model a sudo-like result appearing before terminal restoration/input flushing. The output-only handshake loses exit; the shared prompt-aware probe succeeds. The fixture includes OSC titles/session sequences, a fragmented visible prompt and a guest hostname independent of TARGET. Twenty repeated rounds passed all 40 checks. Sleeps occur only in the fixture to create the race, never in production synchronization. All enter tests reuse the shared probe.

Packaged verification passed 179 units and all 22 native stages in 461.8 seconds, no skips or cleanup errors, including actual CLI and imported-container menu exits for all three stop answers. The controlled flush test demonstrates the failure mechanism without claiming syscall-level diagnosis on the user's host.

Published-entry verification also passed 179 packaged units and all 22 native stages in 487.6 seconds, with no skips or cleanup errors. Its menu stage passed in 83.3 seconds. Public product/tester hashes and all release asset digests match local validated archives. See validation/V0_2_2_PUBLIC_REPORT.json and V0_2_2_RELEASE_CHECK.json.

## Official WSL driver discovery — 0.2.3

Ten added unit tests cover the official command/JSON contract, ignored hooks, both CDI mount locations, deduplication, requery without caching, missing/failing/timed-out tool, invalid results, path/file validation, diagnostic retention, failed discovery preserving records/preventing native startup, off-mode independence and legacy multiple-directory replacement. Tests forbid production directory scanning.

The native GPU stage compares configured paths with official discovery, inventories coexisting driver directories solely inside the tester, checks excluded CUDA files are absent in the container, and records selected/excluded paths alongside actual sandbox CUDA computation. Current host selected one NVIDIA directory and excluded one historical directory. Driver updates are simulated in unit tests, not performed on Windows.

Frozen run passed 189 packaged units and all 22 stages in 449.4 seconds, no skips or cleanup errors. See validation/V0_2_3_LOCAL_REPORT.json. Existing platform limits still apply.

Public delivery checks for 0.2.3 verify the unpinned resolver selects the new version, all seven downloaded assets equal the validated local files, the downloaded product reports 0.2.3, and the raw fixed entry matches. Full public installation/testing was not rerun; the complete native test evidence above belongs to the identical frozen artifacts. See validation/V0_2_3_RELEASE_CHECK.json.

## GPU/diagnostic integration review — 0.2.4

Seven regressions cover invalid collection/option types, record-version typing before host discovery, cancelled hardware selection without requery, observer failure isolation, direct probe progress/log/events, actual product query diagnostics through both CLI and PTY with exactly-once display, and a real PTY GPU warning clearing its transient line. The CLI/PTY query fixture uses a disposable fake lxc and does not change host containers; its product invocation is the actual selected product archive.

Official command comparison verified identical device/mount lists, no generated hooks and warnings reduced from five to two on the measured LXD-bundled NVIDIA tool. Remaining warnings are retained. Frozen validation passed 196 packaged units / 22 native stages in 484.6 seconds, no skips or cleanup errors. Reports: validation/V0_2_4_LOCAL_REPORT.json and V0_2_4_DISCOVERY_CHECK.json.

Public delivery checks verified all seven downloaded artifacts, latest-test selection, fixed entry and downloaded product version. No second full suite through public installation was run; released files match those used in frozen validation. See validation/V0_2_4_RELEASE_CHECK.json.

## Portable subprocess regression — 0.2.5

Reproduced the 0.2.4 missing-mas failure using its existing archive from /tmp. Module-dependent PTY fixtures now reuse testing.python_command. The new runner regression checks unrelated cwd, a shadow mas.py, misleading parent sys.path[0] and PYTHONPATH isolation. The complete frozen tester was launched from /tmp with absolute archive paths and Python isolated mode: 197 units, 22 native stages passed in 452.2 seconds, no skips or cleanup errors. Evidence: validation/V0_2_5_LOCAL_REPORT.json. Checkout-only success and public byte equality are insufficient portability checks; published installation is verified separately.

0.2.5 public verification: all seven downloaded assets match the frozen local files; the resolver selects v0.2.5 and GitHub latest remains stable/0.1.15. Executed the actual public curl | bash --test entry from /tmp, installing the released product/tester and completing all 197 units and 22 native stages in 450.7 seconds, without skips or cleanup errors. The installed product reports 0.2.5. Evidence: validation/V0_2_5_RELEASE_CHECK.json and validation/V0_2_5_PUBLIC_REPORT.json.

## WSL runtime and entry adaptation — 0.2.6

201 packaged unit tests and 22 native stages passed from /tmp (452.2 seconds), no skips or cleanup errors. New tests exercise profile ownership/legacy migration and exact stable channel pairing. Native GPU validation independently loads the host CUDA driver and checks /proc/self/maps against mapped driver directories; it verifies login-shell nvidia-smi and profile removal on disable. No requirement that the multiple-directory warning occur was added. Public fixed-entry validation is recorded separately. Evidence: validation/V0_2_6_LOCAL_REPORT.json.

Public 0.2.6 entry validation from /tmp additionally passed 201 packaged units and all 22 native stages in 452.5 seconds, no skips or cleanup failures. See validation/V0_2_6_PUBLIC_REPORT.json; all eleven public assets and four channel routes are verified in validation/V0_2_6_RELEASE_CHECK.json. Stable pairing was verified by release checksums, without running the full stable suite again.

## GPU result reuse — 0.2.7

204 packaged units and 22 native stages passed locally in 453.3 seconds. New menu regressions count actual GPU discovery calls through the shared manager/module, check on/off defaults, read changed configuration after a failure, and preserve primary/secondary failures. Tester checks retain standalone hardware queries and repeated disable while reusing mutation results and independently validating LXD records. No warning-presence assertion or cross-operation discovery limit is introduced. Evidence: validation/V0_2_7_LOCAL_REPORT.json.

Public installation/test from /tmp passed 204 units and all 22 native stages in 447.9 seconds, no skips or cleanup failures. All eleven published assets match validated local artifacts; see validation/V0_2_7_RELEASE_CHECK.json and validation/V0_2_7_PUBLIC_REPORT.json. Separate isolated packaged-unit execution from /tmp also passed.

## Persistent socket access — 0.2.8

214 packaged units and all 22 native stages passed from /tmp (456.9 seconds), no skips/cleanup errors. Ten socket/install regressions cover group parsing, repair, ready no-sudo behavior, effective metadata/conflicts, timeouts and failure preventing publication. A separate disposable WSL validation reproduces the root:root denial and tests installer repair, socket recreation, default/custom-group reboots and no-sudo ready reinstall. The boot regression is a separate developer script because restarting the user's WSL in the ordinary tester would be disruptive. Reports: validation/V0_2_8_LOCAL_REPORT.json and validation/V0_2_8_WSL_SOCKET_REPORT.json.

Public 0.2.8 validation retained both attempts: the first had a Windows UNC Write mismatch (16 passed, 1 failed, 5 not run; successful cleanup); the unchanged-artifact full recheck passed 214 units and 22 stages in 449.3 seconds with no skips/cleanup errors. The first mismatch is an unresolved observation, not silently retried inside the suite. See validation/V0_2_8_PUBLIC_FIRST_ATTEMPT.json, V0_2_8_PUBLIC_REPORT.json and V0_2_8_RELEASE_CHECK.json.


## Reliability/interface audit — 0.2.9

Current count: 236 packaged units and 23 report stages: one unit-test stage and 22 real integration stages. Report-stage totals include the unit stage; they are not counts of native integration cases alone. The new configuration-concurrency stage obtains a real LXD ETag, changes a key and device through native lxc, verifies rejection of the stale update, and verifies that a fresh conditional update preserves both changes. GPU CLI/menu flows exercise the same writer in the separately supplied product.

Twenty-two additional units cover real Unix HTTP conditional requests and project parameters, preservation of writable fields, missing/invalid ETag, rejected writes without retry, native operation failure/timeout/malformed responses, local socket selection, concurrent GPU changes, damaged PATH markers, atomic publication failure/content/mode/idempotence, symlink preservation, captured diagnostics and both failure streams, TERM-ignoring real PTY processes, bounded unconfirmed KILL, child exec failure, cleanup failure/primary exception/final events/language restoration, fragmented JSONL/exactly-once diagnostics, live PTY warning order, recorded native failures, Windows UNC failure evidence and bilingual help for all commands. Existing menu/progress Unicode/width tests and isolated minimal-bootstrap verification cover shared text utilities.

Final frozen validation passed all units and stages in 483.2 seconds with no skips, unexecuted cases or cleanup errors. Windows UNC read/create/edit/delete/mkdir/rmdir and real GPU computation passed. Reports: validation/V0_2_9_LOCAL_REPORT.json and the preserved corrected packaging regression in validation/V0_2_9_PACKAGING_FIRST_ATTEMPT.json. Actual resource exhaustion and kernel-uninterruptible processes use fault tests rather than destructive host experiments. The old UNC mismatch remains unresolved; no retry was introduced.

Public 0.2.9 installation/test from /tmp passed the same 236 units and all 23 report stages in 488.9 seconds, without skips, unexecuted cases or cleanup errors. Installed product/tester bytes match the published assets, and the isolated project was independently confirmed reclaimed. All eleven assets and four fixed entry routes were checked; normal installation preserved the tester and stable pairing was verified by checksums. Stable remains stable/0.1.15. Evidence: validation/V0_2_9_PUBLIC_REPORT.json and validation/V0_2_9_RELEASE_CHECK.json.

## Remaining failure boundaries — 0.2.10

`tests/test_failure_review.py` adds eighteen tests:

- Real PTYs: reaped child with multiple queued reads, expected-pattern/finish decisions, final diagnostic observer and transcript, suppressed cleanup callbacks, failed transcript writes with confirmed process exit, EOF with a live child retaining the polling interval, and signaling the owned child when its process group is unavailable.
- Controlled deadlines/cleanup: continuously readable output, bounded native client reaping, output-report failure with later cleanup still attempted, CLI event failure preserving its primary exception, and cleanup timeout recorded while final events/output are still attempted. Existing TERM-ignore/KILL and unconfirmed-terminal-exit regressions remain active.
- GPU runtime files: malformed JSON, null/scalar/object/non-string directory entries, non-UTF-8 loader/profile contents, preserved ownership/configuration and no foreign-file deletion.
- Native failure data: real failing Python stand-in for a mutating LXD client with both output streams and no trailing newline; isolated directory-query, listener, SSHFS and fusermount failures retaining native details and operation context.
- Tester entry: invalid timeout rejects both installation and standalone setup before side effects; valid 300-second minimum reaches installation.

The existing distribution archive regression also verifies that tester-only case, PTY, cleanup-action and Windows UNC language keys are excluded from product/installer common catalogs. The packaged tester retains the optional test catalogs.

Final frozen local execution from /tmp passed all 254 packaged units and 23 report stages (unit plus 22 real integration stages) in 484.5 seconds, with no skips, unexecuted stages or cleanup errors. This follows a successful earlier candidate and an additional review/refinement. Report: validation/V0_2_10_LOCAL_REPORT.json. Public installation/test also passed all 254 units and 23 report stages from /tmp in 481.6 seconds, with no skips, unexecuted cases or cleanup errors. All eleven assets, four entries, normal installation preserving the tester, installed file hashes and project reclamation were checked. Reports: validation/V0_2_10_PUBLIC_REPORT.json and validation/V0_2_10_RELEASE_CHECK.json. Windows UNC passed this run; the historical mismatch remains unexplained and is not claimed fixed.


## Fixed isolation and backup compatibility — 0.2.11

Coverage increases to 287 packaged units and 26 reported stages (unit plus 25 real integration stages). The added policy module tests baseline drift, forbidden explicit keys and syscall allowlists, malformed records/device fields, extra devices, exact approved GPU resources, safe stop/list during policy drift, conditional permission refresh, source-preserving migration refusal/cancellation, safe inherited-setting preservation, mount guards and shared menu entry. Import foundation tests retain marking/final-completion failures.

Ten staging tests cover native import/copy sequencing without guest execution, original autostart restoration, unmarked stopped staging, pre-copy audit rejection, empty-stage cleanup versus data retention, creation ownership context, query/cleanup errors preserving primary failures, interruption, successful-copy cleanup failure, owner/occupant conflicts and foreign profile preservation before data deletion. Shared REST completion has an asynchronous-delete/native-failure regression using the real Unix HTTP fixture. These failures are injected; they do not claim naturally occurring storage corruption or daemon outages.

Three added native groups verify project-level refusal of privilege/raw configuration/kernel modules/BPF/nesting/interception/host disks, effective-policy refusal of an unsafe syscall override/changed GPU mapping/extra character device/pool-backed volume, preservation of rejected stopped backup data outside the production project, guest UID mapping and namespaces, active seccomp and denied forbidden-device access, absent host management/Windows paths, explicit migration rejection/cancellation and successful data/user/inherited-setting retention. Migration cancellation uses the real menu; accepted native migration uses CLI and menu reuse is unit tested. Existing native backup round trips, unmarked-backup import, GPU computation/switches, mount read/write and lifecycle restoration, Windows UNC and text-menu operations remain in the suite.

Temporary imports emit structured ownership context at resource creation, including interruption/failure paths. Tester recovery verifies the owner destination matches its unique project and reuses staging cleanup. No prefix-wide deletion or user failed-import cleanup is performed. The suite records actual runtime AppArmor availability; the current WSL kernel has it disabled. Native Ubuntu/cloud, native NVIDIA CDI, other GPU vendors, alternate storage backends and live exploit testing are not established by this report.

The first full candidate passed 285 units and all 26 stages in 595.2 seconds without skips or cleanup errors. The final frozen product passed all 287 units and all 26 stages in 605.7 seconds with no skipped/unexecuted checks or cleanup errors (validation/V0_2_11_LOCAL_REPORT.json). The rebuilt tester also passed all 287 units after removing a redundant fixture override; product/installer bytes are unchanged (validation/V0_2_11_FINAL_UNIT_REPORT.json).

The published test/test.sh entry independently passed all 287 packaged units and all 26 report stages from /tmp in 602.0 seconds, with no skips, unexecuted checks or cleanup errors (validation/V0_2_11_PUBLIC_REPORT.json). All eleven assets, four fixed entries, package separation, ordinary installation, installed hashes and reclamation of the test project, temporary imports and legacy migration resources were verified (validation/V0_2_11_RELEASE_CHECK.json). GPU computation and Windows UNC operations passed both complete runs. Existing Windows UNC diagnosis remains active; the historical intermittent failure was not reproduced or silently retried. Stable remains stable/0.1.15.
