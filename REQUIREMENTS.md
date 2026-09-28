# my-ai-sandbox Requirements

## 1. Scope

Python wrapper around LXD, with a complete CLI (`mas`) and a standard-library TUI. Support Ubuntu on WSL2 and native Ubuntu, including cloud servers. Use the current WSL environment for development and real integration testing. Native Ubuntu verification must be reported separately.

Use LXD's existing functionality instead of reimplementing it. Each basic operation has one shared implementation, including its preconditions, waiting and postconditions. CLI, TUI and composed operations call these functions. Third-party dependencies require explicit user approval. Do not introduce a plugin framework or speculative resource abstractions.

## 2. Commands

| Command | Behavior |
| --- | --- |
| `mas new TARGET [--image IMAGE]` | Create, but do not start, a standard container. TARGET is required; the image override is optional. Default to an Ubuntu image matching the host Ubuntu release. |
| `mas list` | List only managed containers. |
| `mas start TARGET` | Start one managed container. |
| `mas stop TARGET` | Stop one managed container. |
| `mas stop --all` | Stop all managed containers only; no TARGET. Reuse the shared stop function. |
| `mas delete TARGET` | Ask for confirmation, then delete a stopped managed container only. |
| `mas info TARGET` | Show managed container information and state. |
| `mas import TARGET FILE` | Import into an explicitly named, nonexistent TARGET. Never overwrite any existing instance. Verify STOPPED afterwards. |
| `mas export TARGET FILE` | Export a stopped managed container only. If FILE exists, ask whether to overwrite; default no, y/yes allows overwrite. |
| `mas enter TARGET` | Start through the shared start function if stopped, then open a terminal using native LXD execution. |
| `mas config [get language / set language en_us / set language zh_cn]` | Read or update shared user settings without requiring LXD. |
| `mas` | Open the TUI directly when no subcommand is supplied. No `mas tui` command. |

TARGET is a local container name, not a remote, project, snapshot or VM selector. The first release operates on the local LXD server's default project, independent of the user's default remote. This limits accidental scope changes.

`enter` must call the shared function, not another mas CLI process and not a duplicate LXD start implementation. After the shell exits, call a shared exit handler asking whether to stop the container. Default is no; Enter leaves it running. Yes invokes the shared stop function. There is no `mas exit` command.

Image selection is confirmed: `mas new TARGET` requires no image argument and selects `ubuntu:<host Ubuntu VERSION_ID>`. Under WSL, use the Ubuntu release inside WSL, not the Windows version. For example, Ubuntu 26.04 selects `ubuntu:26.04`. An explicit `--image IMAGE` overrides this default. If the matching image is unavailable, report an error rather than silently falling back to another release. CLI and TUI use the same shared image-selection logic.

Import and export take positional FILE arguments. Both CLI and TUI require confirmation before deleting a container. Confirmation defaults to no; only y/yes authorizes deletion or export overwrite. EOF declines confirmation. Prompts are implemented once with CLI and TUI supplying their input mechanisms.

Enter the container as its default user, named `sandbox`, rather than root. Use the user's configured login shell (Bash for newly provisioned users). Provisioning this default user is an explicit exception to the original standard-container-only scope. The sandbox user has passwordless sudo, including sudo -i; do not set an empty root account password. Prepare and verify the user in the shared start function after starting the container; this preserves create as a stopped-container operation. Existing users are retained. Install sudo inside an Ubuntu container if missing, as required by the explicitly requested sudo capability.

Frozen or transitional states must not be silently treated as stopped. Report unsupported states explicitly.

## 3. Ownership and defaults

Identify managed containers with instance-local `user.mas.managed=true` metadata. Creation and import establish this marker. All reads and actions target only managed containers, except the existence check necessary to prevent name collisions. Never adopt, stop, delete, export or enter an unmarked instance. Native lxc use does not remove ownership. No independent ownership database or third-party library.

Use standard LXD default profiles. Do not add GPU, directory sharing, custom network policies or mas profiles. The ownership marker and the explicitly requested default sandbox user setup are the only mas-specific configuration. Use existing networking; fresh initialization prepares ordinary outbound connectivity. Existing misconfiguration is reported, not silently overwritten.

## 4. Completion and waiting

Poll every one second. Continue until an explicit successful postcondition or explicit failure is observed. Use LXD operation completion and structured state, not only process exit codes or fixed sleeps. A failed query does not mean an instance is absent. Default timeout is 600 seconds; configurable operation timeouts must be at least 300 seconds.

Postconditions: new/import = existing stopped managed container; start = running; stop = stopped; delete = confirmed absent; export = native export completed and a complete usable backup exists. Do not perform dependent work before success. Timeouts report operation, target, elapsed time and last observation; never claim the daemon cancelled merely because the client stopped waiting. Tests display and record operation waiting time, including errors.

## 5. TUI

Provide access to all nine container operations, with list selection, input prompts, results and errors. Reuse shared functions directly. Suspend and restore the TUI correctly around interactive terminal sessions. Use Python curses if available; do not introduce third-party UI dependencies without approval.

## 6. Installation

Provide a fixed one-line entry that installs the latest test release. Install missing LXD and its matching lxc client automatically, using the newest available stable snap release rather than development channels. Reuse existing installations without unsolicited upgrades. Prepare missing system prerequisites and initialize a fresh LXD environment with storage and network. Use sudo when needed. Do not overwrite existing LXD configuration.

The fresh-install path must run `snap wait system seed.loaded` with administrator privileges, just like service setup and snap installation. Regression tests must cover missing LXD with snapd both already present and absent; a permission failure must not be mistaken for successful initialization.

WSL service prerequisites, user permissions and restarts must be handled or reported accurately. Implementation baseline: Ubuntu 22.04 or newer with Python 3.10+, systemd and snap support; dir storage for fresh initialization; installation under ~/.local/bin. Zipapps contain no architecture-specific binaries. Do not claim untested host versions or architectures have passed.

Native LXD backup semantics are preserved: imports retain network MAC identity and can conflict with a source container still present on the same network. This version does not silently turn restoration into cloning or rewrite network identities.

## 7. Automated testing

Release a standalone test tool with a fixed one-line download/install/run entry and versioned release assets paired with the product. It prepares missing LXD, runs real integration tests and outputs results and waiting times. No third-party test dependency without approval.

Test container names are `test-<unique-random-code>`. Operate on those explicit targets and clean up only resources created by that run. Never stop other managed user containers while testing `stop --all`: use a temporary isolated LXD test project for the integration test. The product itself still operates on default. Report cleanup failures. Keep installed LXD and permanent environment setup.

Cover new/list/start/stop/delete/info/import/export, default host-matching image selection (including WSL), explicit image overrides, unavailable-image errors without fallback, enter from stopped/running states as sandbox, exit default/no/yes, delete confirmation in CLI and TUI, export overwrite confirmation and default refusal, CLI argument and error handling, bare mas opening the TUI, all TUI actions and terminal return, outbound networking, backup round-trip data integrity, ownership rejection, duplicate import, running-state restrictions and stop-all isolation. Exercise real terminal interaction rather than relying solely on mocks. Cover language selection, persistence, canonical identifiers, localized CLI feedback, immediate TUI language switching and Chinese prompts; isolate test preferences from user configuration. Record unsuccessful, skipped and unexecuted tests accurately. Supplement with focused standard-library unit tests for failure paths that are unsuitable for provoking on a live host.

## 8. GitHub and releases

Publish to the public my-ai-sandbox repository after current WSL checks pass. Versions use a.b.c without a test suffix: a remains 0 unless the user explicitly authorizes 1; b is the project phase (currently 1); c is the complete submission-batch number, incremented once per batch, not per individual Git commit. The current development batch is 0.1.4. Product, installer and tester share that version, with Git tag v0.1.4. GitHub prerelease status is independent of the numeric version. Fixed installation selects the highest published numeric version, including prereleases. Preserve earlier release assets. Include checksums, installation instructions, tested environment and results.

## 8.1. Language and user configuration

Support exactly en_us and zh_cn throughout language filenames, persisted values and CLI arguments. Store all mas-owned interface messages in dedicated translation catalogs, shared by installation, CLI, TUI, core operation messages and the test tool. Preserve native LXD, sudo, package-manager output and machine-readable identifiers verbatim, with localized mas context where needed.

Ask for language before installation starts. The first-install default is zh_cn; reuse the saved language as the default on subsequent installations. Noninteractive installation may explicitly select a language. Store user preferences in $XDG_CONFIG_HOME/my-ai-sandbox/config.json (default ~/.config/my-ai-sandbox/config.json). TUI has a settings entry, initially containing language; changes take effect immediately and persist. CLI: mas config, mas config get language, mas config set language zh_cn, mas config set language en_us. CLI and TUI reuse the same configuration functions. CLI configuration reading and changes must not require LXD.

## 8.2. System sudo behavior

At installation/testing startup, determine whether the current flow needs host sudo. If it does, invoke system sudo -v once before privileged work. Subsequent commands use normal system sudo behavior. No password handling, custom authentication cache, keepalive, expiry policy, timeout extension or host sudoers edits. System-driven reauthentication remains the system's responsibility. A test run with an already usable LXD needs no host sudo.

## 9. Documentation and stages

Keep REQUIREMENTS.md and IMPLEMENTED.md inside this project. Before updating IMPLEMENTED.md at each code stage, check the actual implementation against requirements and correct discrepancies. Distinguish implemented, verified, blocked and pending work. Complete a final requirements audit before release.

## 10. Exclusions

No GPU passthrough, host directory sharing management, resource whitelist, model installation, model service management, custom port forwarding, non-Ubuntu support, plugins or general diagnostic framework in this version.


## 11. Batch 0.1.4 acceptance criteria

1. Automatically configure the actual installation directory in the user's shell startup configuration. Preserve existing PATH entries and unrelated configuration. Repeated installation must not duplicate the managed block. Cover Ubuntu Bash login and interactive startup, and Zsh when selected. New-terminal instructions are acceptable; manual export commands are not a required installation step. Use one shared PATH setup function and test with isolated home directories, including paths with spaces.
2. From 0.1.4 onward, separate product, installation and automated-test artifacts. Historical numeric release pins retain their original implementation and packaging. Without --test, download only the product and files required for installation; do not download or install a tester. The product archive must not contain tests, the test runner or test-only presentation code. With --test, additionally download the version-matched standalone tester; that tester invokes the shared installer and then runs the complete test suite. The installer must not contain or invoke test orchestration. Reuse one installation implementation, including when group membership must be refreshed. Preserve explicitly pinned releases and the fixed latest-version entry.
3. Default to zh_cn when no preference exists, including bootstrap without Python. Previously saved language takes precedence over the default. Localize all mas-owned installation, operation, TUI, test progress, stage names, diagnostic context and summary messages. Leave commands, options, identifiers and original external-program output unchanged. English-interface regression tests may retain their raw output in detailed logs; user-facing status and results remain in the selected language.
4. In an interactive test terminal, refresh normal progress on one transient line, including elapsed waiting time; erase it before permanent output and when a stage finishes. Retain one success summary per completed stage. Retain warnings, errors, unexpected output and failure details; clearly label deliberately provoked errors as expected errors. Do not suppress nonnormal output merely because the process exited successfully. Keep complete original subprocess and terminal logs and structured waiting records. Noninteractive output must contain no cursor-control sequences and must omit normal progress ticks while retaining stage summaries and nonnormal output.
5. Always provide a final test summary with passed, failed and unexecuted stage counts, total elapsed time, cleanup outcome and report path when the suite starts. Cleanup failures must be printed and cause nonzero exit. Test interruption and failures must clear transient progress. Verify artifact separation, orchestration order, shell PATH persistence/idempotency, language defaults and both terminal/nonterminal output behavior. Run the existing container integration coverage on the final artifacts before publication.

User-provided 0.1.3 logs show successful automatic installation on an Ubuntu WSL environment initially without LXD, followed by all 28 unit tests and 14 integration groups passing. This supplements the earlier existing-host validation; it does not establish native Ubuntu coverage.
