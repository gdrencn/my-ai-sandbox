# Container operation behavior

This is an inventory of the additional behavior implemented in mas/core.py as of batch 0.1.10. CLI and text menus call the same Manager. Installation is separate from these operations.

## Shared execution and validation

- Locate lxc using PATH, then /snap/bin/lxc; fail with a setup instruction if absent. Use the local server and explicit project (default for the product; isolated project for tests).
- Require an operation timeout of at least 300 seconds; default 600. Queries capture output, reject timeout/nonzero exit, and retain native stderr. Instance queries use lxc list local: --format=json, parse JSON and validate list/row structure. Query failure or malformed data never means target absence.
- TARGET accepts 1–63 ASCII letters/digits/hyphens, starts with a letter and ends with an alphanumeric character. Reject remote, snapshot and option-like selectors.
- An owned instance must have type container and instance-local config user.mas.managed exactly equal to true as a string. An inherited profile marker is insufficient. Existing-container operations require ownership; host-only recovery of existing filesystem records does not query or mutate a replacement container; new/import name collisions inspect all instances.
- Mutating _operation calls capture native stdout/stderr in temporary files to avoid pipe backpressure. Observe structured state every second, require both native exit zero and expected state, and normally require the ownership marker. Native nonzero exit, LXD Error state and query failures abort. Report observations, elapsed time, final result and native output.
- On timeout/failure/interruption, stop a still-running client process and wait for it; do not claim the LXD daemon operation has been cancelled. Timeout messages include the last observed state; the final event includes elapsed time. Interactive container shells do not use this operation timer.
- Confirmation is shared: terminal radio menu defaults No, --yes/--no supply explicit decisions, noninteractive input without consent declines. CLI/menu presentation localizes mas text and preserves original external output.

CLI and text-menu waiting events share the tester's terminal-line renderer: normal progress refreshes in place, final results and diagnostics remain, and redirected output omits waiting ticks. Successful query stderr uses a permanent-output callback in the product so it cannot be erased by subsequent progress. Structured event records remain complete. This presentation change does not change operation completion criteria.

## Operation inventory

| Operation | Before native execution | Native execution | After / alternate branch |
| --- | --- | --- | --- |
| new | Validate TARGET; reject any existing name; choose ubuntu:<host VERSION_ID> from Ubuntu /etc/os-release unless overridden; reject an image starting with '-' | lxc init IMAGE local:TARGET -c user.mas.managed=true | Wait for native completion and a stopped managed container. Do not start it or provision sandbox here. |
| list | Query structured local instance data | lxc list local: --format=json | Filter to owned containers and sort by name. No mutation. |
| info | Validate TARGET; query structured instance data | Same list query, not a separate lxc info call | Find target, reject absent/unowned instance and return its complete record. CLI/menu formats JSON. |
| start | Require owned target; allow Stopped or Running only | Stopped: lxc start local:TARGET; then lxc exec runs USER_SETUP | Wait Running before setup. Already Running skips native start but still runs USER_SETUP. Wait for setup command completion and Running afterward. |
| stop | Require owned target; allow Running or Stopped only | Running: lxc stop local:TARGET --timeout TIMEOUT | Wait Stopped. Already Stopped returns success with zero elapsed and issues no stop command. |
| stop --all | Get sorted owned list | Call shared stop for each target | Continue after individual Error exceptions; aggregate failures and report them after attempting the list. |
| delete | Require owned, stopped target; confirm; recheck ownership and stopped state after confirmation | lxc delete local:TARGET | Wait for native completion and confirmed absence. Decline causes no mutation. |
| import | Require absent TARGET; expand '~' and make FILE absolute; require a file | lxc import local: FILE TARGET | First wait for native completion and Stopped without requiring a marker. Reject non-container result and leave it unmanaged. Then lxc config set local:TARGET user.mas.managed=true and wait for stopped managed result. Marking failure is reported; no rollback/deletion is invented. |
| export | Require owned, stopped target; expand '~' and make FILE absolute; confirm existing destination overwrite; reject confirmed symlink/nonregular destinations; recheck ownership/state; require existing parent directory | Create a temporary directory in the destination's parent; lxc export local:TARGET TEMP/backup.tar.gz | Wait native completion and Stopped; open archive and require backup/index.yaml. Existing file: os.replace; initially absent file: os.link, so a concurrently created destination is not overwritten. Clean temporary directory on success or failure. Archive/metadata/native/publication failures preserve an existing destination. This is metadata/readability validation, not a new archive format or a claim to inspect every restored file. |
| enter | Require owned target; always invoke shared start, including its setup on already Running targets | lxc exec local:TARGET -- su --login sandbox | On normal subprocess return, call shared on_exit; afterward report a nonzero shell return code. No duplicated native start logic. |
| on_exit | Ask whether to stop; default No | If confirmed, call shared stop | Otherwise leave running. No mas exit command. |

## USER_SETUP inside start

In order:

1. If cloud-init exists, wait for it; accept exit 0 or 2.
2. If sudo is missing, apt-get update and install sudo noninteractively inside the container.
3. If sandbox is absent, create it with a home directory and /bin/bash. Preserve an existing account's UID, home and configured shell; reject UID 0.
4. Ensure /etc/sudoers.d exists with mode 0750. With umask 077, write the temporary rule `sandbox ALL=(ALL:ALL) NOPASSWD: ALL`.
5. Validate with visudo, set rule mode 0440 and move it to /etc/sudoers.d/90-mas-sandbox, replacing the mas-owned rule.
6. Verify passwordless sudo through sandbox's login session using sudo -n /usr/bin/true.

Root's password is not set to empty. The ownership marker and this user/sudo preparation are the only mas-specific container configuration. No GPU mapping, host-directory sharing, network policy, port forwarding or custom profile is added. Fresh-host storage/network initialization, LXD installation, sudo authentication and host PATH setup belong to mas/install.py, not to container operation hooks.


## Filesystem extension (0.1.9–0.1.10)

Manager delegates all three commands to one per-user Filesystems implementation. mountfs verifies ownership, resolves/validates the container directory through native LXD file APIs, locks mount records, rejects overlap and existing host destinations, creates tracked host directories, starts the native authenticated loopback listener and SSHFS, then checks the actual mount table and live helpers. unmountfs selects an exact recorded path, verifies mount identity, uses fusermount3, waits for disappearance, terminates identity-matched helpers and removes only tracked empty directories/private connection files. The SSH known-hosts path is explicitly quoted and absolute inside private per-mount state. mountedfs reconciles records with mount table and helper identity without mounting or changing container state.

Lifecycle transition/delete preconditions refuse this user's recorded mounts before native state changes. No start/stop hook mounts or unmounts automatically. Permissions/UID/GID/ACLs in the container are not rewritten; native new-file semantics apply. The registry is private under XDG_STATE_HOME and separate from the LXD container ownership marker.

The same private registry lock spans mount creation and native start-from-Stopped, stop-from-Running, and deletion; ownership/state is rechecked inside the lock. Locks coordinate this user only. A repeated start of an already-running target retains user setup; stopped stop remains a no-op.

Registry reads validate paths, directory identities, process tokens and required field types. New directory identities use filesystem ID/inode/owner; legacy device/inode records are compared conservatively. Helpers are checked against process start/boot identity and per-mount native command arguments. Exact owned helper arguments allow recovery when interrupted before PID publication. Only a verified helper may be signalled. Final unmount success follows detach, helper exit and directory/private-file cleanup, including total elapsed time. A native timeout preserves records for retry.
