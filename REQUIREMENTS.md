# my-ai-sandbox Requirements

Sections 1–26 describe phase 1 requirements and delivery history. Sections 27–37 describe phase 2 plans and subsequent batches. Later implemented and verified sections supersede earlier defaults; pending sections do not describe current behavior.

Current baseline: published and publicly verified test batch 0.2.9. Stable remains stable/0.1.15. Section 37 records the audit improvements. Restricted project/profile policy, CPU/memory/process controls, network-policy changes and the stable-only release branch are still pending under sections 27 and 34.

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

`enter` must call the shared function, not another mas CLI process and not a duplicate LXD start implementation. After the shell exits, call a shared exit handler asking whether to stop the container. Default is no; Enter leaves it running. Yes invokes the shared stop function. There is no `mas exit` command. After this exit handler and its output, terminate this mas invocation and return to the host shell, including menu entry and post-shell errors; section 21 defines the result-page exception.

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

Publish every completed and validated development batch as a test prerelease to the public my-ai-sandbox repository. Test publication is a mandatory completion step, not an optional follow-up and does not require repeated approval. Verify that the fixed public installation/test entry resolves the new version. Stable promotion is separate; do not defer a completed test release while discussing future features or stable publication. Versions use a.b.c without a test suffix: a remains 0 unless the user explicitly authorizes 1; b is the project phase (currently 2); c is the phase's submission-batch number, incremented once per batch, not per individual Git commit. The current authorized development batch is 0.2.9 (section 37). Product, installer and tester share each release version. A local version number does not imply publication. GitHub prerelease status is independent of the numeric version. Fixed test installation selects the highest published numeric test version; stable installation selects the latest promoted stable release. Preserve earlier release assets. Include checksums, installation instructions, tested environment and results.

## 8.1. Language and user configuration

Support exactly en_us and zh_cn throughout language filenames, persisted values and CLI arguments. Store all mas-owned interface messages in dedicated translation catalogs, shared by installation, CLI, terminal text menu, core operation messages and the test tool. Preserve native LXD, sudo, package-manager output and machine-readable identifiers verbatim, with localized mas context where needed.

Ask for language before installation starts. The first-install default is zh_cn; reuse the saved language as the default on subsequent installations. Noninteractive installation may explicitly select a language. Store user preferences in $XDG_CONFIG_HOME/my-ai-sandbox/config.json (default ~/.config/my-ai-sandbox/config.json). terminal text menu has a settings entry, initially containing language; changes take effect immediately and persist. CLI: mas config, mas config get language, mas config set language zh_cn, mas config set language en_us. CLI and terminal text menu reuse the same configuration functions. CLI configuration reading and changes must not require LXD.

## 8.2. System sudo behavior

Actual privileged operations use ordinary system sudo authentication when needed; do not run a separate sudo -v or an unnecessary command merely to authenticate. Preserve system credential caching and reauthentication. No password handling, custom authentication cache, keepalive, expiry policy, timeout extension or host sudoers edits. A prepared installation/test environment needs no host sudo. Missing package and FUSE setup behavior is specified in section 18.

## 9. Documentation and stages

Keep REQUIREMENTS.md and IMPLEMENTED.md inside this project. Before updating IMPLEMENTED.md at each code stage, check the actual implementation against requirements and correct discrepancies. Distinguish implemented, verified, blocked and pending work. Complete a final requirements audit before release.

## 10. Exclusions

Historical phase 1 exclusions were GPU access, host-directory sharing into containers, a general resource whitelist, model installation, model service management, custom port forwarding, non-Ubuntu support, plugins and a general diagnostic framework. Section 16 subsequently added container-to-host filesystem mounting, and section 28 added the independent GPU module and its explicitly recorded resource mappings. General host-directory sharing, a general resource whitelist, model installation/service management, custom port forwarding, non-Ubuntu support and plugins remain outside the implemented scope. A general container package-preinstallation feature has no agreed package list or installation policy and is not required by filesystem mounting; its priority and scope remain to be confirmed. The existing installation of sudo when needed for the sandbox user remains authorized.


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

Historical 0.1.9–0.1.11 lifecycle rule (superseded for start/stop by section 20 in 0.1.12): mounting is independent of start, stop, stop --all, enter and the exit handler. Those operations must not automatically mount or unmount. Native LXD 6.9 waits for open file/SFTP sessions before lifecycle transitions; therefore start from Stopped, stop from Running and delete must fail promptly with an explicit-unmount instruction while per-user managed mounts/residual records exist. Already-running/already-stopped no-op state handling is retained. This is a precondition, not automatic unmounting. Filesystem access should use LXD's native support for running and stopped containers; mounting must not implicitly start the container. If a container's default user/home has not yet been provisioned, report that the requested directory cannot be resolved or does not exist rather than provisioning it as a side effect.

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

Verify CLI and menu paths, default and explicit homes, root and non-overlapping mounts, read/write/create/delete through the mount, running and stopped containers, preservation across start/stop under section 20, exact unmount matching, ancestor/descendant refusal, managed-target scope, pre-existing files/directories/symlinks/mounts, truthful query status, failed mounting, failed unmounting, stale records, interrupted cleanup, concurrent conflicting requests and safe retry after cleanup. Use isolated test targets and host directories. Confirm existing container ownership/mode/ACL metadata is not rewritten by mounting, and record native new-file ownership and permission behavior without adding corrective changes. Keep warnings/errors and final summaries, with transient waits and complete structured test records.

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

## 19. Batch 0.1.12 — explicit interaction wording and consistent spacing

Status: implemented and verified in batch 0.1.12. Final local evidence is recorded in IMPLEMENTED.md; public publication verification follows as the completion step.

- [x] Audit mas-owned interactive wording in both zh_cn and en_us. State clearly what the user should enter, select or confirm, identify the object being acted on, and explain the effect of leaving an optional input empty and pressing Enter. Use user-facing names such as container name and backup file path instead of exposing TARGET, FILE or an unexplained sandbox home in prompts. Preserve CLI syntax, command arguments, machine-readable identifiers and original external-program output. Cover creation, container listing/selection and information, start, enter/exit, stop, stop-all, deletion, import, export, mountedfs, mountfs, unmountfs, settings/language, installation language selection and every confirmation prompt. Keep the two languages semantically equivalent and store owned messages in the shared catalogs.
- [x] For creation, use the function title `新建容器` followed by `请输入容器名：`. Replace the image prompt with `选择镜像版本（不输入，直接回车默认使用宿主 Ubuntu 版本）：`. Preserve the existing default image selection and accepted image argument semantics; this is a wording change, not a new image picker or image-input format.
- [x] For mounting, retain a target-specific function title such as `挂载文件系统：test` and use `请输入容器内目录路径（不输入，直接回车默认使用 sandbox 用户的主目录）：`. Apply the same explicit-action/default principle to the remaining audited prompts without inventing new defaults or changing operation behavior.
- [x] Define spacing through shared presentation components: visibly separate function entry from preceding content; leave exactly one empty line between a function title and its first input/content block, between successive input blocks, between the completed input area and the operation progress/result area, and between the result area and the result/Back menu. Remove accidental doubled blank lines. When an operation has no input or no waiting event, preserve the same title-to-result boundary. Waiting updates stay on the transient line; successful completion replaces that line without introducing extra blank lines for every observation.
- [x] Keep success, native warnings/errors and related result details in one continuous result block. For example, mount success, the native SSH known-host warning and the mounted host path belong together; retain the warning verbatim. Show the dedicated result/Back menu after one empty line, and restore the parent and its selection only after explicit return. Apply the same boundary rules to success, errors, cancellation and empty results. Preserve normal terminal handoff and the existing exit-time stop question.
- [x] Add regression checks for wording/default semantics and visible spacing/order through shared components and representative real PTYs. Cover Chinese and English creation and mounting, consecutive inputs, operations without inputs or waiting ticks, results containing native diagnostics, empty results, errors, cancellation and return to the retained parent selection. Verify rendered blank-line boundaries rather than merely searching for title strings. Preserve inline history, circular navigation and transient progress behavior. After implementation is separately authorized, verify the changes before updating IMPLEMENTED.md, then follow the standing test-release/public-entry verification requirement for the completed development batch.

### 19.1. User confirmation and further filesystem discussion

The user reports that access through the previously problematic Windows File Explorer route now succeeds with the current mounting functionality. Record this as user-reported validation, distinct from the earlier automated Windows UNC API checks. The previously reported access failure is no longer an outstanding issue in this checklist. This confirmation does not establish additional Windows/WSL version coverage, ACL coverage or offline VHDX support. The subsequently agreed start/stop mount orchestration is specified in section 20. No additional resource exposure or permission changes are authorized by this confirmation.


## 20. Delivered changes — reuse single-path mounts around start/stop

Status: implemented and verified in batch 0.1.12. This section supersedes the existing requirement to refuse a start/stop state transition solely because this user has mas-managed mounts. Deletion guards and explicitly invoked mountfs/unmountfs behavior remain outside that change.

- [x] Before a genuine start or stop state transition, capture the container's current mas-managed mount paths and the information needed to restore those same container/host path mappings. Capture the actual resolved paths before unmounting removes their records; do not resolve a default home again and accidentally restore a different directory. Limit orchestration to this user's mas-managed mounts for that container; do not unmount resources belonging to other users or tools.
- [x] Unmount sequentially by calling the existing single-path unmount foundation once per path. Wait for each call's normal completion before moving on. On the first failure, stop attempting further paths and do not enter the container start/stop operation. Report the failure and instruct the user to finish unmounting manually, then explicitly retry start/stop. Distinguish already completed unmounts, the failed path and paths not attempted. The lifecycle caller does not add rollback or remount earlier successful unmounts.
- [x] Only after every required unmount succeeds, run the existing shared container start/stop flow and its completion checks. After that flow succeeds, restore the captured paths sequentially by calling the existing single-path mount foundation once per path. A failed restoration does not prevent attempts for the remaining paths. At the end, clearly report that container start/stop completed, identify every path whose mount restoration failed and provide the container/host path information needed for manual recovery. Do not reverse the completed container state transition in response to a restoration failure.
- [x] Preserve responsibility boundaries: start/stop only capture the path list, sequence calls, decide whether to continue and summarize results. Do not introduce separate batch mount/unmount operations or duplicate their native commands, waiting, validation, cleanup, retries or recovery logic. Existing rollback/cleanup inside each foundation still runs normally. Any necessary changes to mount/unmount behavior must be made in those foundations and reused by manual and automatic callers, rather than implemented as lifecycle-only behavior.
- [x] Do not unmount/remount solely for repeated start on an already-running container or repeated stop on an already-stopped container. Preserve the existing internal sandbox preparation within start. enter and stop-all inherit the orchestration through the same start/stop functions; do not duplicate orchestration in CLI, menus, terminal-exit handling or stop-all.
- [x] Audit repeated calls and their composition before implementation: shared-parent directory reclamation, ownership and path-conflict checks, exact/default-path identity, deletion and recreation of mount records, existing registry-lock scope, nested-lock deadlocks, concurrent requests, per-operation waiting, diagnostic preservation and result summaries. Resolve any required single-path behavior change in the shared foundation. Preserve refusal to overwrite a host path occupied before restoration. Do not add forced or lazy unmount as an implicit way to make a lifecycle operation proceed.
- [x] Verify multiple-path success through both start and stop; first/middle unmount failure with no later unmount or lifecycle call; partial mount-restoration failure with all remaining paths attempted and an exact manual-recovery summary; normal single-path cleanup on failure; shared-parent preservation; existing/default path identity; retained ownership guards; no-op state requests; enter and stop-all reuse; lock coordination and CLI/menu output. Confirm that manual and automatic invocation use the same foundational behavior. Update IMPLEMENTED.md only after verification and follow the standing test publication requirement when development is separately authorized.

The intended result is restoration of the same mount paths after a successful state transition, with a temporary access interruption; it is not a promise that already-open files or active transfers remain usable without interruption. User-managed external lxc operations are not automatically orchestrated by mas.

Confirmed failure policy, clarified by the user: a failure from the existing start/stop operation propagates normally and prevents execution of its success-only mount-restoration suffix. Preserve the original lifecycle failure behavior; do not add an extra exception handler, state probe, rollback, restoration attempt or special recovery report for that failure.


## 21. Batch 0.1.12 — selection rows and return to the host shell

Status: implemented and verified in batch 0.1.12 together with sections 19 and 20. Test-release publication and public-entry verification remain completion steps; no stable promotion.

- [x] Remove redundant informational tables when a selection list can contain the required information. Implement multi-column, left-aligned selection rows once in the shared menu component, with display-width-aware space padding, optional status colors and readable status text. Use consistent column structure across the entire list. If a status column is needed, include it for every data row, including normally mounted entries; never add/remove columns independently per row. Treat Back as a navigation control, not a data row. Escape user-provided control characters and keep alignment correct for Chinese text, English text, colors and terminal resize.
- [x] Unmount selection shows container paths once, omits host destinations and omits the status column when every entry is normally mounted. If abnormal/residual entries require status information, show a status column on all entries. Container selection also uses the shared column presentation for name and status. Retain separate tables only where necessary information cannot reasonably be integrated into the selection control. Pure query views remain readable lists/tables.
- [x] Retain both a foundational operation-success message and a flow-completed message where currently provided; the user considers their meanings distinct. Correct spacing rather than deleting either message solely because both indicate success.
- [x] After an entered container terminal exits, run the shared exit handler and ask whether to stop, default No. Print normal results or actionable cleanup errors, then terminate this mas invocation and return to the host shell. This applies to both direct CLI entry and entry through menus. Do not display another result/Back page or return to the mas menu, including when post-shell cleanup fails. The user can invoke mas again for further work. Preserve nonzero status for errors. Failure before actually entering the container shell remains an ordinary operation error, not a completed shell-exit flow.
- [x] Verify combined selection rows and column alignment, complete normal/abnormal status columns, left alignment, narrow/Unicode rendering and selection behavior. Verify host-shell return after menu entry with default No, explicit stop, cancelled stop confirmation, nonzero shell exit and cleanup failure, without duplicated start/stop logic. Include actual PTYs and native container checks alongside focused failure tests. Apply the shared spacing and wording rules to these flows and preserve terminal history.

## 22. Batch 0.1.13 — bootstrap dependency correction

The 0.1.12 native/product tests passed, but public entry verification failed before language selection because the minimal bootstrap download list omitted mas/output.py, now required by the shared menu. Completing the authorized release requires correcting that list. Preserve v0.1.12 and earlier published assets; deliver a new numeric test release, without stable promotion.

- Include every runtime module needed by the shared language menu in the minimal bootstrap download. Keep ordinary installation free of tester downloads.
- Package the generated shell entry in the standalone tester solely for a regression that executes its actual download-stage Python block against controlled source bytes, then imports bootstrap and its menu in a clean interpreter without the development checkout. Do not duplicate a second download manifest in tests.
- Verify all packaged unit tests, isolated bootstrap imports, ordinary public installation and public --test installation with the complete native test suite. Record the failed 0.1.12 public check separately from successful final results, and identify 0.1.13 as the supported fixed entry.

Section 22 implementation and local frozen-package verification are complete: 134 packaged units and all 20 report stages passed. Public-entry completion is recorded after release.

Sections 19–22 are implemented, verified and delivered in test v0.1.13. Both fixed public entry modes resolved the corrective version successfully; public --test passed 134 packaged units and all 20 reported stages. The 0.1.12 entry failure and measured 0.1.13 results/limits are recorded in IMPLEMENTED.md. Earlier release assets remain unchanged; no stable promotion occurred.

## 23. Batch 0.1.14 — explicit operation responsibilities

Status: implemented, verified and delivered as test v0.1.14. Frozen local and public --test runs each passed 153 packaged units and all 20 report stages; both public entry modes succeeded. No stable promotion or 0.2.x configuration features.

- Define stages by responsibility, not position relative to a native command or location on the host. Internal work includes validation, native execution, required success/failure branches, completion checks and owned-resource cleanup. External pre/post-processing coordinates other functionality; post-processing only follows successful completion of the complete internal mas operation.
- In start, native Running is an intermediate success. sandbox provisioning and passwordless-sudo verification remain in the internal successful-start branch; provisioning failure means mas start failed and prevents mount restoration. Preserve the original internal failure propagation without extra state queries, rollback or recovery handlers.
- Express lifecycle external pre-processing, internal execution and external post-processing as named, shared private steps. Pre-processing and post-processing sequentially call the existing single-path unmountfs/mountfs foundations. Preserve first-unmount-failure abort, continued restoration after individual failures, original/default path identity, no-op behavior and the registry lock spanning the entire sequence. No new batch mount implementation.
- Treat import type/ownership marking and export archive validation/final file publication as mandatory internal work. Distinguish native-step completion from complete internal function success in progress events and localized presentation. Publish complete internal success only after required work completes; restoration failures still state that start/stop completed.
- Separate mount resource preparation, listener readiness, SSHFS launch, mount observation and identity publication. Pure readiness probes must not launch processes or publish records. Preserve the existing shared deadline for mounting after listener launch. Protect early per-attempt resource creation with the foundation's existing cleanup path. Never reclaim unowned/pre-existing resources; preserve recovery records when cleanup cannot complete safely.
- Keep resource cleanup distinct from external success-only processing. Reuse one detach/helper/directory/record cleanup implementation for explicit unmount and failed mount recovery. Preserve the primary failure if cleanup or reporting also fails; report secondary failures where possible, without adding lifecycle-level recovery.
- Keep confirmation policy in the shared operation layer but inject terminal presentation from CLI/menu entry points; absence of a confirmation provider declines. CLI, menus and composed operations retain existing decisions and exit semantics. Move shared result formatting out of CLI so menus do not import the CLI module.
- Keep enter's session-ended handling separate from native shell exit-code success: after the shell returns, invoke on_exit even for a nonzero shell code; pre-entry failures do not invoke it. When both the shell and on_exit fail, retain both diagnostics and return a nonzero result to the host shell. stop-all must aggregate both domain failures and operating-system failures consistently, without swallowing interrupts.
- Give deletion's no-mount guards names reflecting their actual purpose. Keep ownership/state checks after confirmation and under locks; do not remove intentional repeated validations. Query, interactive shell and long-lived filesystem processes retain their distinct execution lifecycles.
- Review every basic function (new, list, info, start, stop, delete, import, export, mountfs, unmountfs, mountedfs), composed function (enter, on_exit, stop-all), settings and installation for responsibility/completion boundaries. Do not mechanically introduce empty stage functions or a generic hook framework. Correct the current documentation overview while preserving clearly identified historical records.
- Add focused boundary tests for both start and stop, locked/no-op paths, early mount failures, pure mount probes, preserved deadlines, native-step versus function success, dual shell/exit failures, aggregate OSError handling, reporting/cleanup failures and confirmation injection. Retain real product and public installation tests, and verify isolated resource cleanup, packaged dependency completeness and reproducible builds.

## 24. Delivered changes — deletion guard wording

Status: implemented, verified and delivered in test v0.1.15.

- [x] Correct the deletion guard's obsolete instruction about manually unmounting before start/stop. The message must specifically instruct the user to unmount and clean recorded mounts before deleting the target. Start/stop already coordinate unmount and restoration through the shared foundations.
- [x] Update both zh_cn and en_us messages and affected test expectations. Preserve the deletion guard and existing start/stop behavior; this change is wording only.

## 25. Batch 0.1.15 — dependency installation and a flatter main menu

Status: implemented, verified and delivered as test v0.1.15. Local frozen and public --test runs each passed 162 packaged units and all 21 report stages; both fixed public entry modes succeeded. Requirements were recorded before product changes, and IMPLEMENTED.md was updated after verification.

- Reproduce and fix dependency installation hanging with sudo-rs 0.2.13 and terminal input/piped output. Preserve native sudo authentication and required package-manager interaction without password handling, separate sudo -v, keepalive, global sudo configuration changes or replacing system sudo. Validate the execution arrangement using real sudo and terminal/process-group behavior; do not rely exclusively on a fake sudo executable. A minimal process probe must not install packages or leave paused child processes behind. Distinguish reproduced behavior from a proven upstream patch attribution.
- Fix normal APT fragments persisting as permanent output when reads time out before a newline. Handle fragmented lines and carriage-return updates while keeping normal progress transient, preserving warnings/errors/unknown output and making prompts without newlines usable. Keep one shared dependency implementation for bootstrap and installer, including environments where Python is not yet available. Preserve failure status and complete failure logs.
- Bare mas opens the merged top-level menu titled my-ai-sandbox, with these entries in order: view containers, create container, import container, mas preferences, exit. Remove the extra container-management navigation layer. The Chinese preferences label is `mas 选项`; the English label is `mas Preferences`. Children retain Back; the top-level control exits. Future per-container configuration belongs after container selection; future host-management features would be top-level peers of preferences, but neither feature is implemented in this batch.
- Move Stop all containers into the container-selection page, after container rows and before Back. Show it only when there are more than one mas-managed containers and not every reported state is exactly Stopped. Query failure remains an error, never an empty/all-stopped result. Refresh eligibility after returning from actions; preserve selection where still valid. Use a control key that cannot collide with a legal container name.
- Stop-all calls the existing Manager.stop_all, which sequentially reuses Manager.stop for each managed target. Do not duplicate lifecycle or mount orchestration. Menu visibility does not alter CLI stop --all, including zero/one-container cases. State is the live LXD state regardless of whether it was reached through mas or native lxc. Already-stopped behavior and independent mount recovery remain unchanged.
- Update both language catalogs, navigation tests and native menu automation. Verify zero/one/multiple containers, all-stopped/mixed/transitional states, name/control separation, refresh after stopping, settings return, top-level exit and host-shell return after entered sessions. Retain the deletion guard's behavior with corrected deletion-only wording.
- Final verification covers packaged units, native integrations, public normal/test entry, artifact separation and resource cleanup. Record any unverified privileged fresh-host installation boundary explicitly; do not represent a same-user sudo probe as a root package installation test.

Dependency execution detail: keep the privilege boundary outside the APT output pipeline. Interactive installation retains terminal input; redirected output uses noninteractive EOF for package input, with authentication still owned by sudo. Add a real APT update/SSHFS installation case inside an isolated test container as sandbox using its standard mas sudo access. This fixture-only package installation does not change product container provisioning.


## 26. Phase 1 stable promotion — 0.1.15

Status: audited, verified and published as stable/0.1.15. The unchanged test v0.1.15 prerelease remains available. Final audit passed 162 units and all 21 report stages; pinned public installation and published asset verification passed.

Review the current requirements, implemented behavior, source, packaging and test coverage before promotion. Run the frozen matching tester against the unchanged product; require all 162 units and all 21 reported stages to pass, without skips or cleanup errors. Verify published asset hashes and absence of tester modules in the product and installer. If a blocking defect is found, fix and validate a new numeric test batch before promoting it.

Preserve the existing v0.1.15 test prerelease and all its assets. Publish a separate non-prerelease under the Git tag stable/0.1.15: the tag prefix identifies the distribution channel; the program version remains 0.1.15. The stable assets are mas.pyz, mas-install.pyz and SHA256SUMS only. Product and installer bytes must exactly match v0.1.15 test. No test runner, bundled tests or test report is distributed as a stable asset. The release description links the matching test release and repository validation evidence.

Keep the existing latest-test entry unchanged. Document stable installation with the existing --release v0.1.15 option, which downloads only the product and installer from the matching immutable numeric release. Document stable verification with --test --release v0.1.15, which obtains the same-version tester from the preserved test prerelease. Do not claim that the unpinned installation command selects stable. Mark the separate stable release as GitHub latest. This promotion does not change product code, version numbering, host resource policy or supported features.

Record audit findings, final test results, matching hashes, published asset inventory and installation verification after completion. Preserve the distinction between current WSL verification, user-reported fresh-install evidence and unverified native Ubuntu/cloud environments.

## 27. Phase 2 — pending container isolation and hardware configuration

Status: project/profile policies and non-GPU hardware controls remain pending. GPU implementation and measured scope are recorded in section 28. The earlier requirements-only update did not authorize runtime changes; the user subsequently authorized the GPU implementation and tests.

The isolation goal is to protect the Linux/WSL host and its Windows host from unauthorized container access through host resources. Container workloads and in-container administrative activity are outside mas policy. Use LXD's supported isolation mechanisms first; host changes require a demonstrated need. Upstream Windows, WSL, Linux, LXD, LXC and GPU-driver vulnerabilities remain upstream responsibilities. Retain the current default network behavior in this batch; additional network controls and login policy are deferred.

### 27.1. Project configuration — fixed security policy

- [ ] Use a dedicated mas project with `features.profiles=true` and `restricted=true`. Project naming and migration of phase 1 containers remain to be confirmed.
- [ ] Set `restricted.containers.privilege=isolated`, `restricted.containers.lowlevel=block`, `restricted.containers.nesting=block`, and `restricted.containers.interception=block`.
- [ ] Set `restricted.backups=allow` to retain export functionality.
- [ ] Set `restricted.devices.unix-block=block`, `restricted.devices.unix-hotplug=block`, `restricted.devices.usb=block`, `restricted.devices.pci=block`, and `restricted.devices.infiniband=block`.
- [ ] Use `restricted.devices.proxy=block` as the baseline; revisit only in the separate network design. NIC/network policy remains to be confirmed.
- [ ] Use `restricted.devices.disk=block` as the root-disk-only baseline. If GPU runtime libraries require host disk devices, define the necessary `allow` policy and `restricted.devices.disk.paths` prefixes, together with read-only device configuration, before implementation.
- [ ] Resolve `restricted.devices.gpu` and `restricted.devices.unix-char` according to the verified GPU implementation. Allow only the categories required by that implementation; category permission does not constitute an exact device/path whitelist. GPU category permissions belong to project policy; actual per-container GPU allocation belongs to hardware configuration.
- [ ] Treat project policy as fixed mas-managed configuration. Provide no user-editable project settings in the terminal menu or a general mas CLI escape hatch for altering the baseline. This does not claim to prevent a host LXD administrator from using native administrative tools.

### 27.2. Profile configuration — fixed container security baseline

- [ ] Use a dedicated mas profile with `security.privileged=false`, `security.idmap.isolated=true`, `security.nesting=false`, and `security.syscalls.deny_default=true`.
- [ ] Leave `raw.idmap`, `raw.lxc`, and `raw.apparmor` unset; retain LXD-managed identity mapping and confinement. Check the effective configuration including inherited values.
- [ ] Determine `security.devlxd` after checking dependencies and the guest-interface scope. Its value remains to be confirmed; distinguish `/dev/lxd` from the host administrative socket.
- [ ] Treat this baseline as fixed mas-managed configuration, without user-editable profile settings in the terminal menu or a general mas CLI escape hatch. CPU, memory and process limits, and GPU allocation are not fixed profile policy; they belong to section 27.3.

### 27.3. Hardware configuration — editable per container

GPU and the hardware menu are delivered by section 28; CPU, memory and process controls remain pending. GPU defaults and CLI semantics below are superseded by section 28 where specified.

- [ ] Add a `硬件选项` / `Hardware options` menu item after selecting a container. It contains GPU allocation, CPU limits (`limits.cpu`), memory limits (`limits.memory`), and process-count limits (`limits.processes`). These controls are per-container configuration, not global mas preferences.
- [ ] Provide equivalent CLI operations through the same shared configuration functions. CLI syntax, value ranges, defaults, reset behavior, running-container change semantics, and menu ordering remain to be confirmed.
- [ ] GPU access is authorized by default when a supported discrete host GPU is available; the user can explicitly disable it. Record the devices and runtime-library resources necessary for that allocation. Preserve the fixed security baseline; resolve any conflict before implementation. GPU support must cover the intended WSL compute use case; native Ubuntu uses its applicable LXD-supported mechanism and requires separate validation.
- [ ] Prefer LXD's existing GPU/device mechanisms and vendor-supported resource discovery. Any additional third-party dependency still requires explicit approval. GPU compute support does not implicitly authorize WSLg display, audio, Windows drive mappings, host home directories, or host management sockets.

### 27.4. Validation and unresolved integration work

- [ ] Audit expanded instance configuration, project restrictions, and actual runtime confinement in the current WSL environment. Record supported protections and measured limitations rather than inferring them solely from successful startup.
- [ ] Validate real GPU computation in a non-privileged container using the selected official mechanism. Verify access as `sandbox`, actual device/library exposure, read-only runtime mappings where applicable, and the effective GPU selection scope. Device enumeration alone is insufficient.
- [ ] Before implementation, resolve phase 1 migration, imported configuration handling, baseline drift handling, GPU enable/disable lifecycle, and hardware defaults/CLI semantics. Preserve managed-container ownership boundaries and existing filesystem/lifecycle reuse.
- [ ] After authorized development, verify CLI/menu equivalence, baseline enforcement, hardware changes and GPU computation; update IMPLEMENTED.md only with completed and verified behavior. Publish the resulting development batch through the established test-release process.


## 28. Phase 2 first batch — independent GPU module

Status: implemented, verified and published as test v0.2.1. Local and public --test each passed 177 packaged units and all 22 stages; both public installation modes succeeded. Project/profile hardening and CPU/memory/process limits remain pending; retain current network behavior.

- [x] Implement GPU as a shared, independent module with capability detection, status, enable, disable, resource inventory and verified cleanup. Use LXD-supported GPU/device operations. Preserve unrelated devices/configuration and refuse ambiguous ownership or configuration drift.
- [x] Expose `mas hardware TARGET` for hardware status and `mas hardware TARGET gpu [on|off]` to query/change GPU configuration. The container menu gains Hardware options, with GPU as its first option only when a supported discrete GPU is available. No CPU, memory, process-limit or network controls in this batch.
- [x] Default GPU to enabled on supported hosts for newly created containers; persist an explicit off setting across starts. Handle existing/imported containers through the same module before startup. Missing hardware hides the menu switch; CLI mutation reports unavailable rather than claiming success. Never silently replace another GPU configuration.
- [x] Store the requested GPU setting and module-owned resource inventory in instance metadata. Inventory includes native device configuration and any explicit library mappings. Verify native automatic resource handling through integration tests. A failed operation must retain actionable evidence and must not be reported as successful.
- [x] Require a stopped container for configuration changes in this first batch, avoiding removal while tasks hold GPU handles. Query is available in either state. Do not automatically stop a running container. Configure default access before native startup; GPU setup failure prevents startup and its external post-processing.
- [x] Use official LXD CDI where usable. Any compatibility alternative must use LXD device primitives, retain non-privileged operation, limit read-only mappings to necessary GPU runtime resources, and document actual exposure. No additional packages without explicit approval.
- [x] Test default enablement, explicit off, repeated operations, unavailable hardware, unmanaged containers, conflicting devices, metadata corruption, and native failure handling. Native GPU tests must verify sandbox access, CUDA initialization and device memory transfer/computation rather than enumeration alone, absence after disable, restoration after re-enable, resource inventory and preserved non-GPU configuration. Record unavailable-host GPU compute coverage explicitly.
- [x] Verify terminal menu and CLI reuse, translated output, existing lifecycle/filesystem behavior, and packaged tests; update implementation/coverage/release documentation.
- [x] Publish the test release and verify the public entry.

### 28.1. Validated implementation choice and platform boundary

Historical 0.2.1 implementation below; section 30 supersedes its driver-directory scanning with official active-driver discovery in 0.2.3.

The initial implementation targets NVIDIA CUDA GPUs. WSL2 NVIDIA is the current real validation environment; native Ubuntu NVIDIA uses LXD CDI and has not been GPU-tested here. AMD and Intel discrete GPU discovery/backends remain unimplemented, not implicitly covered by the NVIDIA checks. Hosts without a supported NVIDIA device do not show the GPU switch.

The current LXD 6.9 snap CDI probe failed with NVML Driver Not Loaded. The WSL backend therefore uses LXD's native unix-char device for `/dev/dxg`, mode 0666 inside the container, and read-only disk devices for `/usr/lib/wsl/lib` and only driver-store subdirectories containing `libcuda.so.1.1`. It does not map the complete `/usr/lib/wsl/drivers` directory. These GPU driver resources originate from the Windows/WSL driver infrastructure and are the authorized GPU exception, not general Windows filesystem access. DXG access is shared WSL GPU access, not per-adapter isolation.

Instance metadata `user.mas.gpu` records the requested setting, backend, driver directories, exact owned LXD device definitions and the owned loader configuration path. GPU configuration edits publish devices and this record together. The runtime module manages `/etc/ld.so.conf.d/mas-gpu.conf` with fixed identifiable content and refreshes the container's dynamic linker cache. Disabling removes the owned file and devices; the linker cache is refreshed on the next start. Existing container data and unrelated configuration remain intact. Driver-directory changes on a stopped container reuse the same configuration function before startup. Detection or runtime failure is an error, not an automatic silent switch-off.

Existing running containers are not silently modified. Their menu shows the default setting as pending until the next start from Stopped, or an explicit stopped-container hardware change. No new driver, CUDA toolkit, pip package, or host daemon is installed by this module. The test-only CUDA driver probe uses Python ctypes, JIT-compiles a PTX kernel, executes it as sandbox and verifies the returned value.

## 29. Terminal test synchronization fix — v0.2.2

Status: implemented, verified and published as test v0.2.2. Local and public-entry runs each passed 179 packaged units and all 22 native stages, with no skips or cleanup errors.

- Synchronize all container-shell test interactions through shared terminal helpers. A window title or command output does not establish that the shell is ready for another command.
- After the sandbox/sudo probe, wait for the actual interactive shell prompt before sending exit. Preserve the existing 600-second timeout; do not use fixed sleeps as synchronization.
- Add real PTY regression coverage for delayed terminal restoration/input flushing, title/control-sequence interference, and imported-container hostnames differing from TARGET.
- Run packaged units and the complete native LXD regression suite, update implementation/coverage/release documentation, and publish v0.2.2 test.
- GPU active-driver-directory selection remains a separate pending investigation; this batch changes terminal test synchronization only.

## 30. Active WSL GPU driver discovery — v0.2.3

Status: implemented, verified and published as test v0.2.3: 189 packaged units and all 22 native stages passed. Public resolver, fixed entry and all downloaded release assets verified.

- Replace scanning every driver-store directory with the official NVIDIA WSL discovery supplied by the installed LXD snap: nvidia-ctk cdi generate --mode=wsl --format=json. No new package installation or private DXCore implementation.
- Treat generated JSON solely as discovery data. Never apply the CDI document or execute its hooks. Extract selected NVIDIA CUDA driver directories, validate paths/files, and reuse existing GPU device configuration and ownership records. Preserve unrelated configuration.
- Requery before every actual start with GPU enabled. Refresh changed paths before native startup; do not modify live mappings. Explicit off continues to bypass required driver discovery during startup and cleanup.
- Tool absence, timeout, native failure, invalid/empty results, unsafe paths and missing selected files fail explicitly; never fall back to directory scanning or an old cached selection. Keep native warnings/errors visible.
- Verify exclusion of inactive coexisting driver directories, changed selections, failed discovery preventing startup, and disabled cleanup independence. Run actual sandbox CUDA computation with only selected directories. Simulated selection changes do not imply a real Windows driver upgrade was tested.
- Update verified implementation and coverage documentation, publish v0.2.3 test, and verify the public artifacts.

## 31. GPU and diagnostic integration review — v0.2.4

Status: implemented, verified and published as test v0.2.4. All 196 packaged units and 22 native stages passed; public resolver, fixed entry and all downloaded release artifacts verified.

- Use official nvidia-ctk options to disable hook generation and optional nvsandboxutils discovery for the WSL query. Specify the existing nvidia-ctk path for compatibility hook resolution; do not create/install/execute hooks. Verify selected mounts stay identical. Retain all remaining warnings and unrecognized diagnostics, without quiet mode or cross-start caching.
- Route GPU and LXD native diagnostics through a shared callback-aware emitter and the existing permanent-output renderer. Clear transient progress before warnings. Tester direct probes and PTY query diagnostics must be retained in logs/events as well as displayed. Do not duplicate the same diagnostic from both captured stderr and event replay.
- Reuse the hardware menu's last-read state when a GPU selection is cancelled; refresh after a mutation attempt. Keep actual start resource discovery fresh.
- Tighten official JSON collection/option validation and ownership record version typing; centralize driver-directory validation and loader-file content. Validate resource ownership before unnecessary host discovery. Preserve unrelated configuration and existing off/cleanup behavior.
- Add focused malformed-input, menu-cancel, active-progress/diagnostic rendering, callback failure and tester-log/PTY diagnostic regressions. Run packaged units and complete real-LXD/GPU checks, update implementation docs, publish v0.2.4 test and verify public artifacts.

## 32. Portable Python test subprocesses — v0.2.5

Status: implemented and verified outside the checkout: 197 packaged units and all 22 native stages passed in 452.2 seconds, with no skips or cleanup errors. Published as test v0.2.5. The public installer/test entry also passed all 197 units and 22 stages from /tmp in 450.7 seconds, without skips or cleanup errors.

- Centralize Python test-child startup with an explicit import root derived from the running tester module, supporting both checkout and zipapp. Do not rely on the caller's working directory or PYTHONPATH. Reuse it for module-dependent PTY fixtures.
- Preserve generic Terminal execution and intentionally independent bootstrap/standard-library fixtures. No product GPU behavior change.
- Reproduce the reported failure from an unrelated directory; add regression coverage for unrelated working directories and misleading import paths. Validate packaged units and all native stages outside the checkout.
- Update implementation and coverage documentation after validation; publish v0.2.5 test and verify the public installer/test flow outside the checkout.

## 33. WSL GPU runtime and channel entry adaptation — v0.2.6

Status: implemented and verified locally outside the checkout: 201 units and all 22 native stages passed in 452.2 seconds; no skips or cleanup errors. Published v0.2.6 test; public test/test.sh installation and full regression also passed (201 units, 22 stages, 452.5 seconds). All eleven public assets and four entry routes verified; stable remains 0.1.15.

- Explicitly select /usr/lib/wsl/lib for nvidia-ctk library lookup in WSL. Preserve official per-start active-driver discovery and narrow read-only directory mappings; do not scan for the newest-looking directory or map the whole driver store.
- After successful discovery and resource validation, omit only the recognized multiple-driver-store-path warning in product UI/CLI. Tester invocations retain it. Preserve all other diagnostics and all failure diagnostics; no requirement that this warning appear on any host.
- Manage /etc/profile.d/mas-gpu.sh inside the container, adding /usr/lib/wsl/lib to login-shell PATH. Reuse runtime-file ownership, conflict checks and cleanup; reject foreign files/symlinks. Preserve host and user shell configuration. Support existing GPU records from 0.2.5. Disabled GPU removes the owned profile file.
- Independently observe the host NVIDIA runtime's actual loaded driver path and compare it with container GPU mappings. Validate login-shell nvidia-smi, CUDA compute, disable cleanup and re-enable. Do not infer active drivers from directory timestamps or highest version names. Multi-GPU and additional identity coverage remain out of scope.
- Provide fixed stable/install.sh, test/install.sh, test/test.sh and test/test-stable.sh entry URLs. Reuse bootstrap resolution, checksum, installation and testing logic; preserve legacy install.sh --test. Stable testing selects the exact numeric version matching the current stable product and verifies product identity; no fallback to a different version. Stable product remains unchanged.
- Validate packaged tests outside the checkout, publish 0.2.6 test and verify public entry routing. Update implemented and coverage documents after verification.

## 34. Stable-only release branch — next stable publication

Status: agreed, pending implementation from the next stable publication. This documentation update does not create a branch or publish a version. Existing stable/0.1.15 and test releases remain unchanged. For future stable publications, this section supersedes the stable entry and installation-source rules in sections 26 and 33.

- Keep development and test publication on main. Create and update the release branch only for stable publications; its history represents published stable versions, without intermediate test development commits. Represent versions through history and tags, not per-version directories.
- The release branch contains stable product source, installation and build files, and relevant product/installation/build documentation. Exclude automated test programs, test code, test entry scripts and test validation records. Stable builds and installation must not require excluded test files.
- For a version promoted to stable, retain two GitHub Releases: vA.B.C from main for test, and stable/A.B.C from release for stable. Both products report A.B.C and their product artifacts must be identical. Test includes the product, installer, automated tester and verification assets. Stable includes the product, installer and checksums, without the automated tester or test reports.
- The fixed stable installation command is: curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/release/install.sh | bash . The complete stable installation chain obtains scripts and necessary source files from release or the corresponding stable release assets, never main. Download the product from the selected stable GitHub Release. Preserve shared implementation rather than maintaining separate installation logic for the channels.
- Keep main/test/install.sh for installing the latest test and main/test/test.sh for installing and testing the latest test with its matching tester.
- Keep main/test/test-stable.sh as a test-channel entry. It resolves the current stable version, installs its product through the release-branch stable installation chain, and obtains the automated tester from the exact same numeric test release. For stable/A.B.C use the tester from vA.B.C, never the latest unrelated test version. Do not substitute the main-branch installer for the stable installer. Missing matching releases or failed version/checksum verification must stop explicitly, with no fallback to another version.
- Example: a stable promotion of 0.2.10 produces v0.2.10 and stable/0.2.10. Stable testing installs the stable/0.2.10 product and uses the v0.2.10 tester. Later test publications do not update release or change this pairing until another stable is published.
- Acceptance: verify the release tree excludes test content, the stable tag points to the corresponding release commit, stable installation has no main dependency, channel entry routing is correct, and stable testing uses the exact paired tester against the actual stable product. Update implementation documentation only after these behaviors are implemented and verified.

## 35. Reuse GPU discovery results within existing flows — v0.2.7

Status: implemented and locally verified: 204 packaged units and 22 native stages passed (453.3 seconds), no skips or cleanup failures. Published v0.2.7 test; public installation and all 204 units / 22 native stages passed from /tmp in 447.9 seconds. This is a targeted optimization, not a restriction on detect callers or a change to the discovery contract.

- Preserve the complete detect result, independent creation/startup detection timing and standalone CLI query behavior. No global cache, persistent host inventory or installation-time detection.
- Within a hardware-menu interaction, reuse the acquired host capability for configuration and display refresh. Use successful configuration results for the new displayed state. After failure, read and validate actual container configuration rather than publishing the requested state; reuse the host information for that read.
- In the GPU test flow, use switch command return values and independent LXD configuration reads where only container settings need verification. Retain standalone hardware CLI coverage, repeated-off coverage and native configuration verification.
- Add focused regressions for discovery count, successful on/off display, cancellation and failure refresh. Validate packaged tests outside the checkout and the real LXD/GPU suite, update implementation documents after verification and publish v0.2.7 test. Section 34 remains pending until the next stable publication.

## 36. Persistent LXD socket group access — v0.2.8

Status: implemented and verified locally: 214 packaged units and 22 native stages passed from /tmp in 456.9 seconds; isolated WSL socket repair, recreation, two post-install restarts, custom-group access and unprivileged ready reinstall passed. Published v0.2.8 test. Public artifact verification and unchanged-artifact full recheck passed (214 units, 22 stages, 449.3 seconds). The first public attempt hit an unrelated Windows UNC readback mismatch; both attempts and the unresolved observation are recorded in IMPLEMENTED.md.

- During installation, read the LXD snap's generated daemon group configuration (default lxd), validate that group, and use it consistently for user membership and group refresh.
- Add a managed systemd drop-in for snap.lxd.daemon.unix.socket specifying SocketGroup, without editing generated units or widening mode 0660. Preserve unrelated configuration and reject conflicting or symlinked managed paths.
- Reload systemd after configuration changes; repair the existing verified root-owned LXD socket's group when needed, without restarting the LXD daemon or user containers. Validate effective socket configuration and observed socket metadata. A ready environment needs no privilege request.
- Verify native LXD access under the installation user's credentials before publishing installation success. Keep native sudo authentication and existing group-refresh behavior; normal mas operations do not gain privilege or repair host settings.
- Test persistent socket recreation and a separate WSL restart using an isolated environment, including ordinary-user access. Add custom-group, idempotence, conflict and failure regressions. Preserve the current stable release. Update implementation/coverage documents after verification and publish v0.2.8 test.
## 37. Reliability and interface audit — v0.2.9

Status: implemented, published and verified. All 236 packaged units and 23 report stages (the unit stage plus 22 real integration stages) passed from /tmp locally in 483.2 seconds and through the public installation/test entry in 488.9 seconds, with no skips, unexecuted stages or cleanup errors. All eleven published assets match the validated files; ordinary installation and all four entry routes were checked. Evidence: validation/V0_2_9_LOCAL_REPORT.json, validation/V0_2_9_PUBLIC_REPORT.json and validation/V0_2_9_RELEASE_CHECK.json.

- Use LXD's documented GET ETag / PUT If-Match mechanism for the shared container configuration update capability. Read the configuration and its ETag together; publish only against that exact version. Preserve all writable instance fields, unrelated configuration keys and unrelated devices.
- Integrate GPU configuration publication with this shared capability. Publish GPU devices and their ownership record in one conditional update. Preserve the existing ownership, managed-container, stopped-state and runtime-file checks.
- If LXD rejects a stale ETag, report a localized configuration-change error and ask the user to repeat the operation. Do not retry automatically, overwrite the concurrent change, or fall back to an unconditional update. Missing ETags must fail before publication.
- Use LXD's local API through Python's standard library because non-interactive `lxc config edit` does not send an ETag. No new packages, host privilege requirements or remote-server support. Match the applicable native local socket selection and preserve project scope.
- Wait for the native configuration operation to reach explicit success or failure; poll once per second with the existing timeout (default 600 seconds, minimum 300). An accepted asynchronous request alone is not completion. Retain the GPU module's final configuration observation and elapsed-time feedback.
- Verify successful conditional updates, preservation of unrelated fields, native concurrent changes rejected by LXD, absent/invalid ETags, API/operation failures and timeouts, and GPU failure preventing native startup and external post-processing. Run packaged tests and full real-LXD regression, update verified implementation and coverage documentation, publish v0.2.9 test and verify the public entry.
- The user subsequently authorized all nine audit items in this batch. Also bound test-terminal cleanup using the existing timeout and TERM/KILL escalation; preserve primary failures, collect final events and restore temporary language preferences even when cleanup fails.
- Validate incomplete/duplicate managed PATH blocks before writing shell startup files, retain their unrelated content and permissions, and publish changes atomically. Never report PATH configuration success after a damaged block was silently ignored.
- Preserve captured successful native diagnostics and both output streams on failure using shared presentation helpers. Stream test subprocess diagnostics in occurrence order, record context and display each diagnostic once; retain native text and the known test-only multiple-driver warning when it occurs.
- Record Windows UNC read/write steps, expected and observed content/length, native stdout/stderr and Linux-side file evidence on failure. Keep immediate correctness assertions; do not hide unexplained failures with automatic retries.
- Add localized CLI command descriptions, argument/default/restriction help and useful examples without changing interfaces. Share terminal display-width/clipping functions between menu and progress output; include the shared dependency in the minimal bootstrap.
- Reconcile current requirement, implementation, behavior and coverage baselines while preserving delivery history and unresolved validation boundaries. Project/profile security baseline, non-GPU hardware controls, non-Snap installation-policy changes and the future stable-only release branch remain outside this batch.
