# Current requirements — my-ai-sandbox 0.2.25

This is the consolidated current contract after accepted stable/0.2.25. Earlier proposals, superseded behavior, approvals and delivery stages are preserved in [the requirements history](docs/history/REQUIREMENTS_0_2_25.md). Current implementation and evidence are in [IMPLEMENTED.md](IMPLEMENTED.md). Pending decisions below are not execution authorization.

## Authorized documentation and handoff batch

Authorization on 2026-10-04: “OK，现在可以做完整文档整理和交接bundle了。”

1. Audit all maintained documents against current source, public channels and recorded evidence. Separate current requirements/behavior/verification from historical records; retain earlier decisions/reports and list unresolved features and platform limits explicitly.
2. Provide repository-owned workflow, architecture, development, test, release and UI instructions. A new Codex must not depend on this conversation or `/home/gordon/.codex` files. Supply a first-read entry and a copyable continuation prompt; retain the user's discuss-before-execution rule.
3. Publish a self-contained archive under `handoff/` on main. Include complete reachable history for main, release and all existing tags; current code, documents, tests and committed validation records; baseline commit identities; public release metadata; internal/external SHA-256 checksums; and offline restoration that refuses an existing destination. Do not package untracked host files, installed binaries, credentials, personal config or container/LXD data.
4. Verify checksums, Git completeness, offline restoration in a new directory, branch/tag identities, history, documentation links/anchors and first-read instructions. Rebuild the three accepted zipapps from the restored checkout and compare exact hashes; run all restored packaged units. This documentation-only batch does not require a new native full suite unless a concrete concern appears.
5. Upload documents/archive to GitHub and verify the public archive download and restore. Preserve all existing releases/assets/tags, latest stable/0.2.25 and the release branch. Keep version 0.2.25 and product behavior unchanged; record verified stages after their checks pass.

Completed on 2026-10-04; the document audit, full-history archive, restored rebuild/449 units and public download/restoration/preservation evidence are recorded in [IMPLEMENTED.md Stage 47](IMPLEMENTED.md#documentation-and-handoff-batch--stage-47). Pending feature decisions below remain separate.

## Authorized project-guidance handoff correction

Authorization on 2026-10-04: “OK，做吧。” after confirming that the only missing guidance is CODE_PRINCIPLE.md and that all three instruction files belong to the restored project.

1. Copy CODE_PRINCIPLE.md into docs/ without changing its principles. Keep CLI_TUI_GUIDELINES.md unchanged. Root AGENTS.md must state its repository scope and explicitly apply both development guides; do not install or alter files under any Codex global directory.
2. Update the documentation index, development guide, accepted decisions and fresh-Codex handoff instructions so all three project-owned guidance files are discoverable. Preserve the existing discuss-before-execution rule and recorded project exceptions.
3. Regenerate the complete handoff on main from a committed baseline containing the correction. Preserve every existing branch/tag identity and reachable historical object, including the already committed first archive. Make that prior-archive inclusion explicit in the builder invocation and manifest, rather than filtering history. Keep this generation's archive-upload and final-receipt commits outside its own baseline.
4. Verify exact guide contents/references, unchanged global files and product sources, local Markdown links, deterministic generation, all Git refs/history and offline restoration. Rebuild the accepted artifacts, run the restored packaged units, then verify the public archive/checksums/download and restore. Record the correction's evidence separately from Stage 47 receipts.
5. Publish the corrected project documents, archive, manifest and checksums at the existing handoff paths. Keep product version 0.2.25, stable/test assets, all existing Releases/tags and the release branch unchanged. This is a project-documentation and handoff-tooling correction, not a product release or global Codex configuration change.

Completed on 2026-10-04. All three project guidance files, corrected full-history archive, restored rebuild/449 units, public download/restoration and publication-preservation checks are recorded in [IMPLEMENTED.md Stage 48](IMPLEMENTED.md#project-guidance-handoff-correction--stage-48). The original Stage 47 receipts remain unchanged.

## Scope and shared architecture

The product is a Python-standard-library CLI and inline terminal menu for local LXD Ubuntu containers. The two interfaces call the same Manager. Product, installer and tester are separate zipapps; no third-party Python library is required. Host targets are Ubuntu 22.04+ on native Linux or WSL2, Python 3.10+ and systemd-capable snapd/LXD. A target is not a claim of measured compatibility; see [coverage limits](TEST_COVERAGE.md#current-measured-limits).

Use LXD's supported configuration, namespace, device and backup mechanisms. The isolation goal concerns unauthorized container access to Linux/WSL/Windows host resources; guest workloads, guest root and passwordless sudo are not filtered by a workload policy. Trusted host root/LXD administrators and upstream kernel/driver flaws are outside that protection claim.

## Commands and ownership

| Command | Required behavior |
| --- | --- |
| bare `mas` | Inline main menu. |
| `mas --version` | Running numeric version; no LXD dependency. |
| `new TARGET [--image IMAGE]` | Create, standard start, one-time preparation and validation, payload retirement, standard stop, verified final Stopped. |
| `list`, `info TARGET` | Structured local query; owned filtering or exact lookup; info returns complete JSON. |
| `start TARGET` | Complete startup, required sandbox/GPU preparation, verified Running; no enter flag. |
| `stop TARGET`, `stop --all` | Standard stop; all affects only owned containers and attempts every target before reporting aggregate errors. |
| `restart TARGET [-e|--enter]` | Standard stop then start, or stop then enter; failed stop prevents continuation. |
| `enter TARGET [--yes|--no]` | Standard start, sandbox login shell, shared post-terminal decision. |
| `delete TARGET [--yes|--no]` | Stopped, no recorded mounts, explicit confirmation, identity/state recheck, verified absence. |
| `export TARGET FILE [--yes|--no]` | Stopped; host path; default refusal to overwrite; native backup validation then safe publication. |
| `import TARGET FILE` | New name; staged native backup import and policy audit; verified stopped/owned result. |
| `migrate TARGET [--yes|--no]` | Explicit compatible stopped legacy default-project migration, no mounts/name collision, data preserved. |
| `mountfs TARGET [PATH]` | Container directory to host via native LXD file mount and SSHFS; omitted PATH uses sandbox's actual home. |
| `unmountfs TARGET [PATH]`, `mountedfs TARGET` | Exact recorded unmount, or host-side status/recovery listing. `--legacy` supports only old default-project listing/unmount recovery. |
| `hardware TARGET [gpu|network [on|off]]` | Shared status/configuration; stopped-target mutations; default network on and default supported GPU on. |
| `config`, `config get language`, `config set language zh_cn|en_us` | Shared atomic preferences, no LXD dependency. |

TARGET is 1–63 ASCII letters/digits/hyphens, starts with a letter and ends with a letter/digit. Remote/snapshot/option-like names are rejected. Production Project/Profile are `mas`, with project-local `default` also configured for native backups. Ownership requires type container and instance-local string `user.mas.managed=true`; a profile-only marker is insufficient. Queries failing or returning malformed data never establish absence. Name collisions do not overwrite any existing instance.

Default image is `ubuntu:<host Ubuntu VERSION_ID>`; on WSL this means its Linux distribution version. Unavailable images fail without fallback. Backups retain native MAC identity and restore semantics; they are not silently converted into clones.

## Completion, lifecycle and failure behavior

Native command exit zero and observed expected state are both necessary. Default per-operation timeout is 600 seconds, minimum 300; query state every second and on native completion. Native first-boot output is sampled independently every 50 ms. Preserve original stdout/stderr, primary/secondary failure distinctions and partial restoration details. Interrupt/timeout terminates and reaps the client, without claiming daemon-side operations are cancelled.

For real start/stop transitions, the same per-user filesystem registry lock spans recorded-path unmount, complete internal operation, and path restoration after success. Each foundation operates one path; first unmount failure prevents native transition; restoration attempts every captured path and reports failures. Already-Running start still prepares the user but does not coordinate mounts; already-Stopped stop is a no-op. Do not add empty hook stages, generic retry/rollback or duplicate lifecycle implementations.

New containers use native Ubuntu cloud-init/APT for exactly these 25 packages: sudo, ca-certificates, curl, wget, openssh-client, git, nodejs, npm, python3, python3-venv, python3-pip, python3-dev, build-essential, pkg-config, ripgrep, jq, patch, file, tar, gzip, xz-utils, zip, unzip, zstd, shellcheck. All come from the Ubuntu archive; the old official-Node download was superseded. Verify package state, sandbox commands, node/npm/npx and Python venv/pip; store `/var/lib/mas/development.json` and retire the cloud-init payload conditionally. Later starts/restarts/imports do not reinstall user-removed software. A prepared container missing required sudo reports that capability; earlier unprepared containers keep their compatible user setup. Guest root has no empty password; sandbox retains native passwordless sudo.

After a terminal returns, offer Stop container, Restart container, Return to mas, Exit mas; default/dismissal is Exit. Stop/restart ends at the host terminal after output. Return opens the selected-container menu with Enter focus and no result page. Preserve nonzero shell diagnostics/final failure status, including explicit menu return; do not infer reboot/shutdown from code 143. `--yes` means stop and `--no` means exit for terminal entry; plain restart rejects these consent flags. Native guest reboot/shutdown bypasses mas lifecycle coordination.

## Fixed isolation and resource approval

Project configuration is fixed: `features.profiles=true`, `features.storage.volumes=true`, `features.networks=false`, `features.images=false`, `restricted=true`; privilege isolated; lowlevel/nesting/interception blocked; backups allowed; NIC managed and limited to the approved managed bridge. Block unix-block, unix-hotplug, USB, PCI, infiniband and proxy devices. Leave `restricted.idmap.uid` and `.gid` absent.

Default disk/unix-char/GPU categories are blocked. The approved WSL NVIDIA backend permits disk and unix-char, with disk source prefixes restricted to `/usr/lib/wsl/lib` and validated exact active-driver subdirectories. Native NVIDIA CDI permits GPU. Category permissions do not authorize arbitrary devices: audit complete expanded definitions, approved root pool/NIC, exact GPU ownership, paths and readonly fields. Retain previously authorized exact prefixes while other containers may use them; never grant the driver-store parent.

Profile baseline: `security.privileged=false`, `security.idmap.isolated=true`, `security.nesting=false`, `security.syscalls.deny_default=true`, `security.devlxd.management.volumes=false`. Keep basic devlxd for cloud-init compatibility and `security.devlxd.images` absent. Require `raw.idmap`, `raw.lxc`, `raw.apparmor`, `raw.seccomp`, `security.syscalls.allow`, `security.idmap.base`, `security.idmap.size`, `linux.kernel_modules`, `linux.kernel_modules.load` absent. Reject BPF delegation keys and enabled syscall interception. Do not replace forbidden absent values with explicit false.

Audit policy/expanded config before native startup and after new/import/migration. Drift and malformed/unknown devices fail with concrete differences; do not silently repair/adopt them. Listing/information, safe stop and owned host mount recovery remain available. Configuration updates use valid ETags/If-Match and UUID rechecks; stale updates or same-name replacement must preserve competing data.

GPU uses fresh official NVIDIA discovery before actual stopped startup; no scanning/cached fallback or hook execution. WSL maps `/dev/dxg`, readonly runtime/driver paths and exact owned runtime files; DXG does not provide per-card isolation. Native NVIDIA uses LXD CDI and remains separately unverified. GPU changes require Stopped and preserve unrelated data; off is persistent and removes only owned devices/files. No GPU toolkit, driver or model framework installation.

Network off masks the approved inherited `eth0` with an instance-local `type=none`; IPv4/IPv6 external connectivity is removed, loopback retained. On restores the approved NIC/MAC. The shared bridge, profile, other containers and guest firewall are not changed. State survives lifecycle/backup; host LXD exec, security and file access remain usable offline. This is NIC allocation, not traffic/login ACL policy.

## Filesystem requirements

Container absolute directories map under `~/LXDCMFS/TARGET`; root `/` maps to TARGET's directory. Reject `..`, control characters, symlinks, overlap, foreign/changed host paths and identity conflicts. Preserve guest UID/GID/mode/ACL semantics, not host readability through permission rewriting. Root-authenticated native LXD file mounting serves loopback SFTP; SSHFS uses `allow_root`, dedicated private host-key state and host FUSE `user_allow_other` configuration.

Registry lives under `$XDG_STATE_HOME/my-ai-sandbox/filesystems` (default `~/.local/state`). Record mount/device/inode, UUID, process start/boot identity and owned directories. Reconcile residual mounts safely; never kill a reused/unrelated PID or remove a replaced/pre-existing/nonempty directory. Exact unmount cannot unmount a parent/child by approximation. Deletion requires explicit mount cleanup; start/stop reuse normal mount foundations. Locks coordinate this user, not all host users.

## Installation, language and interface

Installation prepares missing Python, snapd, LXD/lxc and SSHFS, merges needed APT work, enables required FUSE/group/socket access and initializes only an unconfigured LXD. Preserve existing LXD/profile/container state and installed tester on ordinary installation. Use system sudo for actual privileged commands, without separate sudo -v, password storage, keepalive, timeout changes or host sudoers edits. Prepare persistent 0660 LXD socket group ownership without restarting active LXD; refresh the target user's groups for installation completion and request a new daily-use terminal.

Language identifiers are exactly `zh_cn`/`en_us`; first default Chinese, later saved preference. Ask before installation; `--language` supports noninteractive choice. Configuration is `$XDG_CONFIG_HOME/my-ai-sandbox/config.json`, default `~/.config`; owned messages use catalogs, native diagnostics/identifiers stay unchanged.

Inline UI uses shared menu/text/output components, one title per page, display-cell alignment, navigation ↑/↓ circular and Enter/Right confirm, Esc/Left back/cancel/exit according to context. Text cursor keys edit input. Preserve history, parent focus, mode/cursor restoration and resize state without full-screen/scrollback clears. About is Language → About → Back, with `mas.__version__` and one Back choice. Progress is one transient physical row; actual native logs replace its fallback, unchanged text is not redrawn; permanent diagnostics clear it first. Results precede navigation. Noninteractive output contains no cursor escapes. The minimal pre-Python Bash adapter has explicit terminal size/ASCII limits. Applied instructions are [CLI_TUI_GUIDELINES.md](docs/CLI_TUI_GUIDELINES.md); conflicts already resolved in project decisions do not require repeated approval.

## Testing and release contract

Full suite order is install → one unit stage + 26 functional stages → one fresh-container full challenge → owned cleanup → report/summary. Detailed logs and JSON retain identifiers, native events, elapsed times, failures/skips/not_run and cleanup errors. Do not use optimized Python. Security orchestration shares one host module and immutable bundled probes; independent `test/security.sh` is host-only, selects/accepts TARGET and restores initial UUID/state. No public guest command or separate security-host.sh. Exact methods/ranges and limits are in [GUEST_SECURITY_PROBE.md](GUEST_SECURITY_PROBE.md).

Current immutable test tag is `v0.2.25`; stable tag is `stable/0.2.25` and GitHub latest. Versions are a.b.c: a stays 0 until explicitly authorized, b is phase 2, c increments once per agreed product submission batch. Documentation/receipts and stable promotion do not invent a new numeric version. Agreed product batches publish verified test prereleases; stable promotion follows explicit user acceptance.

Main owns development/test tooling/docs; release owns stable-only product/installer/shared-build source and product docs, with history advancing by stable publications. Stable has exactly mas.pyz, mas-install.pyz, SHA256SUMS; product/installer bytes equal the accepted numeric test. Test has the twelve assets listed in [DEVELOPMENT.md](docs/DEVELOPMENT.md#artifacts-and-branches). Stable installation reads release source; test installation reads main source. Stable testing gets actual stable product/installer and only the exact same-version immutable tester, validates both manifests and equality, and fails without fallback. Preserve every prior tag/release/asset. Verify final frozen assets outside the checkout and then public entries, ordinary tester preservation, source/download origins, GitHub digests/latest and independent resource cleanup.

## Pending decisions

| Subject | Current behavior | Required confirmation before work |
| --- | --- | --- |
| CPU, memory, process limits | No mas UI/CLI controls. Safe existing limits can survive migration. | Syntax, ranges, defaults, reset/live-change semantics, menu order and test targets for `limits.cpu`, `limits.memory`, `limits.processes`. |
| Root-disk quota | No delivered mas quota control; audit permits safe root size metadata. | Supported backend/filesystem quota behavior and UI/CLI/default/reset rules. |
| Traffic, login, custom ports | NIC on/off implemented; no ACL/login policy or port-forward interface. | Threat/scope model, destinations/protocols, host changes and rule lifecycle. |
| Basic devlxd | Available for instance/cloud-init compatibility; volume management disabled. | Whether/how to disable the basic interface without breaking initialization. |
| Host AppArmor | Recorded, disabled on measured WSL; not enabled by mas. | Demonstrated need, supported host configuration and validation plan. |
| Post-terminal restart-entry | Restart then return to host; separate `restart --enter` is implemented. | Whether the post-shell Restart choice should re-enter and how completion/navigation should change. |
| Additional GPUs/platforms | WSL NVIDIA measured; native CDI path exists; AMD/Intel automatic support absent. | Scope, resource model and independent machine validation before support claims. |

General host-directory sharing into containers, a generic resource whitelist, WSLg display/audio, Windows drive exposure, model installation/services, plugins and non-Ubuntu support are not delivered requirements. Do not start these solely because they appear in history or pending tables.
