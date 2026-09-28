# my-ai-sandbox Requirements

## 1. Scope

Python wrapper around LXD, with a complete CLI (`mas`) and a standard-library terminal text menu. Support Ubuntu on WSL2 and native Ubuntu, including cloud servers. Use the current WSL environment for development and real integration testing. Native Ubuntu verification must be reported separately.

Use LXD's existing functionality instead of reimplementing it. Each basic operation has one shared implementation, including its preconditions, waiting and postconditions. CLI, terminal text menu and composed operations call these functions. Third-party dependencies require explicit user approval. Do not introduce a plugin framework or speculative resource abstractions.

## 2. Commands

| Command | Behavior |
| --- | --- |
| `mas new TARGET [--image IMAGE]` | Create, but do not start, a standard container. TARGET is required; the image override is optional. Default to an Ubuntu image matching the host Ubuntu release. |
| `mas list` | List only managed containers. |
| `mas start TARGET` | Start one managed container. |
| `mas stop TARGET` | Stop one managed container. |
| `mas stop --all` | Stop all managed containers only; no TARGET. Reuse the shared stop function. |
| `mas delete TARGET [--yes | --no]` | Ask for confirmation, then delete a stopped managed container only. |
| `mas info TARGET` | Show managed container information and state. |
| `mas import TARGET FILE` | Import into an explicitly named, nonexistent TARGET. Never overwrite any existing instance. Verify STOPPED afterwards. |
| `mas export TARGET FILE [--yes | --no]` | Export a stopped managed container only. If FILE exists, ask whether to overwrite; default No; selecting Yes allows overwrite. |
| `mas enter TARGET [--yes | --no]` | Start through the shared start function if stopped, then open a terminal using native LXD execution. |
| `mas mountfs TARGET [PATH]` | mount a container directory read-write at its corresponding host path; see section 16. |
| `mas unmountfs TARGET [PATH]` | unmount the exact container directory previously mounted; see section 16. |
| `mas mountedfs TARGET` | list managed filesystem mounts and their actual status; see section 16. |
| `mas config [get language / set language en_us / set language zh_cn]` | Read or update shared user settings without requiring LXD. |
| `mas` | Open the terminal text menu directly when no subcommand is supplied. No `mas tui` command. |

TARGET is a local container name, not a remote, project, snapshot or VM selector. The first release operates on the local LXD server's default project, independent of the user's default remote. This limits accidental scope changes.

`enter` must call the shared function, not another mas CLI process and not a duplicate LXD start implementation. After the shell exits, call a shared exit handler asking whether to stop the container. Default is no; Enter leaves it running. Yes invokes the shared stop function. There is no `mas exit` command.

Image selection is confirmed: `mas new TARGET` requires no image argument and selects `ubuntu:<host Ubuntu VERSION_ID>`. Under WSL, use the Ubuntu release inside WSL, not the Windows version. For example, Ubuntu 26.04 selects `ubuntu:26.04`. An explicit `--image IMAGE` overrides this default. If the matching image is unavailable, report an error rather than silently falling back to another release. CLI and terminal text menu use the same shared image-selection logic.

Import and export take positional FILE arguments. Both CLI and terminal text menu require confirmation before deleting a container. Confirmation defaults to No; selecting Yes or passing --yes authorizes deletion or export overwrite. --no or cancellation declines confirmation. CLI and terminal text menu share the confirmation menu. Noninteractive input without explicit consent declines.

Enter the container as its default user, named `sandbox`, rather than root. Use the user's configured login shell (Bash for newly provisioned users). Provisioning this default user is an explicit exception to the original standard-container-only scope. The sandbox user has passwordless sudo, including sudo -i; do not set an empty root account password. Prepare and verify the user in the shared start function after starting the container; this preserves create as a stopped-container operation. Existing users are retained. Install sudo inside an Ubuntu container if missing, as required by the explicitly requested sudo capability.

Frozen or transitional states must not be silently treated as stopped. Report unsupported states explicitly.

## 3. Ownership and defaults

Identify managed containers with instance-local `user.mas.managed=true` metadata. Creation and import establish this marker. All reads and actions target only managed containers, except the existence check necessary to prevent name collisions. Never adopt, stop, delete, export or enter an unmarked instance. Native lxc use does not remove ownership. No independent container-ownership database or third-party library. Host mount recovery in section 16 only inspects/cleans that user's existing host records and does not adopt or act on an unmarked replacement container.

Use standard LXD default profiles. Do not add GPU passthrough, host-directory sharing into containers, custom network policies or mas profiles. Section 16 separately specifies container-to-host filesystem access; it does not authorize exposing host directories to containers. The ownership marker and the explicitly requested default sandbox user setup are the only mas-specific configuration. Use existing networking; fresh initialization prepares ordinary outbound connectivity. Existing misconfiguration is reported, not silently overwritten.

## 4. Completion and waiting

Poll every one second. Continue until an explicit successful postcondition or explicit failure is observed. Use LXD operation completion and structured state, not only process exit codes or fixed sleeps. A failed query does not mean an instance is absent. Default timeout is 600 seconds; configurable operation timeouts must be at least 300 seconds.

Postconditions: new/import = existing stopped managed container; start = running; stop = stopped; delete = confirmed absent; export = native export completed and a complete usable backup exists. Do not perform dependent work before success. Timeouts report operation, target, elapsed time and last observation; never claim the daemon cancelled merely because the client stopped waiting. Tests display and record operation waiting time, including errors.

## 5. terminal text menu

Provide access to all nine existing container operations, with list selection, input prompts, results and errors. The filesystem operations in section 16 must also be available through the same inline menus. Reuse shared functions directly. Restore ordinary terminal input before each operation and shell session; show the explicit result/Return flow in section 18 before restoring the parent menu. From 0.1.6, use inline terminal text menus without curses or an alternate screen; do not introduce third-party UI/Python dependencies.

## 6. Installation

Provide a fixed one-line entry that installs the latest test release. Install missing LXD and its matching lxc client automatically, using the newest available stable snap release rather than development channels. Reuse existing installations without unsolicited upgrades. Prepare missing system prerequisites and initialize a fresh LXD environment with storage and network. Use sudo when needed. Do not overwrite existing LXD configuration.

The fresh-install path must run `snap wait system seed.loaded` with administrator privileges, just like service setup and snap installation. Regression tests must cover missing LXD with snapd both already present and absent; a permission failure must not be mistaken for successful initialization.

WSL service prerequisites, user permissions and restarts must be handled or reported accurately. Implementation baseline: Ubuntu 22.04 or newer with Python 3.10+, systemd and snap support; dir storage for fresh initialization; installation under ~/.local/bin. Zipapps contain no architecture-specific binaries. Do not claim untested host versions or architectures have passed.

Native LXD backup semantics are preserved: imports retain network MAC identity and can conflict with a source container still present on the same network. This version does not silently turn restoration into cloning or rewrite network identities.

## 7. Automated testing

Release a standalone test tool with a fixed one-line download/install/run entry and versioned release assets paired with the product. It prepares missing LXD, runs real integration tests and outputs results and waiting times. No third-party test dependency without approval.

Test container names are `test-<unique-random-code>`. Operate on those explicit targets and clean up only resources created by that run. Never stop other managed user containers while testing `stop --all`: use a temporary isolated LXD test project for the integration test. The product itself still operates on default. Report cleanup failures. Keep installed LXD and permanent environment setup.

Cover new/list/start/stop/delete/info/import/export, default host-matching image selection (including WSL), explicit image overrides, unavailable-image errors without fallback, enter from stopped/running states as sandbox, exit default/no/yes, delete confirmation in CLI and terminal text menu, export overwrite confirmation and default refusal, CLI argument and error handling, bare mas opening the terminal text menu, all terminal text menu actions and terminal return, outbound networking, backup round-trip data integrity, ownership rejection, duplicate import, running-state restrictions and stop-all isolation. Exercise real terminal interaction rather than relying solely on mocks. Cover language selection, persistence, canonical identifiers, localized CLI feedback, immediate terminal text menu language switching and Chinese prompts; isolate test preferences from user configuration. Record unsuccessful, skipped and unexecuted tests accurately. Supplement with focused standard-library unit tests for failure paths that are unsuitable for provoking on a live host.

## 8. GitHub and releases

Publish every completed and validated development batch as a test prerelease to the public my-ai-sandbox repository. Test publication is a mandatory completion step, not an optional follow-up and does not require repeated approval. Verify that the fixed public installation/test entry resolves the new version. Stable promotion is separate; do not defer a completed test release while discussing future features or stable publication. Versions use a.b.c without a test suffix: a remains 0 unless the user explicitly authorizes 1; b is the project phase (currently 1); c is the complete submission-batch number, incremented once per batch, not per individual Git commit. The current development batch is 0.1.11. Filesystem mounts in section 16 are included. Product, installer and tester share each release version. A local version number does not imply publication. GitHub prerelease status is independent of the numeric version. Fixed installation selects the highest published numeric version, including prereleases. Preserve earlier release assets. Include checksums, installation instructions, tested environment and results.

## 8.1. Language and user configuration

Support exactly en_us and zh_cn throughout language filenames, persisted values and CLI arguments. Store all mas-owned interface messages in dedicated translation catalogs, shared by installation, CLI, terminal text menu, core operation messages and the test tool. Preserve native LXD, sudo, package-manager output and machine-readable identifiers verbatim, with localized mas context where needed.

Ask for language before installation starts. The first-install default is zh_cn; reuse the saved language as the default on subsequent installations. Noninteractive installation may explicitly select a language. Store user preferences in $XDG_CONFIG_HOME/my-ai-sandbox/config.json (default ~/.config/my-ai-sandbox/config.json). terminal text menu has a settings entry, initially containing language; changes take effect immediately and persist. CLI: mas config, mas config get language, mas config set language zh_cn, mas config set language en_us. CLI and terminal text menu reuse the same configuration functions. CLI configuration reading and changes must not require LXD.

## 8.2. System sudo behavior

Actual privileged operations use ordinary system sudo authentication when needed; do not run a separate sudo -v or an unnecessary command merely to authenticate. Preserve system credential caching and reauthentication. No password handling, custom authentication cache, keepalive, expiry policy, timeout extension or host sudoers edits. A prepared installation/test environment needs no host sudo. Missing package and FUSE setup behavior is specified in section 18.

## 9. Documentation and stages

Keep REQUIREMENTS.md and IMPLEMENTED.md inside this project. Before updating IMPLEMENTED.md at each code stage, check the actual implementation against requirements and correct discrepancies. Distinguish implemented, verified, blocked and pending work. Complete a final requirements audit before release.

## 10. Exclusions

No GPU passthrough, host-directory sharing into containers, resource whitelist, model installation, model service management, custom port forwarding, non-Ubuntu support, plugins or general diagnostic framework in this version. Container-to-host filesystem mounting is now an approved requirement in section 16, implemented in 0.1.9. A general container package-preinstallation feature has no agreed package list or installation policy and is not required by filesystem mounting; its priority and scope remain to be confirmed. The existing installation of sudo when needed for the sandbox user remains authorized.


## 11. Batch 0.1.4 acceptance criteria

1. Automatically configure the actual installation directory in the user's shell startup configuration. Preserve existing PATH entries and unrelated configuration. Repeated installation must not duplicate the managed block. Cover Ubuntu Bash login and interactive startup, and Zsh when selected. New-terminal instructions are acceptable; manual export commands are not a required installation step. Use one shared PATH setup function and test with isolated home directories, including paths with spaces.
2. From 0.1.4 onward, separate product, installation and automated-test artifacts. Historical numeric release pins retain their original implementation and packaging. Without --test, download only the product and files required for installation; do not download or install a tester. The product archive must not contain tests, the test runner or test-only presentation code. With --test, additionally download the version-matched standalone tester; that tester invokes the shared installer and then runs the complete test suite. The installer must not contain or invoke test orchestration. Reuse one installation implementation, including when group membership must be refreshed. Preserve explicitly pinned releases and the fixed latest-version entry.
3. Default to zh_cn when no preference exists, including bootstrap without Python. Previously saved language takes precedence over the default. Localize all mas-owned installation, operation, terminal text menu, test progress, stage names, diagnostic context and summary messages. Leave commands, options, identifiers and original external-program output unchanged. English-interface regression tests may retain their raw output in detailed logs; user-facing status and results remain in the selected language.
4. In an interactive test terminal, refresh normal progress on one transient line, including elapsed waiting time; erase it before permanent output and when a stage finishes. Retain one success summary per completed stage. Retain warnings, errors, unexpected output and failure details; clearly label deliberately provoked errors as expected errors. Do not suppress nonnormal output merely because the process exited successfully. Keep complete original subprocess and terminal logs and structured waiting records. Noninteractive output must contain no cursor-control sequences and must omit normal progress ticks while retaining stage summaries and nonnormal output.
5. Always provide a final test summary with passed, failed and unexecuted stage counts, total elapsed time, cleanup outcome and report path when the suite starts. Cleanup failures must be printed and cause nonzero exit. Test interruption and failures must clear transient progress. Verify artifact separation, orchestration order, shell PATH persistence/idempotency, language defaults and both terminal/nonterminal output behavior. Run the existing container integration coverage on the final artifacts before publication.

User-provided 0.1.3 logs show successful automatic installation on an Ubuntu WSL environment initially without LXD, followed by all 28 unit tests and 14 integration groups passing. This supplements the earlier existing-host validation; it does not establish native Ubuntu coverage.


## 12. Batch 0.1.5 — shared interactive UI specification

- Both TUI pages and interactive CLI choices use shared standard-library menu components, input decoding and selection rules. Options occupy separate left-aligned rows, with a visible focus marker and highlight. Instructions occupy their own row. Do not introduce third-party dependencies.
- TUI main menu separates Container management, Settings and Exit. Container management provides Container list, New, Import, Stop all and Back. Selecting a container opens Info, Start, Enter, Stop, Export, Delete and Back. Settings provides Language and Back. All nine container operations retain their shared Manager implementations and ownership protections.
- Up/Down moves focus; Enter/Right activates a menu item; Escape/Left returns to the previous page. Support both normal (CSI) and application (SS3) arrow-key sequences in real terminals. Focus and viewport remain valid after list changes or terminal resize. Empty lists remain navigable.
- Single-choice prompts use one option per row and default selection. First-install language defaults to the Chinese row; saved language selects its corresponding row. Deletion, export overwrite and stop-after-exit prompts default to No. The same confirmation policy applies in CLI and TUI. Cancellation never authorizes an action.
- Shared menu primitives also support multiple choices: arrows move focus, Space toggles a checkmark, Enter submits; focus and checked state are distinct. No new product setting or container bulk action is introduced solely to expose this primitive.
- Noninteractive operations use explicit arguments, not keyboard menus. --language supplies installation language; confirmation-capable CLI commands support mutually exclusive --yes / --no. For enter these govern stopping after the terminal exits. With no explicit consent and no interactive input, confirmation is declined. Legacy piped y/n is not a confirmation interface.
- The missing-Python bootstrap uses Bash built-ins for its initial language menu, with labels generated from the same catalogs and the same selection rules. After Python is available, installation, CLI and TUI use the shared Python menu implementation.
- Text fields for TARGET, image and paths remain editable text input, on their own pages with clear prompts and cancellation. Container shell entry suspends the TUI and restores the previous page after the shared exit handler. Container information supports scrolling and Back.
- Verification uses real PTYs and sends actual arrow sequences, Enter, Space and Escape, rather than relying only on former letter shortcuts. Cover both arrow encodings, initial focus, single/multiple selection, cancellation, CLI confirmations, main/submenu navigation, language persistence, empty lists and every TUI container operation, including export overwrite, delete defaults, enter/exit and stop-all. Test actual state/results, not just appearance. Complete artifact validation and update IMPLEMENTED.md before release.


## 13. Batch 0.1.6 — inline terminal text menus

This supersedes the fullscreen presentation in earlier sections. Bare mas opens an ordinary terminal text menu at the current output position. Never enter the alternate screen, clear the screen/scrollback or position a menu at the top of the screen. Completed menus, operation output and errors remain in terminal history. Only the currently active menu/input block may be redrawn locally. On resize, preserve history and keep selection valid.

Keep Container management, Settings and their existing actions, vertical left-aligned choices, Up/Down, Enter/Right, Escape/Left, default Chinese/saved language, default-No confirmations and shared single/multiple selection. Installation language, CLI confirmations and the interactive application reuse the same standard-library component. Explicit CLI commands and --yes/--no remain available. No new dependencies.

Restore normal terminal input before running a container command or opening its shell, and after confirmation, cancellation, interruption or failure. Commands print normal progress/results, then show the dedicated result/Back step before restoring the parent menu, as specified in section 18. Container information is printed completely into history, with a Back choice afterward; use native terminal scrollback instead of a fullscreen information viewer. Enter invokes the existing shared start/shell/exit handler and returns to the appropriate menu. Preserve lifecycle, ownership and waiting logic.

Verify actual PTY navigation, both arrow encodings, editing, Unicode input, resize, cancellation and terminal-mode restoration. Verify the absence of alternate-screen, screen-clear and scrollback-clear sequences in menu output; verify prior text and operation diagnostics remain in history. Run all nine container operations through the text menu, plus shared CLI confirmations, full real-LXD regression tests and public normal/test installation. Update IMPLEMENTED.md after verification and publish 0.1.6.


## 14. Batch 0.1.7 — coverage audit and failure-path verification

Audit the requirements, implementation record and current code together. Maintain a requirement-to-test coverage map with real-LXD, PTY and simulated-failure evidence distinguished; do not claim a line-coverage percentage or untested platform coverage.

Expand shared-operation regression tests for native completion versus observed state, native failures, LXD Error state, query failures/invalid data, ownership-marker verification, interruption and timeout cleanup. Validate export failure preservation, archive metadata, publication collisions, temporary-file cleanup and confirmation-time state changes; import must not mark failed or non-container imports. Cover idempotent start/stop, unsupported states, stop-all partial failure and enter failure ordering. Reject malformed structured LXD list data explicitly rather than treating it as absence or leaking an unhandled schema exception.

Extend real-LXD verification with invalid/missing targets and backup inputs, repeated lifecycle operations retaining sandbox identity/home/shell, and restoring a native unmarked backup with explicit post-import management marking. Preserve isolated projects, unique test names, minimum operation timeouts, diagnostics, history and cleanup.

Discover all packaged test modules automatically. Reports must record unit-test counts, failures, errors and skipped reasons separately from integration-group outcomes, plus test module names and test identifiers. Regression-test the runner's failure/interruption, cleanup-error and report-error exit semantics. Preserve normal/test artifact separation and validate final archives and public install/test entry before publishing 0.1.7.


## 15. Batch 0.1.8 — shared transient operation progress

CLI and inline text-menu operations must reuse the tester's terminal line-rendering primitive. In an interactive terminal, refresh normal waiting status and elapsed time on one bounded line; replace that line with a permanent final success or error result before subsequent menus, prompts or shell entry. Preserve warnings and native failure diagnostics without overwriting them. Preserve operation polling, state/command completion checks and structured test events. Redirected output must be plain text without cursor controls; omit normal waiting ticks and retain final results and diagnostics. Cover terminal rendering, interruption/failure, sequential operations, localized text, narrow terminal widths and noninteractive output. Keep test-specific diagnostic filtering outside the product archive and add no dependencies. This batch does not change stable release channels or resource/security configuration.


## 16. Phase-1 extension — container filesystem mounts

Status: implemented, published and publicly verified in 0.1.9; robustness audit in 0.1.10. This section supersedes the earlier proposal to attach mounting to start and unmounting to stop. The user has now authorized completing this extension and publishing 0.1.9 test, followed by a code/documentation/test audit and 0.1.10 test. No stable promotion is included.

### 16.1. Shared operations and lifecycle independence

Add shared mountfs, unmountfs and mountedfs functions. CLI and inline terminal menus call those same functions; cleanup and path checks are reused rather than duplicated. All targets must be mas-managed local containers under the existing ownership rules.

- `mas mountfs TARGET [PATH]`: mount the specified container directory for read/write access from the host.
- `mas unmountfs TARGET [PATH]`: unmount that exact previously mounted container directory and reclaim eligible host directories.
- `mas mountedfs TARGET`: list independently mounted container paths, host mount points and verified status, including abnormal or residual managed entries. The listed container paths identify exact unmount selections. A directory inside a mount is not a separate mounted item. Show an explicit empty result when there are no managed entries. Querying must not mount, unmount, start or stop a container.

Mounting is independent of start, stop, stop --all, enter and the exit handler. Those operations must not automatically mount or unmount. Native LXD 6.9 waits for open file/SFTP sessions before lifecycle transitions; therefore start from Stopped, stop from Running and delete must fail promptly with an explicit-unmount instruction while per-user managed mounts/residual records exist. Already-running/already-stopped no-op state handling is retained. This is a precondition, not automatic unmounting. Filesystem access should use LXD's native support for running and stopped containers; mounting must not implicitly start the container. If a container's default user/home has not yet been provisioned, report that the requested directory cannot be resolved or does not exist rather than provisioning it as a side effect.

No new background container-health monitor is included. Container failure does not imply that an independent host mount was automatically removed. A host/WSL shutdown removes live mounts but can leave mount-point directories and management records. Query and cleanup must distinguish live, failed and residual states instead of assuming that a directory's existence proves a working mount.

### 16.2. Path mapping and symmetric unmount semantics

Use exactly `~/LXDCMFS/TARGET` as the host mapping base for container `/`, where the host `~` is the invoking user's home. PATH denotes a container directory, not an arbitrary host destination. When omitted, resolve the actual home of the container's default sandbox user; do not hard-code `/home/sandbox` for an existing user with a different home.

| Command | Container directory | Host mount point |
| --- | --- | --- |
| `mas mountfs demo` | Default user's home, for example `/home/sandbox` | `~/LXDCMFS/demo/home/sandbox` |
| `mas mountfs demo /var/log` | `/var/log` | `~/LXDCMFS/demo/var/log` |
| `mas mountfs demo /` | `/` | `~/LXDCMFS/demo` |

The base is a path-mapping convention, not an automatic root mount. Mounting home alone must not also mount `/` at the base. Unmount with no PATH selects the default home; explicit PATH selects that exact mount. `unmountfs TARGET /` means unmount an independently mounted root, not unmount every entry for the container. If `/` is mounted but `/var/log` is not separately mounted, `unmountfs TARGET /var/log` must refuse without altering any mount or deleting any directory, explain that the path belongs to `/`, and identify the matching root-unmount command.

Multiple non-overlapping directory mounts for one target are allowed. Reject ancestor/descendant overlap and do not stack mounts. Resolve path identity consistently so alternate spellings cannot evade overlap or ownership checks or escape the intended host mapping base. Accept absolute container paths only, normalize repeated/trailing separators and dot components, reject parent traversal and control characters, and reject symlink components rather than follow aliases. Omission selects home without host-shell tilde expansion. Record default-home mounts so default unmount can select the originally mounted home even if the account home subsequently changes; ambiguous multiple default selections fail with an explicit-path instruction.

### 16.3. Conflicts, ownership and cleanup

Refuse to create a mount over any existing destination: regular file, empty or nonempty directory, symbolic link (including a dangling link), or another mount. Do not overwrite, remove or hide pre-existing content. Common parent directories previously created and tracked by mas can be reused for non-overlapping mounts. Validate parent paths as well as the leaf; do not follow an unexpected host symlink into another location.

Track sufficient ownership and source identity to distinguish mas-created mount points and intermediate directories from user paths. Container ownership remains the LXD marker; mount/directory records do not replace it. The storage format of mount records remains an implementation decision. Verify actual mounts in addition to records; do not claim success solely from a command exit code. Use the shared one-second waiting, timeout and elapsed-output rules for completion checks.

- Normal unmount: verify the mount has gone, then remove its tracked empty mount-point directory and any tracked empty parents no longer used by other mounts.
- Failed mount: verify no residual mount remains before reclaiming only empty directories created by that attempt.
- Unmount failure, nonempty directories or uncertain ownership: preserve the path and report the reason. Do not force deletion or recursively delete contents.
- Abnormal exit: verify recorded ownership and actual mount state before cleanup. Never infer authority to delete from the name or location alone. A prior mas record alone is insufficient if the path has since been replaced.

Cleanup removes empty host mount-point directories only after unmounting; it must not delete the container directory or its contents. Residual entries must be visible in mountedfs and handled by the shared unmount/cleanup logic. Do not claim a failed mount is healthy or silently overwrite it on a later request.

### 16.4. Native permissions and dependencies

Use standard LXD filesystem access and its native file permission behavior. Do not add custom UID/GID mappings. Section 18.1 explicitly permits the host FUSE allow_root access option without rewriting container permissions. Mounting/unmounting must not chmod, chown, rewrite ACLs or otherwise alter container file/directory permissions. Explicit host file operations through a successful read/write mount act on the container's files, preserving native operation semantics. Do not promise sandbox ownership for newly created host-side files or universal access to every special path; observe and document native behavior before considering adjustments.

The direction is container-to-host access. No host home or other host resource may be shared into the container without explicit user authorization.

LXD's direct filesystem mount requires SSHFS on the host. It does not require installing SSHFS, an SSH server or another package inside the container. Prefer the native LXD mounting command and its standard behavior. The existing rule requiring explicit approval for third-party dependencies still applies before installation. Install missing host SSHFS using the existing installer and system sudo flow. Use the native LXD loopback SFTP listener with authenticated SSHFS running as the invoking user, retaining native file permission behavior and applying the approved host FUSE option in section 18.1; this avoids making a snap root-owned direct mount inaccessible to the ordinary user. Scope private connection/state files to that user. Listener and SSHFS processes survive CLI exit, with identities tracked for safe unmount cleanup. No custom SFTP server or Python third-party library is introduced.

### 16.5. Required verification and remaining decisions

Verify CLI and menu paths, default and explicit homes, root and non-overlapping mounts, read/write/create/delete through the mount, running and stopped containers, independence from start/stop, exact unmount matching, ancestor/descendant refusal, managed-target scope, pre-existing files/directories/symlinks/mounts, truthful query status, failed mounting, failed unmounting, stale records, interrupted cleanup, concurrent conflicting requests and safe retry after cleanup. Use isolated test targets and host directories. Confirm existing container ownership/mode/ACL metadata is not rewritten by mounting, and record native new-file ownership and permission behavior without adding corrective changes. Keep warnings/errors and final summaries, with transient waits and complete structured test records.

Deletion must refuse while that user has managed mount/residual records for the target; explicit unmount performs recovery first. A missing target may have its existing recorded mounts cleaned up without adopting another instance; an existing unmanaged replacement remains untouched while recorded host resources may be recovered without accessing that replacement. Stable publication remains separate. Implementation records must identify the per-user mount-management scope and limitations of external lxc actions.


## 17. Batch 0.1.10 — post-0.1.9 audit and reliability completion

Status: implemented, verified and published as test v0.1.10. Both fixed public entry modes were verified; measured results and remaining environment limits are in IMPLEMENTED.md and TEST_COVERAGE.md.

Audit all current documentation and source against the shipped 0.1.9 behavior. Preserve native LXD/SSHFS permission behavior and the existing scope; do not add GPU/resource policy, custom SFTP, package presets or stable promotion. Finish with versioned test publication and public-entry verification, not merely local changes.

- Serialize same-user filesystem mount creation and container lifecycle transitions/deletion with the same record lock; recheck ownership/state after acquiring the lock so a concurrent mount cannot slip between a precondition and native execution. External LXD operations remain outside this lock's scope.
- Validate every persisted mount/directory/process field before acting, preserve corrupt records and paths, and never signal a PID based only on its number. Recover owned native helpers after interrupted PID-record publication by checking process identity and exact per-mount command arguments.
- Use persistent filesystem identity plus inode/owner for new directory records so changing kernel device numbers across host reboot does not imply directory replacement. Read legacy device/inode records conservatively; do not invent a safe migration when their identities cannot be verified.
- Querying/cleaning existing per-user mount records must remain possible after an external deletion or replacement of the container. These recovery operations affect only recorded host resources, never the replacement container. New mounts still require current mas ownership.
- Unmount completion includes native detach, helper termination and empty-directory cleanup. Report total elapsed time and preserve diagnostics; do not emit final success before cleanup finishes. Timeouts leave recoverable records and user-facing errors.
- Use unique atomic installer staging files and reproducible zipapp builds. Preserve saved preferences, archive separation and numeric version selection.
- Extend fault tests and real integration checks for schema corruption, stale process records, locking, reboot identity simulation, helper interruption, command timeouts, preserved paths, explicit/default-home changes, original metadata and native new-file metadata. Distinguish simulated failures from live tests and document remaining platform limits.

## 18. Batch 0.1.11 — completed changes

- [x] Audit every text-menu action for an explicit entry, result and return flow, rather than fixing only mountedfs. Cover container listing/information, creation, start, stop, stop-all, deletion, import, export, mountedfs, mountfs, unmountfs, settings/language, confirmations, and terminal entry/exit. A selected function must visibly open with a separating blank line and an appropriate title before its content, prompts or progress. Query results must remain visible with a dedicated Return choice. Executed operations must retain their result and offer Return instead of immediately redrawing the full parent menu. Return restores the parent menu and its selection. Handle empty results, errors and cancellation consistently; preserve terminal handoff and the exit-time stop question. Implement shared function/result presentation and return handling, with actions supplying their title/content/operation, not independent per-menu UI implementations. Verify ordering and navigation in real PTYs, including diagnostics, so results cannot appear attached to a freshly redrawn parent menu or be obscured by it.
- [x] Investigate the reported 0.1.10 host-access failure: mounting reports success and creates the expected ~/LXDCMFS/TARGET/home/sandbox path, but opening the final sandbox directory reports insufficient permission. The user confirmed that the failure occurs in Windows File Explorer, which displays a permission-denied dialog while opening the mounted directory. The original user's shell comparison is unavailable; a local Linux/Windows UNC comparison and its measured limits must be recorded. Reproduce Windows File Explorer access and compare it with access from the mounting user's WSL shell; inspect actual mount/helper state and effective access identity before selecting a fix. Distinguish a verified mount-table entry from successful file access through the user's intended access route. Preserve container ownership, modes and ACLs; do not silently introduce permission overrides, UID/GID mappings or broader host-user access. Discuss any required change to the agreed native-permission policy before implementing it. Add a regression for the confirmed cause and document which access routes were actually tested; prior Linux-side read/write tests do not establish Windows-side access compatibility.
- [x] Implement circular Up/Down navigation once in the shared selection component: Up from the first option selects the last, Down from the last selects the first, and a single-option list remains on that option. Apply the same behavior to every menu, single-choice list and multiple-choice list through reuse, including installation language selection and confirmations. Preserve checked values while moving focus and retain existing Left/Right, confirmation, cancellation and text-editing semantics. Do not add per-menu navigation implementations. Verify both wrap directions and single-option behavior in the shared component, with representative terminal integration checks that consumers use it.
- [x] Remove the standalone startup `sudo -v` step from installation/testing. The actual privileged operation, such as `sudo apt-get`, should trigger ordinary system authentication when needed. Do not add an apt operation merely to authenticate; flows needing another privileged command use that command's normal sudo behavior. Preserve system-managed credential caching and reauthentication, without custom password handling or keepalive. When implementation is authorized, update affected prompts, tests and current-behavior documentation together.
- [x] Consolidate initial dependency preparation across the fixed entry, installer and install-and-test flow. Detect missing prerequisites before installation, group compatible APT package installations, and avoid repeating `apt-get update` within the same installation flow. Retain necessary bootstrap ordering, install only missing prerequisites, preserve existing installations/configuration, and keep Snap operations separate from APT index refreshes. Reuse shared dependency preparation instead of duplicating it between normal installation and testing.
- [x] Apply the shared output standard to APT dependency preparation, including index refresh and package installation. In interactive terminals, normal progress must refresh in place and disappear when the step completes; retain concise stage-success summaries rather than scrolling ordinary APT output. Preserve warnings, errors, abnormal output and failure details permanently, with native diagnostic wording unchanged. Do not classify output as abnormal solely because it was written to stderr, and do not hide diagnostics through blanket suppression. Keep system sudo authentication and any required interaction visible and usable. Redirected output must omit transient progress/control sequences while retaining summaries and diagnostics. Reuse the existing progress/diagnostic presentation where applicable and preserve Snap's compact native progress behavior.
- [x] Verify the installation changes with dependency combinations, no-op preparation on ready systems, normal/test flow reuse, APT refresh deduplication, interactive and redirected output, retained warnings on successful commands, failed refresh/install diagnostics, and usable system authentication. Update current-behavior and coverage documents after implementation and verification.

Status: the complete checklist is implemented and verified for test 0.1.11. Measured outcomes and remaining environment limits are recorded in IMPLEMENTED.md and TEST_COVERAGE.md. Published as test v0.1.11 and verified through both public entry modes; earlier release assets remain unchanged.

### 18.1. Approved filesystem compatibility direction

Validate SSHFS `allow_root` as the least-broad compatibility option for Windows access through WSL. Enable the host FUSE `user_allow_other` configuration gate when needed for non-root mounting, preserving unrelated settings. The mount option remains `allow_root`, not `allow_other`; authorization is for the mounting user and root, not all host users. Preserve container UID/GID/mode/ACL metadata and existing directory guards. Verify the Windows UNC filesystem path, Linux-side access, and denial to another ordinary host identity. If this option cannot meet those requirements, report the evidence before broadening access. Installation must prepare the prerequisite through normal system privilege handling, and old mounts require explicit unmount/remount to use new options.
