# Implementation status

Current result: v0.1.0-test.1 is publicly released; a reported fresh-install permission bug is fixed locally for v0.1.0-test.2. See Stage 5. Earlier successful existing-host tests did not cover the failing fresh-install step.

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

The v0.1.0-test.2 product and matching tester passed all 13 real integration groups (including 20 unit tests), with exit code 0 and no cleanup errors. The tested product hash matches the release artifact; evidence is in validation/TEST_2_REPORT.json. Publication is the remaining step. A full live fresh-host installation remains unverified here.
