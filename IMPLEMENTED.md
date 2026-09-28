# Implementation status

Current result: version 0.1.4 is publicly released. Final artifact validation and both public entry paths passed on the current WSL host. See Stage 7. Development checkpoint numbers below are not version phase numbers; the version phase remains 1.

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
