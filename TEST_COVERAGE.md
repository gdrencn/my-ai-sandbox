# Automated test coverage

This maps the checks present in batch 0.1.11 to requirements and implementation. It is a behavioral coverage inventory, not a statement of 100% line/branch coverage. Final execution results are recorded in IMPLEMENTED.md and the versioned validation reports.

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
| enter / on_exit | running and stopped entry as sandbox, default keep-running, explicit stop, menu return and subsequent navigation | shared start/stop reuse; startup failure prevents shell; nonzero shell exit still invokes exit handler then reports failure |
| Shared _operation | one-second observations and elapsed events for real commands | state success alone cannot finish live command; exit code zero alone cannot skip state; marker required; nonzero native exit, LXD Error, failed query, interruption and 300-second simulated timeout; client termination and final events |
| Text menus | complete lifecycle, classification/navigation, settings persistence, cancellation, shell return, native progress and JSON history | CSI/SS3, radio/multiple choice, defaults, UTF-8 editing, viewport resize, Ctrl-C/Escape restoration, row-redraw history preservation, no alternate-screen/screen-clear sequences |
| Installation and packaging | separate installer invoked before final product testing; public normal/test entry; installed artifact hashes | missing snap/LXD sudo sequence, ready-system no-sudo, existing profile preservation, PATH idempotence, atomic copy-failure preservation and concurrent install publication, archive separation, mismatched version, bad download checksum prevents installation |
| Language / configuration | CLI get/set/help, menu language changes and cancellation, installation default in PTY | exact en_us/zh_cn identifiers, catalog keys/placeholders, saved defaults, broken config protection, unrelated preferences retained |
| Shared progress display | complete real menu/CLI lifecycle; permanent final results, separate structured waiting records | redirected output has no ticks/escapes; Chinese narrow width; actual output terminal sizing; query warnings without newlines; PTY results/diagnostics/menu/interruption history |
| Filesystem mounts | running/stopped reads and writes, root and default-home mounts, exact unmount, non-overlap, pre-existing paths, lifecycle refusal, killed-helper cleanup/retry, lost PID-record recovery, changed account home, external marker removal without adoption, persisted native host key, CLI and real menu actions; original and newly created metadata recorded | normalization, symlink/unknown-parent refusal, inode replacement, nonempty cleanup, corrupt records, default-home changes, mount-table identity, PID reuse, failed-attempt ownership, shared missing-dependency preparation; full schema rejection, replacement-container recovery, real lock contention, mount ownership recheck, simulated reboot device change, unmount timeout/cleanup failure, unrelated live PID refusal |
| Tester behavior | localized per-stage results, persistent diagnostics, detailed logs, elapsed events, isolated cleanup | failed/interrupted group and later not_run status; cleanup/report errors produce failure; unit skips/details recorded; automatic discovery; Python optimization rejected because it disables assertions |

## Current limits

- Full real runs are on the current Ubuntu WSL host. Native Ubuntu/cloud hosts and other architectures still require external-machine verification.
- Historical user logs cover a missing-LXD installation. The current batch does not remove the host LXD/Python installation to repeat fresh provisioning; sudo, package-manager failure and existing configuration behavior use controlled subprocess tests.
- Disk/publication failure, LXD query corruption, native Error state, VM import rejection, timeout and interruption branches use fault injection. They are not claims of live disk exhaustion, daemon destruction, VM boot or natural timeout testing.
- Terminal checks use real PTYs and CSI/SS3 input. They do not certify every terminal emulator or SSH client.
- GPU passthrough, host-to-container resource sharing and custom networking are excluded features, not covered functionality.

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

For count clarity, the current report contains 20 stages in total: the unit-test stage and 19 real integration stages. The 118 individual unit tests are reported separately inside unit_tests. Both the frozen local run and the public installation/test run passed these stages; see validation/V0_1_11_REPORT.json and validation/V0_1_11_PUBLIC_REPORT.json.
