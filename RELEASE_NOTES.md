# v0.1.0-test.2

Fix fresh installation failing with `error: access denied (try with sudo)` at `snap wait system seed.loaded`. This step now uses the shared privileged-command runner. The permission failure was reproduced on the development host, and a regression test covers both existing and missing snapd. This does not require users to configure passwordless host sudo.

Container behavior is unchanged from test.1:

- Commands: new, list, start, stop (including --all), delete, info, import, export, enter.
- Default Ubuntu image follows the host release. Containers are created stopped.
- Default terminal user sandbox has passwordless sudo. Exit asks whether to stop, default no.
- Both interfaces confirm deletion. Existing export files require overwrite confirmation, default no.
- One-second state polling, 10-minute default operation timeout, minimum configurable timeout of five minutes.
- Only containers with user.mas.managed=true are managed. Import rejects any existing target name.
- Separate product and automated test zipapps; fixed installer resolves the latest test prerelease and checks SHA-256.

Install latest test:

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash
```

Install and run the matching complete test suite:

```bash
curl -fsSL https://raw.githubusercontent.com/gdrencn/my-ai-sandbox/main/install.sh | bash -s -- --test
```

Assets: mas.pyz, mas-test.pyz, bootstrap.py, install.sh, SHA256SUMS, and WSL_REPORT.json. The report identifies the tested product by hash and includes test results and waiting times; detailed CLI and terminal transcripts are retained locally by each test run.

Test environment: WSL2 Ubuntu 26.04.1, x86_64, Python 3.14.4, LXD 6.9, dir storage and the standard LXD bridge. Native Ubuntu is supported by design but has not been tested on a separate host. Fresh-system package installation by the installer has not been exercised end to end; existing-environment installation has been verified. WSL without systemd needs the documented enable/restart step.

Validation: 20 unit tests and all 13 real integration groups passed against the test.2 product, with no cleanup errors. Results and the product hash are recorded in WSL_REPORT.json and validation/TEST_2_REPORT.json. The new regression test exercises the fresh-install command path with subprocess permission checks; it does not claim a full live fresh-host installation.

LXD backups preserve MAC identities. Restoring while the source still exists on the same network may prevent the restored container from starting; this release does not rewrite network identities. GPU, host resource whitelists, directory sharing and model installation are outside this release.
