# Implementation status

Current result: phase 2 GPU batch 0.2.1 is implemented, verified and published as test v0.2.1. Both public installation modes are verified. Phase 1 stable/0.1.15 remains unchanged. Stage 20 records the GPU implementation; earlier stages remain historical checkpoints.

## Stage 1 — shared operations and interfaces (2026-09-27)

Implemented in `mas/core.py`: ownership-scoped lifecycle functions, host Ubuntu image selection, one-second completion polling with a 600-second default, shared confirmations, export overwrite handling, sandbox user preparation and terminal entry/exit composition. `mas/cli.py` and `mas/tui.py` call these functions; bare `mas` opens curses. No third-party Python dependency.

Verified against REQUIREMENTS.md before this update:

- 15 standard-library unit tests passed, including ownership rejection, confirmations, running-state restrictions, duplicate-target rejection, host image selection, CLI argument validation and composition reuse.
- Current host: WSL2, Ubuntu 26.04.1, Python 3.14.4, LXD client/server 6.9.
- Fresh LXD initialized using native `lxd init --auto --storage-backend=dir`; default profile has a root disk and lxdbr0 NIC.
- Real randomized test container created from default `ubuntu:26.04`, remained stopped, then started successfully.
- Real container login as sandbox, passwordless sudo to root, matching Ubuntu version and DNS resolution verified.
- Operation logs included actual wait durations (creation approximately 15 seconds in the initial run).

Pending verification: full CLI and TUI integration, backup round trip, HTTP outbound connectivity, isolated stop-all tests, fresh-machine installer, release artifacts and public GitHub publication. Native Ubuntu has not been tested. This is not a release-complete status.

## Stage 2 — complete source integration and installer

After correcting test assumptions about LXD's image.version metadata and backup MAC preservation, all 13 source integration cases passed in `test-results/full-4/report.json`, with no cleanup errors. This includes 19 unit tests, default and unavailable images, CLI lifecycle and state guards, sandbox login and sudo, outbound HTTPS, real PTY enter/exit, backup round-trip data preservation, overwrite/delete confirmations, ownership-scoped stop-all, and all TUI actions. A curses prompt redraw issue exposed by repeated prompts was corrected and retested.

The standard-library zipapp build produces separate product and test artifacts. Local installation into ~/.local/bin was verified against the existing LXD environment without modifying its profiles. The installer selects the highest available stable LXD snap version when missing and initializes only an empty environment. Existing configuration preservation is unit tested. The current LXD snap was initially installed manually by the user, so fresh-system package installation by the installer has not yet been exercised end to end. WSL without systemd requires the reported enable/restart step.

Next: validate the built product with the independent test artifact, then publish and verify the public fixed download entry. Native Ubuntu remains a support target, not a claimed test result.

## Stage 3 — release artifact validation

`python3 dist/mas-test.pyz --product dist/mas.pyz --output test-results/release-artifacts` exited 0. All 13 integration groups, including 19 unit tests, passed with no cleanup errors. The test tool ran CLI and TUI code from the specified product zipapp, not merely the source checkout. Product SHA-256 is recorded in `validation/WSL_REPORT.json` and matches the release asset. Both zipapps and the packaged installer were exercised in the current environment.

Final requirements audit:

| Requirement | Evidence |
| --- | --- |
| Shared Python lifecycle functions and ownership marker | core.py, ownership unit tests and live unmarked-container rejection |
| Host-matching image and explicit override | new-default, missing-image and export-import integration groups |
| Create stopped; start/stop/info/list | live CLI and TUI integration |
| Enter as sandbox; passwordless sudo; shared exit handling | real PTY tests from running and stopped states |
| Delete confirmation in both interfaces | delete-confirmation and tui integration groups |
| Export stopped only; overwrite defaults no | running-guards and overwrite-confirmation, plus TUI prompts |
| Import rejects duplicate targets; data preserved | export-import and ownership-and-stop-all groups |
| Stop-all scoped to managed instances | live unmarked container remains running, outside-project smoke container remains running |
| Polling, timeout floor and logged waiting | focused waiting unit tests, operation logs and JSON report |
| Bare mas opens full TUI | PTY test of all nine actions and terminal restoration |
| Standard profile, outbound network | lxdbr0/dir setup and live HTTPS request |
| Separate portable test tool | packaged mas-test.pyz tests the version-matched product and records its hash |
| Installer preserves existing setup | packaged local installation and configuration-preservation unit test |

Known verification limits remain: fresh-system installation was not run end to end by this installer, native Ubuntu and non-x86_64 hosts were not separately tested, and WSL without systemd requires a host restart after enabling it. No claim is made that these paths passed live testing.

## Stage 4 — public release and entry verification

- Public repository: https://github.com/gdrencn/my-ai-sandbox
- Prerelease: https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.0-test.1
- Published assets: mas.pyz, mas-test.pyz, bootstrap.py, install.sh, SHA256SUMS, WSL_REPORT.json.
- Executed the documented public curl/bash entry with --test against GitHub. It resolved v0.1.0-test.1, verified and installed the actual downloadable assets, and completed all 13 integration groups (including 19 unit tests) with exit code 0.
- Installed product and tester hashes match the release files. Evidence: validation/PUBLIC_ENTRY_REPORT.json.
- All temporary test containers and test projects were removed. Only the standard default project, initialized storage/network and LXD shared image cache remain. Report logs are retained; temporary backups were removed.
- Product and test tool are installed locally at ~/.local/bin/mas and ~/.local/bin/mas-test.

This completes the first test release in the current WSL environment, subject to the explicitly recorded environment-verification limits above.

## Stage 5 — fresh-install seed wait permission fix

User report: on a machine without LXD, installation stopped at `snap wait system seed.loaded` with `error: access denied (try with sudo)`. The same unprivileged command reproduced the failure on the development host.

The installer now runs that step through the shared privileged-command runner. Added a regression test exercising the fresh-install path with snapd present and absent, simulating the subprocess permission boundary. Before the fix both scenarios failed with the reported permission error; after the fix all 20 unit tests passed. No third-party dependency or host sudoers configuration was added.

The v0.1.0-test.2 product and matching tester passed all 13 real integration groups (including 20 unit tests), with exit code 0 and no cleanup errors. The tested product hash matches the release artifact; evidence is in validation/TEST_2_REPORT.json. Published at https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.0-test.2. The fixed public installation entry resolved test.2, installed successfully on the existing development environment, and installed product/tester hashes match the release files. A full live fresh-host installation remains unverified here.


## Stage 6 — version 0.1.3, language settings and system sudo

Implemented and checked against REQUIREMENTS.md:

- Product and tester use 0.1.3. The fixed installer selects the highest published numeric version, including prereleases, and accepts exact pins with or without v. Numeric ordering is regression tested with 0.1.9 and 0.1.10. Existing suffixed releases are preserved.
- All mas-owned interface messages are in mas/locales/en_us.json and zh_cn.json. CLI, TUI, installer, shared operations and test-tool presentation reuse mas/i18n.py. Native command output, test-framework output and machine identifiers retain their original form.
- mas/config.py provides atomic persisted preferences in the XDG configuration location. CLI config works without LXD; unknown preferences are retained. Supported language identifiers are consistently en_us and zh_cn.
- Installation prompts before product installation, with the saved default and an explicit --language option. The minimal installer downloads the shared configuration/catalog modules; its missing-Python prompt is generated from the same catalog. Real PTY tests verify language selection. An initial /dev/tty read/write-mode issue was fixed and regression tested.
- TUI c opens settings; 1 selects English and 2 selects Chinese immediately. Unicode cell widths are handled for drawing and prompts. Real terminal tests cover switching, Chinese creation, default refusal to delete, return to English and the complete TUI lifecycle.
- Installer checks whether host privilege is required and uses system sudo -v before privileged setup. Later commands use normal sudo; no password storage, keepalive, custom cache or host sudo policy changes exist. Ready environments require no host sudo. Fresh snapd/LXD paths verify privileged snap seed waiting and upfront authentication in simulated subprocess tests.
- The standalone tester uses temporary preferences, preserving user settings. Its full workflow covers both languages and retains wait durations and cleanup results.

Validation: 28 standard-library unit tests passed. All 14 integration groups passed using the final product and tester zipapps, with the test tool configured to zh_cn. Product hash verification and zero cleanup errors are recorded in validation/V0_1_3_REPORT.json. The earlier candidate also passed all 14 groups; the final build additionally includes the real installer-terminal regression test. Local bootstrap installation, Chinese CLI output and installed product/tester hash equality passed on the existing host. Shell syntax, Python syntax and git diff whitespace checks passed.

Verification limits: live fresh-system installation, native Ubuntu and non-x86_64 environments remain unverified. No third-party dependency was added. Historical stages and their verification limitations remain below their original version descriptions.


### 0.1.3 publication and public entry verification

Published https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.3 with product, matching tester, bootstrap, shell installer, SHA256SUMS and WSL_REPORT.json. Executed the original public curl/bash --test entry in a real terminal, selected zh_cn at its initial prompt, and confirmed it resolved v0.1.3. All 14 integration groups, including 28 unit tests, passed with no cleanup errors. The installed product and tester exactly match the released artifact hashes; the temporary test project was removed. Evidence: validation/V0_1_3_PUBLIC_REPORT.json. Test language selection used isolated preferences and did not overwrite the user's configuration. This was an existing-LXD host and needed no host sudo.

The 0.1.3 batch is complete within the recorded verification limits. Documentation-only commits in this batch do not increment the submission-batch version.


## Stage 7 — version 0.1.4, separated distribution and concise testing

Verified against the batch 0.1.4 requirements before this update:

- configure_path in mas/install.py writes a guarded, idempotent PATH block using the actual installation directory. Bash login and interactive startup files are covered; Zsh uses ZDOTDIR when configured; POSIX sh uses .profile. Existing file content and PATH entries are preserved. Tests exercise repeated configuration and a home directory containing spaces. A new real Bash login shell, launched with only /usr/bin:/bin initially in PATH, found ~/.local/bin/mas and reported 0.1.4 without manual export.
- Distribution now has mas.pyz, mas-install.pyz and mas-test.pyz. The normal entry downloads only product and installer plus bootstrap/verification resources. --test additionally downloads the tester, which invokes the installer, installs its own executable and starts verification. The installer installs only the product and does not invoke tests. Product and installer archives exclude test modules and test-only catalogs; product also excludes the installation module. Archive boundaries and both bootstrap download branches are tested. Historical numeric releases retain their original packaging through a compatibility call to their own installer.
- Group-refresh continuation imports installation code from the installer archive, not the product. The tester separately refreshes its process groups when necessary. A real child-process continuation using the packaged installer succeeded with the sudo boundary simulated; live privileged setup was not repeated on this already prepared host.
- First-use language defaults to zh_cn; saved en_us is retained. Shared interface catalogs remain canonical. Test-only translations are separate under mas/locales/test. User-facing test stage names, progress, diagnostic context and summaries use the selected language. English UI fixtures retain original output in detailed logs.
- Test output refreshes normal progress on one transient terminal line. Stage success summaries, expected-error labels, warnings and failures are permanent. Error progress records are retained. Unknown stderr is retained even on successful exit; native warning/error lines in stdout are retained. Full native stdout/stderr and structured per-second wait events are recorded. Network probe retries retain a localized warning and their native error in the report.
- Noninteractive output omits normal ticks and cursor-control sequences. Final output includes passed/failed/not-run stage counts, total test duration, cleanup status and report path. Cleanup errors remain visible and cause failure.

Final packaged validation: all 40 unit tests and all 14 integration groups passed, no skipped unit tests and no cleanup errors. The test tool installed through the separate final installer before testing the installed product. Evidence: validation/V0_1_4_REPORT.json; its product hash matches the release product. Final noninteractive logs contain no escape sequences. A preceding real-PTY run verified transient redraw/clear behavior, localized visible progress, stage summaries and a single final summary. Subsequent focused tests verify error-progress retention and network retry diagnostics. Source-only unit discovery marks the archive-boundary check as skipped; the packaged run executes it and passes.

The user-provided 0.1.3 transcript additionally verifies missing-LXD installation, initial sudo authentication, group refresh and all earlier tests on that user's Ubuntu WSL environment. For 0.1.4, native Ubuntu, other CPU architectures and a full live fresh-host reinstall remain unverified; this release preserves the existing system-sudo policy and fresh-install path.


### 0.1.4 publication and public entry verification

Published https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.4 with mas.pyz, mas-install.pyz, mas-test.pyz, bootstrap.py, install.sh, SHA256SUMS and WSL_REPORT.json.

Executed the public entry without --test in a real terminal with fresh isolated preferences: the prompt defaulted to zh_cn, Enter selected Chinese, and product installation succeeded. The pre-existing tester file's modification time was unchanged. Bootstrap branch tests separately verify that the normal path never requests the tester asset.

Then saved en_us and ran the public --test entry: the prompt correctly reused en_us, selection of Chinese took effect, and the downloaded tester invoked the separate installer before testing. All 40 unit tests and all 14 integration groups passed with no cleanup errors. Real terminal output contained transient clear/redraw sequences, no leaked English waiting ticks and exactly one localized final summary. Product and tester bytes match the release artifacts. The test project was removed and original user preferences were preserved by the validation harness. Evidence: validation/V0_1_4_PUBLIC_REPORT.json.

The 0.1.4 batch is complete within the stated platform and fresh-host verification limits. The final documentation commit belongs to this same batch and does not increment the version.


## Stage 8 — version 0.1.5, shared menus and paged TUI

Verified against REQUIREMENTS.md section 12 before this update:

- mas/menu.py is the shared standard-library implementation for vertical left-aligned menus, focused row highlighting, radio choices, checkbox choices, text input, cancellation and terminal key decoding. Normal CSI and application SS3 arrow sequences both work. Multi-selection separates focus from checked values; no speculative bulk operation or setting was added.
- The TUI main menu separates Container management, Settings and Exit. Management contains List, New, Import, Stop all and Back; each container opens Info, Start, Enter, Stop, Export, Delete and Back. All actions call the existing Manager. Information scrolls; empty lists and resized viewports remain navigable. Cancelling a language choice returns to Settings without changing the preference.
- Installation and settings use the same radio language selector. Chinese is selected on first installation; saved preferences determine later defaults. CLI deletion, export overwrite and the shared shell-exit handler use the same default-No confirmation menus as TUI actions. Explicit mutually exclusive --yes / --no arguments support unattended commands; enter applies the choice after the shell exits. Piped y/n no longer grants consent.
- Text inputs support entry, Backspace and cancellation. Shell entry suspends curses and restores the outer TUI afterward. An initial integration run exposed canonical input/echo being restored by the nested exit-confirmation menu; the fix explicitly restores immediate input, keypad and cursor modes. A dedicated real-PTY regression test verifies mode flags and subsequent arrow navigation.
- Bootstrap downloads the shared menu module for its controlling-terminal prompt, including curl-pipe installation. Before Python exists, a minimal Bash built-in selector follows the same radio rules and uses generated shared-catalog labels. Its default, CSI and SS3 selection paths were verified separately in real PTYs without removing host Python or invoking package installation.
- New interface text is present in both language catalogs. README describes menu navigation and noninteractive consent. Existing ownership, operation waiting, language persistence, distribution separation, system sudo behavior and transient test output policies remain covered.

Final packaged validation: 49 unit tests passed with no skips; all 14 real LXD integration groups passed after installation through the separate installer. CLI confirmations and every TUI container operation were driven using actual arrow sequences, Enter and Escape; reusable multiple-choice tests use Space. The TUI tests include language changes/cancellation, empty lists, cancelled creation, information scrolling, start, sandbox terminal entry and return, stop, export and overwrite refusal, deletion refusal/confirmation, import and stop-all. Actual states, backups, configuration and shell identity are checked. The focused PTY suite additionally checks resize and viewport selection. No cleanup errors occurred; the final noninteractive log contains no terminal-control escapes. Evidence: validation/V0_1_5_REPORT.json, whose product hash matches the final release artifact. Shell syntax, Python compilation and git diff whitespace checks passed.

Verification environment remains the current Ubuntu WSL host with existing LXD. Native Ubuntu, other CPU architectures and a fresh full privileged installation were not rerun in this batch. No third-party dependency was added. Public-entry verification follows publication and is recorded separately below.


### 0.1.5 publication and public entry verification

Published https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.5 with product, separate installer, separate tester, bootstrap, shell entry, SHA256SUMS and WSL_REPORT.json.

Ran the public curl/bash entry in a real PTY using fresh isolated preferences. Its radio language menu selected Chinese by default, Enter confirmed, and installation resolved v0.1.5. Normal installation left the existing tester modification time unchanged. Then ran the same public entry with --test; the downloaded tester invoked the installer before testing the installed product. All 49 packaged unit tests and all 14 integration groups passed, including the complete arrow-driven TUI workflow. Both installed executables match the released product/tester hashes. Cleanup had no errors, and both final validation projects were confirmed absent. Temporary preferences were removed without changing the user's saved language.

Evidence: validation/V0_1_5_PUBLIC_REPORT.json. The 0.1.5 batch is complete within the WSL/platform and fresh-host limits documented above. This publication-evidence update remains part of the same submission batch.


## Stage 9 — version 0.1.6, ordinary terminal text menus

Verified against REQUIREMENTS.md section 13 before this update:

- Removed the curses/fullscreen implementation. mas/menu.py now uses only standard-library termios, select and bounded ANSI row updates. It never enters an alternate screen, clears the screen/scrollback or positions output at the top of the screen. Menus append at the current terminal location; only their active rows are refreshed. A fresh block is appended on resize because previous rows may have reflowed. Long lists retain a valid selection and viewport.
- mas/terminal_ui.py replaces mas/tui.py. Container management, Settings, all nine operations, language persistence and default-No confirmations retain their shared backend. Operations use the ordinary Manager reporter, preserving progress and native diagnostics. Information prints complete JSON into history followed by Back; users use terminal scrollback. Results and errors remain visible before the next menu.
- Input mode changes are scoped to each prompt and restored in finally blocks. Commands and container shells receive normal terminal input; shell exit invokes the existing shared confirmation handler. There is no nested fullscreen session or curses mode recovery. Text input supports Unicode, Backspace, left/right cursor movement, Home/End, Delete, Enter and Escape. Both CSI and SS3 navigation remain supported.
- Installation language, CLI confirmation and application menus reuse the same inline component. The existing missing-Python Bash selector was already inline and remains unchanged. Explicit CLI operations and --yes/--no retain their behavior. User-facing catalog text and README now describe terminal text menus. Historical test/report case identifiers remain stable for comparisons.

Final artifact verification: all 51 packaged unit tests passed with no skips, followed by all 14 real-LXD integration groups after installation through the separate installer. Tests drive the complete text-menu lifecycle and CLI confirmations with real keys, assert resulting states/data, check that information and progress are printed, and reject alternate-screen, screen-clear and scrollback-clear sequences. Focused tests cover UTF-8 editing, resize, cancellation, Ctrl-C and exact terminal-mode restoration before/after operations. A row-update interpreter verifies that prior text, completed menus and shell output remain visible after redraws; a separate real-PTY check verifies failure diagnostics remain visible before the next menu. No cleanup errors occurred. The noninteractive test log contains no terminal-control escapes. Python compilation, shell syntax and git diff whitespace checks passed.

Evidence: validation/V0_1_6_REPORT.json; its product hash matches the release artifact. Verification used the current Ubuntu WSL environment with existing LXD. Native Ubuntu, other CPU architectures and fresh privileged host installation were not rerun. No third-party dependency was introduced. Public-entry validation will be recorded after publication.


### 0.1.6 publication and public entry verification

Published https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.6 with the product, separate installer and tester, bootstrap, shell entry, SHA256SUMS and WSL_REPORT.json.

Executed the public curl/bash entry in a real terminal with isolated fresh preferences. The inline language menu defaulted to Chinese, Enter confirmed, and installation resolved v0.1.6. Normal installation did not change the existing tester modification time. The public --test entry then downloaded the matching tester, invoked installation and passed all 51 packaged unit tests and all 14 integration groups, including the complete inline menu workflow. Both public entry transcripts were checked for the absence of alternate-screen and screen/scrollback-clear sequences. Installed product/tester hashes match the release artifacts. Cleanup reported no errors, and both validation projects were confirmed removed. Test preferences were isolated and removed without overwriting the user's saved language.

Evidence: validation/V0_1_6_PUBLIC_REPORT.json. The 0.1.6 batch is complete within the documented WSL, architecture and fresh-host verification limits. This documentation-only publication record remains part of the same batch.


## Stage 10 — version 0.1.7, requirement/code audit and expanded verification

Compared current requirements, historical implementation records and the actual shared backend before making this update. TEST_COVERAGE.md maps requirements to real product/PTY and fault-injection tests, with platform and fresh-host limits. CORE_BEHAVIOR.md inventories every shared precondition, completion check, operation hook, start-time user setup, and composed enter/exit behavior. Historical stages remain historical; these current inventories describe the inline menu and present implementation.

- Added tests/test_failures.py with 18 focused tests covering command completion versus state, native errors, Error state, query failures, ownership marking, interruption/client cleanup, idempotent/unsupported lifecycle states, stop-all partial failures, enter failure ordering, import marking and VM rejection, export corruption/metadata/publication failure, concurrent destination creation, state rechecks and path guards.
- The new malformed-query regression initially reproduced three failures and three unhandled exceptions: a JSON object could be interpreted as an empty instance list, while malformed rows could leak KeyError/TypeError. LXD.instances now requires a list of rows with string name/status/type and dictionary config. Invalid data raises the existing localized error and cannot establish absence. This is the only changed container-operation behavior in this batch.
- Added tests/test_runner.py with eight tests covering run failure/interruption, not_run tracking, cleanup/report failure exit status, success counts, module discovery, detailed unit results, optimization rejection and checksum failure preventing installation. The runner now catches unexpected cleanup exceptions, records them and still attempts the report. Python -O/PYTHONOPTIMIZE is rejected before testing because it disables behavioral assertions.
- Unit modules are discovered from all packaged tests/test_*.py files. JSON reports now include unit_tests with module names, unique test identifiers, tests_run, failure/error counts, skipped reasons, expected failures, unexpected successes and successful status. Integration group outcomes remain separate.
- Added real-product groups invalid-inputs, lifecycle-repeat and unmarked-import. They exercise missing/invalid targets and corrupt backups; repeated start/stop with sandbox UID, home file and custom shell retention; and native export of a fixture after removing its management marker, followed by stopped marked restoration through mas import. Only isolated registered test fixtures are touched.

Final packaged validation: 77 tests across six discovered modules passed, zero failures/errors/skips; all 17 real LXD groups passed after installation through the separate installer. The report contains all 77 test identifiers. Cleanup had no errors. The final noninteractive log contains no terminal-control escapes. Python compilation, shell syntax and git diff checks passed. Evidence: validation/V0_1_7_REPORT.json; the recorded product hash matches the release asset.

Verification remains current Ubuntu WSL with existing LXD. Fault-injection branches are explicitly distinguished from live failures in TEST_COVERAGE.md. Native Ubuntu, other CPU architectures and a fresh privileged host reinstall were not performed. No third-party dependency was added. Public-entry verification follows publication.


### 0.1.7 publication and public entry verification

Published https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.7 with product, separate installer/tester, bootstrap, shell entry, SHA256SUMS and WSL_REPORT.json. Public normal installation in a real terminal selected Chinese by default, resolved 0.1.7 and left the existing tester modification time unchanged. Public --test installation then passed all 77 discovered unit tests and all 17 real-product integration groups. The report records zero failures/errors/skips and all test identifiers; cleanup had no errors. Both installed executable hashes match the release assets. Public transcripts contain no alternate-screen or screen/scrollback-clear sequences. Both validation projects were confirmed removed, and temporary preferences were removed without changing user configuration.

Evidence: validation/V0_1_7_PUBLIC_REPORT.json. The audit and test-improvement batch is complete within the coverage limits in TEST_COVERAGE.md. This documentation-only record remains part of batch 0.1.7.


## Stage 11 — version 0.1.8, shared transient operation progress

Verified REQUIREMENTS.md section 15 against the final code and packaged artifacts before this update:

- Extracted the tester's bounded terminal-line renderer into mas/output.py. CLI and inline menus use the same Progress reporter; the tester subclasses the same Output primitive and keeps its test-specific diagnostic filtering in mas/test_output.py, excluded from the product. No third-party dependency was added.
- Interactive waiting events refresh one line, with width measured from the actual output terminal and Chinese display width respected. Final success/error events clear the transient line and remain in history. Plain redirected output omits waiting ticks and retains final results and diagnostics without cursor-control bytes. Structured test events still record every observation and elapsed time.
- Successful LXD query stderr can pass through the same permanent-output callback, including messages without a trailing newline, so a following refresh cannot erase it. Native command failures retain their existing error reporting. CLI errors and interruption clear pending progress before displaying their messages. Lifecycle/state/ownership checks and polling frequency are unchanged.
- Added five tests for plain output, Chinese narrow-line rendering, actual output-terminal sizing, query warnings and PTY history across sequential CLI operations, menu navigation and interruption. Existing tests continue to cover command/state completion and failure paths.

Final packaged validation: 82 unit tests across seven modules passed with no failures, errors or skips; all 17 real-LXD integration groups passed, including the full text-menu workflow. Cleanup succeeded and the isolated project was confirmed removed. The report's product SHA-256 matches dist/mas.pyz. The noninteractive suite log contains no terminal-control escapes. Source discovery passed 82 tests with the existing archive-only test skipped; the packaged run executes that check. Compilation, shell syntax, archive separation and git diff whitespace checks passed. Evidence: validation/V0_1_8_REPORT.json.

Terminal behavior boundary: commands retain normal terminal input modes. If a user types ahead during a wait, the terminal itself can echo keys/newlines and leave a waiting line in history. The real menu suite deliberately queues some navigation keys before operations complete; those echoed-input rows are distinct from periodic progress output. Focused PTY verification with input at prompts confirms that normal waiting rows disappear while results, warnings, errors and menus remain.

Validation used the current Ubuntu WSL with existing LXD. No fresh-host installation, native Ubuntu run, public-entry validation or stable publication was performed in this batch. Resource/security settings and release-channel behavior were not changed.


### 0.1.8 test publication and public-entry verification

Published https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.8 as a test prerelease with the validated product, separate installer and tester, bootstrap, shell entry, SHA256SUMS and WSL_REPORT.json. Source commit: b4a802e9b70491463901c9cbc84d53297e2e68ae. Requirements now explicitly make test publication and fixed-entry verification mandatory after each completed, validated development batch, without renewed approval. Stable promotion remains separate.

Ran the public curl/bash entry in actual PTYs with isolated fresh user preferences: both normal installation and --test resolved v0.1.8, with Chinese selected from the initial language menu. Normal installation preserved the existing tester modification time. The public --test flow installed the matching artifacts and passed all 82 packaged unit tests and all 17 real LXD integration groups, with no skipped unit tests or cleanup errors. Installed product/tester SHA-256 values match the release assets; the isolated project was confirmed removed. Public transcripts contain no alternate-screen, screen-clear or scrollback-clear sequences. Temporary preferences were removed without overwriting the user's saved configuration.

Evidence: validation/V0_1_8_PUBLIC_REPORT.json. Validation remains current Ubuntu WSL with existing LXD; native Ubuntu and fresh privileged installation were not rerun. Filesystem-mount commands in section 16 of REQUIREMENTS.md remain unimplemented and are not part of this release. This publication record completes the same 0.1.8 batch; it does not increment the version.


## Stage 12 — version 0.1.9, independent filesystem mounts

Verified section 16 against the final implementation and packaged product before this update. Added shared mountfs/unmountfs/mountedfs methods, CLI commands and inline container-menu actions. Absolute directory paths map below ~/LXDCMFS/TARGET; omitted paths resolve sandbox home. Exact unmount selection, non-overlap, pre-existing destination rejection, tracked directory identity, empty-only cleanup and residual query status share mas/filesystems.py. Per-user records use private XDG state storage, atomic writes and a process lock; helper PIDs include process start time and boot identity.

Native LXD runs an authenticated loopback SFTP listener; SSHFS runs as the invoking user. No custom SFTP implementation, permission remapping, default_permissions override or container package installation was added. The installer now prepares missing host SSHFS using ordinary system sudo. Host connection files are private and are cleaned on unmount. Helpers survive command exit. Native stderr is retained.

Live LXD 6.9 verification established that a persistent file session delays native stop until released. start-from-Stopped, stop-from-Running and delete therefore refuse recorded mounts/residuals with an explicit-unmount instruction; they never automatically unmount. Already-running and already-stopped behavior is retained. Native lxc operations and other users' mounts are outside per-user coordination. Relative, traversing and symlink container paths are rejected. Default unmount remembers an earlier default-home mount if the account home changes.

Added 15 unit tests for path/mount/process identity, conflicts, cleanup, records, exact/default selection, lifecycle preconditions and missing-SSHFS sudo setup. Added three real groups: filesystems, filesystem-recovery and filesystem-menu. Tests verify running/stopped read/write, root mount, independent paths, mode/owner preservation, native new-file metadata, lifecycle refusal, failed requests, killed-helper cleanup, safe retry and actual menu selection. Fixed fixture cleanup to retain handling of the test suite's deliberately unmarked native container.

Final packaged result: 97 unit tests, zero failures/errors/skips; 20 real LXD groups passed. Mount roots and test project were removed; no cleanup errors. Product SHA-256 matches validation/V0_1_9_REPORT.json. Source discovery skips only the packaged-boundary check. Compilation, shell syntax and diff checks passed.

Environment: current Ubuntu WSL/LXD 6.9. System sudo was unavailable, so live development validation used the Ubuntu repository SSHFS 3.7.3 executable unpacked into a temporary host directory, using existing FUSE/OpenSSH libraries; no container package was added. Native Ubuntu, fresh privileged host installation and actual ACL-bearing fixtures were not rerun. No full isolation/security-hardening claim is made. Public installation verification is recorded separately after publication.


### 0.1.9 publication and public-entry verification

Published v0.1.9 from commit 4c862ab4c7dca5f3a230ad70f40916d5496cd4ce. Both public curl/bash flows resolved the release; normal installation preserved the tester, and the public test flow passed 97 packaged unit tests and 20 real groups with zero skips or cleanup errors. Installed product/tester hashes matched the validated assets. PTY transcripts contained no full-screen/scrollback clearing. Evidence: validation/V0_1_9_PUBLIC_REPORT.json. Environment limitations are unchanged from Stage 12.


## Stage 13 — version 0.1.10, reliability and coverage audit

Rechecked all six project documents, container lifecycle code, filesystem implementation, installer/bootstrap, menu/presentation and tester against the released 0.1.9 baseline. Updated REQUIREMENTS before implementation; current README, CORE_BEHAVIOR, TEST_COVERAGE and RELEASE_NOTES now reflect the audited behavior. Historical stage records remain historical; 0.1.9 public validation is recorded above.

Mount creation and native start-from-Stopped, stop-from-Running and deletion now hold the same per-user record lock and recheck ownership/state inside it. Query/unmount recovery validates existing local records without accessing a missing or unmarked replacement container; new mounts still require current ownership. Registry schema checks cover directory paths/identities, mount fields, helper process tokens and created-directory ancestry. Invalid records are preserved. New directory identities use filesystem ID/inode/owner, with conservative legacy device/inode handling; atomic registry publication fsyncs both file and directory.

Helper cleanup validates UID, process start/boot identity and mount-specific native argv; exact argv discovery recovers helpers interrupted before PID publication. Unmount emits final success only after native detach, helper termination and tracked empty-directory/private-file cleanup, with elapsed reporting while waiting for helper exit. Native unmount timeouts retain recovery records and return a localized error. Known-hosts files use quoted absolute private paths; a live path-with-spaces smoke test confirmed successful native key persistence. No container chmod/chown/ACL or ID-map adjustment was added.

Installer file publication now uses unique temporary files, fsync and atomic replacement; copy failures preserve the installed file. Two consecutive builds produced identical SHA-256 values for every distributed artifact. Frozen archives were checked byte-for-byte against their packaged source. Python 3.10 grammar parsing, compilation, shell syntax and diff checks passed; these are not claims of executing a separate Python 3.10 interpreter.

Added ten unit/failure checks since 0.1.9: malformed record preservation; recovery without querying replacements; simulated reboot device-number changes; real lock contention and transition guard; ownership recheck after lock; unmount timeout and cleanup-failure final status; unrelated live PID refusal; atomic installer failure; concurrent installer publication; tester recovery before querying a deleted fixture. Real recovery checks now remove helper PID fields, change sandbox's home while a default mount exists, and remove the LXD ownership marker before host-only unmount. The portable test also asserts that the private native known_hosts file was written. Tester cleanup now reclaims its recorded host mounts even when its target was externally deleted.

During development, the new home-change fixture first failed because usermod refuses an account with active processes; the fixture now edits/restores only that disposable container's passwd home field. A relative known_hosts experiment produced a native write diagnostic and was replaced with the verified quoted absolute path. Exploratory failures/diagnostics remain in local logs and are not the release report.

Final frozen-package verification: 107 unit tests, zero failures/errors/skips; all 20 real integration groups passed in 315.7 seconds; no cleanup errors. The isolated project, mount roots and directory/mount records were confirmed removed. Evidence: validation/V0_1_10_REPORT.json; product SHA-256 matches the distributed archive. Supplementary source smoke checks used independent test projects and were also cleaned. This batch remains a test prerelease, without stable promotion or added resource/security policy.

Limits: current Ubuntu WSL/LXD 6.9 only. As sudo authentication was unavailable, host SSHFS was the executable extracted from the official Ubuntu package in a temporary path; missing-dependency/system-sudo branches were simulated, not a fresh privileged install. Native Ubuntu, other architectures, an actual host reboot and ACL-bearing live fixtures were not exercised. Device identity across reboot, corrupt state and command timeout cases use focused simulations. Public-entry verification follows publication and is recorded separately below.


### 0.1.10 publication and public-entry verification

Published https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.10 from source commit b24c4eb7e5cf897c78844afbbcc509390c246ce3 with the frozen product, independent installer/tester, bootstrap, shell entry, checksums and WSL report. No stable promotion occurred.

Both public curl/bash flows ran in actual PTYs and resolved v0.1.10. Normal installation preserved the pre-existing tester modification time. The public --test flow downloaded and installed the matching release, then passed all 107 packaged unit tests and all 20 real groups with zero skips and cleanup errors in 342.5 seconds. Installed product/tester SHA-256 values matched the published assets. The isolated project, mount points and mount/directory records were confirmed removed; isolated preferences were restored. PTY transcripts contained no alternate-screen, screen-clear or scrollback-clear sequences. Evidence: validation/V0_1_10_PUBLIC_REPORT.json. Stage 13 environment limits still apply.

## Stage 14 — version 0.1.11, completed pending changes

Verified the section 18 checklist against code and tests before recording completion:

- Shared Selection.move wraps first/last focus in both directions. Menus, single-choice prompts, multiple-choice lists and confirmations reuse it; checked values remain independent. The necessary pre-Python Bash fallback follows the same two-option wrap rule and generated catalog labels.
- Shared UI.present prints a separating blank line and function title before content. Operations, settings and terminal entry/exit remain on their result/Back step after success, error or cancellation; the parent is restored only after return, retaining selection. Container-list navigation retains its existing dedicated selection/Back page. Real PTYs check result ordering and every lifecycle/filesystem action.
- Removed independent sudo -v. mas/dependencies.sh is the single prerequisite detector, grouped APT installer and APT presenter for the generated pre-Python entry and packaged installer. The tester delegates installation to that same installer. Only missing prerequisites trigger one update and one grouped install; Snap setup is separate and existing LXD configuration remains unchanged.
- APT uses its native C-locale output with transient normal lines in a terminal, permanent summaries/diagnostics and no transient redirected output. Unknown messages are preserved. Failure retains the full native log and return code. Questions without a newline remain visible; sudo uses its ordinary controlling terminal. No password handling or keepalive was added.
- New SSHFS sessions use allow_root. Installation enables user_allow_other in /etc/fuse.conf only if needed, preserving existing text/mode/owner and using atomic publication. Non-root mountfs checks the prerequisite before creating mount resources. Existing mounts are not changed; explicit unmount/remount is required. No container UID/GID/mode/ACL rewriting or custom mapping was introduced.
- Reproduced the reported access route locally: a mount without allow_root was readable in Linux but denied through Windows UNC. With allow_root, Windows listing, file read/create/edit/delete and directory create/delete passed. Mount-owner and root reads passed; a different ordinary identity was denied after entering the mount as root and dropping UID/GID/groups, so the assertion tests FUSE access rather than parent-directory permissions. The existing mode-0600 file retained UID/GID 1001:1001. Evidence: validation/V0_1_11_WINDOWS.json.

Final frozen-package run: 118 unit tests, zero failures/errors/skips; all 20 reported stages (the unit stage plus 19 real integration stages) passed in 317.7 seconds; no cleanup errors. Product SHA-256: dc9e7d186992d7730712075ec2128b638b1691ec3649ddb0e360f8082aac5aae. Evidence: validation/V0_1_11_REPORT.json. Builds repeated with identical asset hashes. Focused PTYs separately verified menu success/error/cancel ordering, both bootstrap-language wrap directions, system-style authentication and native APT interaction.

Environment limits: current Ubuntu WSL host only; actual Windows UNC filesystem APIs through PowerShell, without manual Explorer GUI interaction. The portable tester records the Windows access route as not_run when WSL interop is absent. Native Ubuntu/cloud, other architectures, live ACL-bearing files and offline VHDX mounting remain unverified. SSHFS was installed from Ubuntu packages using the shared helper through WSL's root invocation because this agent lacked sudo credentials; ordinary product installation still uses standard sudo. Real password entry was covered by terminal fixtures, not an actual password session. Earlier interrupted development runs were cleaned and are not counted as successful final runs.

Published and publicly verified as test v0.1.11; no stable promotion occurred.

### 0.1.11 publication and public-entry verification

Published https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.11 from source commit 7d74dcd9c0a07cdb93ea91fadcba94aee881eaa3 with product, separate installer/tester, bootstrap, fixed shell entry, SHA256SUMS and WSL_REPORT.json.

Both public curl/bash modes ran in actual PTYs and resolved v0.1.11. Normal installation preserved the existing tester's modification time. The public --test flow passed all 118 packaged unit tests and all 20 reported stages in 347.3 seconds, with no skips or cleanup errors; its Windows UNC event passed. Installed product/tester hashes matched the release assets. The isolated project, mounts and tracked directories were confirmed reclaimed, and isolated preferences restored. No alternate-screen, screen-clear or scrollback-clear sequences were observed. Evidence: validation/V0_1_11_PUBLIC_REPORT.json. Stage 14 environment limits still apply.


## Stage 15 — version 0.1.12, mount-preserving lifecycle and menu contracts

Verified sections 19–21 against the shared implementation and frozen archives before recording completion:

- start/stop share one lifecycle sequence. For a real state change, snapshot this user's recorded paths, sequentially call the existing unmountfs, run the existing native lifecycle and user preparation, then sequentially call the existing mountfs. Preserve exact paths and the default-home tag. The first unmount failure aborts without other unmounts, native transition or caller rollback. Native lifecycle/user-preparation failure propagates unchanged and naturally skips the suffix; no added failure probe, recovery report or restoration handler exists. Restoration failures do not prevent remaining attempts; an aggregate error identifies each failed container/host path and the completed state. No-op requests leave mounts alone; delete still requires explicit unmount. enter, stop-all and on_exit inherit shared behavior.
- Manager caches its Filesystems instance. Its registry lock is reentrant within that object and retains cross-process exclusion over the sequence; nested foundational calls reload committed records. Foundation cleanup, path conflicts, identity checks and parent reclamation remain the single implementations used by explicit and automatic operations.
- Shared menu/output boundaries provide one blank line between title, input blocks, first operation output and the result/Back block. Progress remains transient; success, native diagnostics and result details remain consecutive. Both catalogs use explicit input/action/default wording; long input instructions wrap within the inline area. Command syntax and external output are unchanged.
- The shared column component left-aligns display-width-aware rows and status colors/text. Container selection shows name/status. Unmount shows each container path once without the host destination or a duplicate table. Normally mounted-only lists omit status; if abnormalities require status, every data row includes it. Back remains a navigation control. Foundational success and flow-completed messages are both retained.
- After an actual container shell exits, shared on_exit runs and the mas invocation ends at the host shell, including post-shell failures. No result/Back or parent menu follows. Pre-entry failures keep the usual result page. CLI errors retain a nonzero result. Native terminal handoff remains unchanged.

Added 15 packaged tests: seven lifecycle/locking tests and eight menu/exit/display tests. The display regression includes twelve actual PTY cases across Chinese/English creation, mounting, no-input results, errors, cancellation and empty results, checking rendered single-gap boundaries and consecutive diagnostics. Supplemental packaged-presentation evidence: validation/V0_1_12_DISPLAY.json (controlled operation output, not a native LXD operation). Real integrations now keep two independent mounts through stop/start, also exercise root mounts through both transitions, and verify continued content access. Real menu-entry sessions separately verify default keep-running, explicit stop and Escape cancellation returning to the host shell with the expected container state.

An exploratory full run found two tester assertions still waiting for the old deletion wording. That run was interrupted and its fixtures were successfully cleaned; both expectations were corrected before the final complete run. Its partial result is not counted as final validation.

Final frozen-package result: 133 unit tests with zero failures/errors/skips; all 20 reported stages (unit plus 19 real integration stages) passed in 362.6 seconds with no cleanup errors. The isolated LXD project, mount roots and mount/directory records were confirmed reclaimed. Windows UNC read/write operations passed again. Evidence: validation/V0_1_12_REPORT.json. Product SHA-256: 80a6cdeb4f3510c7a3c0fd6a30d26a28bf171d7b2c443abd5249988564f3e111. Repeated builds have identical asset checksums; packaged source matches the workspace. Python 3.10 grammar parsing, shell syntax and diff checks passed.

Limits: current Ubuntu WSL/LXD host only. Native Ubuntu/cloud, other architectures, live ACL-bearing files, offline VHDX access and a fresh privileged installation were not rerun. Lifecycle failure branches use controlled injection; real tests establish successful transitions/restoration. Prior Windows Explorer success is user-reported, separate from the portable tester's Windows UNC API verification. No additional permission/resource policy, dependency or stable promotion was introduced. Test publication and public-entry verification are recorded below after execution.


### 0.1.12 publication and bootstrap check failure

Published test v0.1.12 from a66ab80dbc485f509a13eab971bdba3e004b9768 with seven assets. The first public normal-installation check failed before language selection: the shell entry's minimal download list omitted mas/output.py after the shared menu began importing it. The module is present in the product/installer archives; local native tests did not exercise this separately downloaded bootstrap dependency boundary. No successful public installation or public full-test result is claimed for this version. Its published assets are retained unchanged. Version 0.1.13 corrects the fixed entry and release shell artifact.

## Stage 16 — version 0.1.13, bootstrap dependency correction

The generated fixed entry now downloads mas/output.py with the shared menu's other runtime modules. The standalone tester includes the generated install.sh only to exercise its actual Python download block with controlled source responses. A clean interpreter using -I then imports bootstrap and the downloaded menu from that isolated directory, without the development checkout. This regression uses the shell entry's own manifest instead of maintaining a second list. Normal product/installer separation is unchanged; no tester content is added to ordinary installation.

Verified source discovery: 134 tests passed, with only the existing archive-boundary check skipped outside an archive. The packaged unit stage also passed with the matching 0.1.13 product; full native and public-entry validation remains in progress. No change to the 0.1.12 container or mount behavior is made in this corrective batch.

Final local 0.1.13 verification: 134 packaged unit tests, zero failures/errors/skips; all 20 reported stages passed in 365.7 seconds with no cleanup errors. The isolated project, mount roots and registry entries were verified removed; the Windows UNC event passed. Evidence: validation/V0_1_13_REPORT.json. Product SHA-256: 81be0c454b30d2bb8cb6fb260b86d286e70dea7a5d4091361045fdd8bceeeba7. Repeated builds matched byte-for-byte. This supersedes the earlier in-progress validation status; public-entry checks follow publication. Stage 15 environment limits remain applicable.


### 0.1.13 publication and public-entry verification

Published https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.13 from 0703f0ed327a1b9f36a6cdc9b62b08aeef51bb5f with the frozen product, separate installer/tester, corrected shell entry, bootstrap, checksums and WSL_REPORT.json. Earlier assets, including 0.1.12, were not replaced; 0.1.12 release notes identify its shell-entry defect and the corrective release.

Both fixed public curl/bash modes resolved and installed 0.1.13 in actual PTYs. Ordinary installation preserved the existing tester modification time. Public --test passed all 134 packaged unit tests and all 20 reported stages in 368.5 seconds, with no skips or cleanup errors. Installed product/tester hashes matched the published assets; the Windows UNC event passed. The isolated LXD project, mount root and registry entries were confirmed reclaimed and isolated language preferences restored. No alternate-screen, screen-clear or scrollback-clear sequences were observed. Evidence: validation/V0_1_13_PUBLIC_REPORT.json. This completes sections 19–22, including the corrected public bootstrap boundary. Test prerelease only; no stable promotion. Stage 15 environment limits remain unchanged.


## Stage 17 — version 0.1.14, explicit operation responsibilities

REQUIREMENTS.md section 23 was written before implementation. The code and full frozen package were then checked against it before this completion record.

- Shared lifecycle orchestration names external pre-processing, internal execution and external post-processing. sandbox setup remains mandatory internal start work; native Running alone is insufficient. Internal failure propagates unchanged and naturally prevents restoration, without a new failure handler, state query or rollback. Existing single-path foundations retain unmount/mount ownership; first-unmount failure aborts, restoration continues after individual failures, no-op requests leave mounts alone and the reentrant registry lock spans the full sequence.
- Every foundational/composed function, settings and installation was reviewed. CORE_BEHAVIOR.md now inventories their internal duties and actual external coordination. No empty phase methods or generic hook framework was added. Import marking and export validation/publication remain internal requirements. Deletion-only guard names now reflect their scope; intentional ownership/state rechecks remain.
- Mount creation separates journal/resource preparation, listener launch/readiness, SSHFS launch, observation and final identity publication. Probes have no process-launch or record-save side effects. Readiness shares the original deadline. Failure protection now includes the first journal write and directory creation, reusing unmount cleanup; a work_created flag protects a pre-existing private-directory collision and retains its recovery record. Legacy records remain accepted.
- Shared diagnostics protect primary failures from reporting or secondary cleanup failures. Registry/config/installer temporary files, export directories and native-client cleanup reuse this policy. A standalone cleanup failure remains a failure. stop-all aggregates Error/OSError with target names; shell and on_exit failures preserve both diagnostics and return to the host shell.
- CLI/menu adapters inject confirmation presentation; absent providers decline. Shared progress/info/mount-list formatting lives in mas/presentation.py, eliminating the menu-to-CLI dependency. Native steps are transient, distinguished from complete internal function success; required work must finish before function success. Native warnings remain. Bootstrap's actual download manifest includes the newly shared diagnostics dependency and its packaged regression passed.

Validation: 153 packaged unit tests, zero failures/errors/skips; all 20 reported stages (unit plus 19 native integration stages) passed in 369.4 seconds. This adds 19 focused boundary tests to 0.1.13. Actual checks covered multi-path/root/default-home restoration through start/stop, Windows UNC read/write, CLI, inline menus, terminal exit, backups, ownership isolation and resource recovery. The isolated project, mount root and registry entries were independently confirmed reclaimed. Evidence: validation/V0_1_14_REPORT.json. Product SHA-256: c4da24e24acd99cefe4a93c7b511927d0f84a14e13434445eff547074f58d218.

Repeated builds matched byte-for-byte; packaged source matched the workspace. Python 3.10 grammar, shell syntax and diff checks passed. Unit discovery outside the archive retains its expected single archive-only skip; final packaged tests had none.

Limits: current Ubuntu 26.04 WSL/LXD 6.9 host. Native Ubuntu/cloud, other architectures, fresh privileged installation, offline VHDX and additional ACL cases were not rerun. Failure branches use controlled injection, not a live disk-full or daemon-outage campaign. Windows UNC API checks are distinct from manually inspecting File Explorer. No new third-party dependency, resource exposure, 0.2.x configuration policy or stable promotion was introduced. Publication and public-entry results follow after execution.


### 0.1.14 publication and public-entry verification

Published https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.14 from c752147e7e0c072f97bbe7876bda5e18a372eaad with seven assets: mas.pyz, mas-install.pyz, mas-test.pyz, bootstrap.py, install.sh, SHA256SUMS and WSL_REPORT.json. Earlier releases/assets remain unchanged.

Both fixed curl/bash modes resolved 0.1.14 and succeeded in actual PTYs. Ordinary installation preserved the existing tester modification time. Public --test passed all 153 packaged units and all 20 report stages in 367.1 seconds, without skips or cleanup errors. Installed product/tester hashes matched the frozen release files; the Windows UNC event passed. Independent checks confirmed the isolated project, mount root and registry entries were reclaimed. Language preferences were isolated and restored; no alternate-screen, screen-clear or scrollback-clear sequences were observed. Evidence: validation/V0_1_14_PUBLIC_REPORT.json.

This completes section 23, including test publication and public-entry verification. The above environment/coverage limits remain; no stable promotion occurred.


## Stage 18 — version 0.1.15, dependency terminal flow and merged navigation

Requirements sections 24–25 were recorded before product changes. Implementation was then verified against those requirements before this completion record.

The installation hang was reproduced without installing host packages: real same-user sudo-rs 0.2.13-0ubuntu1.2 with terminal stdin and piped output left a forked terminal-reading child in T. Direct-terminal and EOF-input variants completed. Observations and the minimal source are retained in validation/V0_1_15_SUDO_REPRODUCTION.json. Ubuntu's installed changelog did not list the related terminal fix; upstream sudo-rs issue 1598 was investigated, but the exact signal/patch attribution was not established from this process snapshot.

- The single shared Bash helper now keeps sudo's own stdout connected to the terminal and places the APT/tee/renderer pipeline inside sudo's command. Interactive package input remains a terminal; redirected output uses EOF package input while sudo still owns authentication. No sudoers change, sudo replacement, standalone sudo -v, stored password, keepalive or new dependency was introduced. Failure status and full native failure logs are preserved.
- Rendering buffers normal partial prefixes across read timeouts and handles carriage returns; it does not automatically make unterminated ordinary progress permanent. Unknown native prompts remain visible before newline, and warnings/errors remain permanent. Bootstrap and installer use the same implementation; the generated shell was rebuilt and its dependency/package regression passed.
- Bare mas opens one main menu with list/new/import/mas preferences/exit. Chinese is mas 选项; English is mas Preferences. Container actions remain behind selection. Stop all is before Back in the container list only when more than one managed container exists and at least one live status is not exactly Stopped. A non-name control key avoids collisions. After actions the list and eligibility refresh, retaining valid selection; initial selection is the first container. Query failures remain errors. The existing Manager.stop_all and per-target stop orchestration are unchanged.
- Deletion's bilingual no-mount instruction now refers only to deletion. Existing deletion guards, exact mount cleanup and lifecycle behavior are unchanged.

Nine new units bring the total to 162; they cover real sudo/PTY child reads and unterminated prompts, redirected operation, normal/diagnostic fragments, main-menu structure, conditional bulk actions, first-row selection, preference return, name/control separation, query failure and shared stop-all reuse. Existing controlled authentication tests remain. A new native dependency-install stage executes actual APT update and SSHFS installation as sandbox through system sudo inside a disposable test container; the recorded versions exactly match the reported host: sudo-rs 0.2.13-0ubuntu1.2 and apt 3.2.0 (amd64). This fixture-only installation does not change product container provisioning.

An exploratory integration run was deliberately interrupted after a review caught the first-container default selecting Back. The selection was corrected and asserted before rebuilding the final package; exploratory resources were reclaimed. Its partial results are not release evidence.

Final frozen validation: 162 packaged units with zero failures/errors/skips; all 21 report stages (unit plus 20 integrations) passed in 420.6 seconds. The new merged menu, eligible bulk stop, native dependencies, lifecycle/mount recovery, Windows UNC operations and terminal exit passed. Independent checks confirmed the isolated project, mount root and registry entries were reclaimed. Report: validation/V0_1_15_REPORT.json. Product SHA-256: bf14e7b76ca767ca03a7ae3eeddbd32b85caf1ddd4c82df195e971119dec5bb6. Packaged sources match the workspace and repeated builds are byte-identical; Python 3.10 grammar, shell syntax and diff checks passed.

Limits: the full fresh-host snap/LXD/group/FUSE installation was not repeated. Actual password entry remains a user/system boundary, tested with controlled prompt fixtures; the new live sudo probe uses the same user and the container installation uses standard mas passwordless sudo. Native Ubuntu/cloud, other architectures and offline VHDX remain unverified. The user's already-paused old installer was not resumed or terminated. No stable promotion. Public verification follows publication.


### 0.1.15 publication and public-entry verification

Published https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.1.15 from 634e37e0feddb8b97740d1c2b71e98ecc9548c46 with seven frozen assets: product, separate installer/tester, bootstrap, shell entry, checksums and WSL_REPORT.json. Earlier release assets remain unchanged.

Actual PTY runs of the fixed public curl/bash normal and --test entry both resolved 0.1.15. Normal installation preserved the existing tester modification time. Public --test passed 162 packaged units and all 21 report stages in 389.2 seconds, without skips or cleanup errors. It included actual sudo/APT installation in the test container, the merged navigation and Windows UNC access. Installed product/tester hashes matched the release files. Independent checks confirmed the isolated project, mount root and registry entries were reclaimed; temporary language preferences were restored, and no alternate-screen or screen/scrollback-clearing sequences were observed. Evidence: validation/V0_1_15_PUBLIC_REPORT.json.

Sections 24–25 are delivered. The limits above still apply; the user's existing stopped installer remains outside this verification. Test prerelease only, no stable promotion.


## Stage 19 — phase 1 stable 0.1.15 audit and promotion

Section 26 was recorded before promotion. Reviewed REQUIREMENTS.md, implemented behavior, core/lifecycle/ownership boundaries, filesystem resource handling, installer/bootstrap/dependency orchestration, CLI/menu/config/presentation modules, packaging and failure/native test coverage. No additional product-code correction was identified as necessary for phase 1. The full review inventory and limits are in validation/STABLE_0_1_15_AUDIT.md. This is a promotion of unchanged bytes, not a new development batch or a claim of exhaustive defect absence.

Final matching packaged tester run: 162 unit tests, no failures/errors/skips; all 21 reported stages passed in 394.0 seconds, no unexecuted stages or cleanup errors. Native dependency installation, lifecycle/mount restoration, abnormal filesystem recovery, Windows UNC access and inline menu/shell behavior passed. Independent checks confirmed the temporary LXD project, mount root and registry entries were reclaimed. Evidence: validation/V0_1_15_STABLE_REPORT.json.

Downloaded the published v0.1.15 product, installer and tester and verified checksums, local archive equality and every included workspace source. Product/installer exclude test modules. Python 3.10 grammar and shell syntax checks passed. The fixed public entry with --release v0.1.15 completed in an actual PTY, installed the matching product and left the existing tester hash and modification time unchanged; preferences were isolated. Evidence: validation/V0_1_15_STABLE_INSTALL.json.

Published https://github.com/gdrencn/my-ai-sandbox/releases/tag/stable/0.1.15 as a non-prerelease and GitHub latest, targeting the unchanged source commit 634e37e0feddb8b97740d1c2b71e98ecc9548c46. Its three assets are mas.pyz, mas-install.pyz and SHA256SUMS; no tester or test report is attached. Product SHA-256 is bf14e7b76ca767ca03a7ae3eeddbd32b85caf1ddd4c82df195e971119dec5bb6; installer SHA-256 is 9156ff2cec3b3e54b15d4c59d46c44c05f4d9ae3801035396f839ecc51f5d105. Public stable downloads were compared byte-for-byte with the prepared assets and matching test binaries. The seven original test assets and prerelease metadata were confirmed unchanged. Both numeric-pinned and latest-test bootstrap resolution still select v0.1.15. Evidence: validation/V0_1_15_STABLE_RELEASE.json.

Stable installation is documented with --release v0.1.15; same-version validation adds --test and uses the preserved test prerelease. The existing unpinned latest-test entry was intentionally retained. There is no new channel-selection option and no product version suffix.

Environment remains Ubuntu 26.04 WSL / LXD 6.9. The user's separate fresh-install log verifies successful dependency/FUSE/snap/LXD setup but stopped on a remote HTTPS connection reset before later integration cases; it is not represented as a successful complete suite. Native Ubuntu/cloud, other architectures, offline VHDX, live disk-full/daemon-outage scenarios and additional resource/security policy remain outside this verification. No source code, tester code, third-party dependency or host/container resource policy was changed during promotion.


## Stage 20 — independent GPU hardware option (0.2.1)

Verified against REQUIREMENTS.md sections 27–28 before this update. `mas/gpu.py` owns capability discovery, settings, exact resource records, configuration validation, atomic native configuration publication/readback, runtime-file cleanup and runtime preparation. CLI `mas hardware TARGET [gpu [on|off]]` and the per-container Hardware options menu reuse Manager.hardware. GPU is the first and currently only hardware option. Default-on configuration applies to new supported containers and stopped-to-running legacy/imported containers; explicit off persists. Running-container mutation is rejected; there is no implicit stop or hot removal.

Measured WSL backend: `/dev/dxg`, read-only `/usr/lib/wsl/lib`, and two NVIDIA driver-store subdirectories containing libcuda.so.1.1. The complete Windows/WSL driver store is not exposed. An initial native LXD 6.9 CDI probe failed with NVML Driver Not Loaded; WSL therefore uses native LXD unix-char/disk devices explicitly. The prototype was stopped and deleted. No additional host/container package was installed for GPU support or CUDA verification. Resource records are stored in user.mas.gpu. The module owns /etc/ld.so.conf.d/mas-gpu.conf and runs ldconfig inside the container; ordinary data, unrelated devices, host drivers and network policy remain unchanged.

Start's external pre-processing reuses GPU.ensure after filesystem unmounts. Required GPU runtime preparation is part of internal successful start after sandbox preparation; failure prevents complete start success and filesystem restoration. GPU set reuses the existing shared mutation lock. Native configuration and the corresponding ownership record are published together. Invalid records, changed devices, conflicting runtime files and native failures are refused without a false success result. Cleanup of recorded access remains available when host discovery fails. Driver directory refresh reuses the same setter.

Frozen local validation: **177 packaged units, all 22 report stages passed, 459.4 seconds, no skipped units, no unexecuted stages or cleanup errors**. GPU testing used the actual product CLI and a real terminal menu, sandbox CUDA initialization, PTX JIT/kernel execution and host readback of 42, read-only mapping checks, disable/restart access denial, re-enable/restart computation, and preservation of non-GPU devices. Report: validation/V0_2_1_LOCAL_REPORT.json. Product SHA-256: 4eb61ee5e3b0e726c4c166bc959f4f63ee9b430dc48c4987a83c8721c10dddcc.

Development checkpoints: an early native probe corrected an unsupported lxc config show --format assumption; JSON instance queries are used instead. A real PTY caught the hardware submenu initially focusing Back because its key matched the unspecified default; the explicit default now selects GPU. Two intermediate full runs were intentionally interrupted to incorporate corrections and additional guards; their temporary resources were cleaned. They are not counted as successful release validation.

Boundaries: current hardware discovery/backends target NVIDIA. WSL2 RTX 5090 Laptop GPU was tested; native Ubuntu NVIDIA CDI is implemented but not hardware-verified. AMD/Intel discrete GPUs remain unsupported. WSL DXG access is not per-adapter isolation. Windows driver-update scenarios are covered by fault tests, not an actual driver upgrade. No restricted project/profile policy, CPU/memory/process limits or network controls are implemented by this batch. Stage 1 stable remains available and unchanged.

Publication/public verification: published https://github.com/gdrencn/my-ai-sandbox/releases/tag/v0.2.1 with all seven standard test assets. Public normal installation resolved 0.2.1, installed the matching product hash and left the existing tester byte-for-byte and mtime unchanged. Public --test resolved 0.2.1 and passed all 177 packaged units and 22 report stages in 462.2 seconds, including real GPU computation and menu switching, with no skips or cleanup errors. The installed product matches the frozen local product hash. Reports: validation/V0_2_1_PUBLIC_REPORT.json, V0_2_1_INSTALL_CHECK.json and V0_2_1_RELEASE_CHECK.json. All seven release asset digests match local files; repeated builds reproduce the same SHA256SUMS. Product/installer archives contain no tester or tests. GitHub latest remains stable/0.1.15; earlier release assets remain unchanged. User language preferences were preserved using an isolated XDG_CONFIG_HOME for public checks.

## Stage 21 — terminal test synchronization (0.2.2)

The user reported a menu test waiting 600 seconds for the stop question after sending exit; its transcript ended at the sandbox shell prompt without exit/logout. Inspection found the shared shell probe sent the next input as soon as sudo printed 0, before observing the shell regain control. Initial entry also matched sandbox@ inside terminal titles. A controlled real PTY reproduced loss of early exit input during delayed terminal restoration and input flushing. This establishes the tester race; the original machine's syscall trace is unavailable, so it does not identify a particular upstream sudo implementation as the proven source of that flush.

Terminal.expect now shares a cursor-aware pattern matcher which checks buffered output before waiting for new bytes. Terminal.shell_ready recognizes the actual Ubuntu sandbox prompt after terminal control/title sequences, without assuming that the guest hostname equals TARGET. All CLI/menu shell probes wait for this prompt before the probe and after its output, before exit is sent. No fixed synchronization sleep, timeout increase, product lifecycle change, GPU change, or dependency was introduced. The product/installer version advances with the matching tester.

Verification: 179 packaged units and all 22 native stages passed in 461.8 seconds, with no skipped units, unexecuted stages or cleanup errors. The previously failing menu stage passed in 83.8 seconds, including imported-container exits with No, Yes and Escape. Two new real PTY tests cover loss with the output-only handshake and successful synchronization under the same delayed flush, title/control sequences, fragmented prompt and different hostname. Twenty repeated rounds passed all 40 checks. Repeated builds produce identical hashes; product/installer exclude tests and the runner. Evidence: validation/V0_2_2_LOCAL_REPORT.json and V0_2_2_TERMINAL_REPEAT.json.

GPU active-driver selection remains pending separate investigation; this release preserves the 0.2.1 resource-selection behavior. Stable 0.1.15 remains unchanged.

Publication verification: v0.2.2 is published with all seven standard test assets. The unpinned public install.sh --test entry resolved 0.2.2 and passed 179 packaged units / 22 stages in 487.6 seconds; the menu stage passed in 83.3 seconds. No skips, unexecuted stages or cleanup errors. Installed product/tester hashes and all seven GitHub asset digests match the validated local files. The user's preferences were preserved through isolated XDG_CONFIG_HOME. Evidence: validation/V0_2_2_PUBLIC_REPORT.json and V0_2_2_RELEASE_CHECK.json. GitHub latest remains stable/0.1.15.

## Stage 22 — official active WSL GPU driver discovery (0.2.3)

Replaced production driver-store scanning with `/snap/lxd/current/bin/nvidia-ctk cdi generate --mode=wsl --format=json --output ''`, using the NVIDIA tool already supplied by LXD. The empty output argument explicitly keeps discovery on stdout. NVIDIA's WSL implementation queries DXCore for adapter-associated driver paths. mas reads only the returned all-device/global CUDA mount entries, validates their driver-store scope, matching container path, read-only option, actual file and non-redirected canonical path, then passes selected directories to the existing GPU setter. It does not apply CDI, execute hooks, implement DXCore, install a package, or change native Ubuntu's GPU backend.

GPU.ensure reuses discovery before each real Stopped-to-Running transition and reuses GPU.set when the selection changes. Old recorded device mappings are replaced atomically with the new inventory, including migration from multiple previously scanned directories. Running mappings remain unchanged. Off startup and owned cleanup do not require successful discovery. Tool absence, execution failure, timeout, invalid/empty JSON selection, unsafe/redirected paths and missing selected CUDA files fail explicitly without scanning/cached fallback. Native warnings and unrecognized diagnostics remain visible; informational discovery logs are omitted.

Frozen verification: 189 packaged units, all 22 native stages passed in 449.4 seconds; no skips, unexecuted stages or cleanup errors. New tests cover official-only lookup, ignored hooks, global/device edit locations, deduplication, requery, missing/failing tool, timeout, malformed/empty/wrong-kind data, unsafe/missing/redirected paths, warning retention, legacy multi-directory replacement, disabled cleanup and discovery failure preventing native start and external post-processing. An initial test-fixture nested autospec error was corrected before this successful frozen run; the failed preliminary run is not counted as validation.

Measured LXD-bundled nvidia-ctk version: 1.19.1. On this host the official selection was `/usr/lib/wsl/drivers/nvrzi.inf_amd64_6a54f45845aaf4cd`; the coexisting `/usr/lib/wsl/drivers/nvrzi.inf_amd64_94140ac3dbff22dd` was excluded and its CUDA library was absent inside the container. sandbox CUDA computation returned 42 with only the selected read-only mapping; off/re-enable and repeat computation passed. Evidence: validation/V0_2_3_LOCAL_REPORT.json, gpu.driver_selection and compute results.

Selection-change and failure cases are controlled tests; Windows was not updated/rebooted for this batch. Native Ubuntu NVIDIA CDI and AMD/Intel support boundaries remain unchanged. Official WSL probing can emit optional-component/NVML-version and multiple-adapter warnings despite successful resource discovery; warnings are retained and success requires validated output plus real compute validation.

References: https://github.com/NVIDIA/nvidia-container-toolkit/blob/main/pkg/nvcdi/driver-wsl.go and https://github.com/NVIDIA/nvidia-container-toolkit/blob/main/internal/dxcore/dxcore.c .

Publication verification for 0.2.3: the unchanged public release resolver selects v0.2.3. All seven public assets were downloaded and compared byte-for-byte with the locally verified frozen files; the downloaded product reports 0.2.3. The raw fixed install.sh entry matches the repository. GitHub latest remains stable/0.1.15. Repeated builds reproduce identical SHA256SUMS; product/installer contain no tester/tests. Evidence: validation/V0_2_3_RELEASE_CHECK.json. The full native suite was not repeated through public installation in this batch; public checks verify that the delivered artifacts are the same ones that passed the frozen full suite.

## Stage 23 — GPU/diagnostic integration review (0.2.4)

Reviewed the GPU module, shared native-command diagnostics, hardware menu, progress rendering and portable tester integration. The WSL query now uses official --disable-hook=all and --feature-flag=disable-nvsandboxutils options, with --nvidia-cdi-hook-path pointing to the already present nvidia-ctk for compatibility path resolution. No hooks are generated/applied/executed and no dependency is installed. Measured original/optimized device and mount lists are identical; warnings per probe fall from five to two. Remaining driver-version/NVML and multiple-adapter warnings remain visible; no quiet mode, duplicate-message suppression or cached startup discovery was introduced. Evidence: validation/V0_2_4_DISCOVERY_CHECK.json.

GPU discovery and LXD queries reuse diagnostics.emit_native, which routes through the caller's existing Output.keep callback (or the standard stderr fallback). This clears active transient progress before permanent diagnostics. GPU exposes a contextual detect wrapper so direct tester discovery uses the same callback. Tester-owned direct queries append native-diagnostics.log and structured events. Product subprocess query diagnostics also enter event files; CLI diagnostics are displayed from capture once, while terminal-session query diagnostics are replayed from events once. This closes a PTY reporting gap without printing every normal terminal line.

Hardware-menu cancellation keeps the last-read state instead of immediately rerunning discovery; mutation attempts invalidate it and refresh on return. Actual startup and explicit GPU changes still probe fresh. Official mount/options collections and integer record version are validated more strictly; ownership checks precede status discovery. Driver-directory syntax and owned loader-file content each have one shared definition. The loader preparation retains the same content and behavior.

Seven added tests cover malformed option/collection types, malformed version rejection before probing, menu cancel without mutation/requery, diagnostic callback failure preserving the primary result, direct diagnostic log/event preservation, actual CLI/PTY query diagnostics displayed exactly once, and real-terminal clearing of a transient GPU progress line. Existing tests continue to cover per-start discovery, driver changes, owned cleanup, path validation and failures.

Frozen validation: 196 packaged units and all 22 native stages passed in 484.6 seconds, no skipped units, unexecuted stages or cleanup errors. GPU sandbox CUDA computation, off/on behavior, selected-directory exclusion, filesystem restoration and complete menu flow passed. Evidence: validation/V0_2_4_LOCAL_REPORT.json. This is a targeted integration review, not a claim that all possible optimization or fault scenarios are exhausted.

Official option references: https://github.com/NVIDIA/nvidia-container-toolkit/blob/main/pkg/nvcdi/api.go , https://github.com/NVIDIA/nvidia-container-toolkit/blob/main/pkg/nvcdi/options.go and https://github.com/NVIDIA/nvidia-container-toolkit/blob/main/cmd/nvidia-ctk/cdi/generate/generate.go . Existing GPU platform and Windows-driver-update validation boundaries remain unchanged.

0.2.4 publication verification: the public resolver selects v0.2.4; all seven downloaded assets match the locally validated frozen files byte-for-byte. The downloaded product reports 0.2.4, and raw main/install.sh matches the repository. Repeated builds reproduce checksums and product/installer archives exclude tests. GitHub latest remains stable/0.1.15. Evidence: validation/V0_2_4_RELEASE_CHECK.json. Full public installation/testing was not rerun in this batch; the complete native validation above exercised the identical published artifacts.

## Stage 24 — Portable test subprocess imports (0.2.5)

The installed 0.2.4 tester failed in its GPU diagnostic PTY test because its child Python process did not receive the tester import path. Reproduced using the unchanged 0.2.4 zipapp from /tmp. Prior 0.2.4 validation ran inside the checkout, which hid the omission; identical downloaded bytes did not establish working-directory independence.

A shared testing.python_command builds isolated Python fixture commands and explicitly inserts the import root derived from the currently loaded tester module. It supports both the source checkout and zipapp without depending on sys.path[0], cwd, user-site packages or PYTHONPATH. Menu, language, progress, diagnostic, spacing and optimized-Python test fixtures reuse it. Generic Terminal execution, independent bootstrap tests and standard-library shell simulation remain separate. Product GPU behavior is unchanged.

A new regression runs from an unrelated directory containing a misleading mas.py and PYTHONPATH-only module, with a misleading parent sys.path[0], and verifies that the child loads the actual tester and ignores the injected module. Frozen zipapp validation was run with python3 -I and absolute product/tester paths from /tmp: 197 units and all 22 native stages passed in 452.2 seconds; no skips or cleanup errors. Evidence: validation/V0_2_5_LOCAL_REPORT.json. Repeated builds yield identical checksums; product and installer exclude test code. Release procedure now requires packaged validation outside the checkout.

0.2.5 public verification: all seven downloaded assets match the frozen local files; the resolver selects v0.2.5 and GitHub latest remains stable/0.1.15. Executed the actual public curl | bash --test entry from /tmp, installing the released product/tester and completing all 197 units and 22 native stages in 450.7 seconds, without skips or cleanup errors. The installed product reports 0.2.5. Evidence: validation/V0_2_5_RELEASE_CHECK.json and validation/V0_2_5_PUBLIC_REPORT.json.
