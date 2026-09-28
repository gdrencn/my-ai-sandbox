# Implementation status

Current result: version 0.1.4 has passed final artifact validation on the current WSL host. Public publication and entry checks remain. See Stage 7. Development checkpoint numbers below are not version phase numbers; the version phase remains 1.

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
