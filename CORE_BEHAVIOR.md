# Container operation behavior

This is an inventory of the additional behavior implemented in mas/core.py as of test batch 0.2.1. Phase 1 stable remains the unchanged 0.1.15 release. CLI and text menus call the same Manager. Installation is separate from these operations.

## Shared execution and validation

- Locate lxc using PATH, then /snap/bin/lxc; fail with a setup instruction if absent. Use the local server and explicit project (default for the product; isolated project for tests).
- Require an operation timeout of at least 300 seconds; default 600. Queries capture output, reject timeout/nonzero exit, and retain native stderr. Instance queries use lxc list local: --format=json, parse JSON and validate list/row structure. Query failure or malformed data never means target absence.
- TARGET accepts 1–63 ASCII letters/digits/hyphens, starts with a letter and ends with an alphanumeric character. Reject remote, snapshot and option-like selectors.
- An owned instance must have type container and instance-local config user.mas.managed exactly equal to true as a string. An inherited profile marker is insufficient. Existing-container operations require ownership; host-only recovery of existing filesystem records does not query or mutate a replacement container; new/import name collisions inspect all instances.
- Mutating _run_lxd_until_state calls capture native stdout/stderr in temporary files to avoid pipe backpressure. Observe structured state every second, require both native exit zero and expected state, and normally require the ownership marker. Native nonzero exit, LXD Error state and query failures abort. Report observations, elapsed time, final result and native output.
- On timeout/failure/interruption, stop a still-running client process and wait for it; do not claim the LXD daemon operation has been cancelled. Timeout messages include the last observed state; the final event includes elapsed time. Interactive container shells do not use this operation timer.
- Confirmation policy is shared, with the presentation callback injected by each entry point; no callback means decline. The terminal radio menu defaults No, --yes/--no supply explicit decisions, noninteractive input without consent declines. CLI/menu presentation localizes mas text and preserves original external output.

CLI and text-menu waiting events share the tester's terminal-line renderer: normal progress refreshes in place, final results and diagnostics remain, and redirected output omits waiting ticks. Successful query stderr uses a permanent-output callback in the product so it cannot be erased by subsequent progress. Structured event records remain complete. This presentation change does not change operation completion criteria.

## Operation inventory

| Operation | Before native execution | Native execution | After / alternate branch |
| --- | --- | --- | --- |
| new | Validate TARGET; reject any existing name; choose ubuntu:<host VERSION_ID> from Ubuntu /etc/os-release unless overridden; reject an image starting with '-' | lxc init IMAGE local:TARGET -c user.mas.managed=true | Wait for native completion and a stopped managed container, then reuse the GPU module to configure default access when supported. Do not start it or provision sandbox here. |
| list | Query structured local instance data | lxc list local: --format=json | Filter to owned containers and sort by name. No mutation. |
| info | Validate TARGET; query structured instance data | Same list query, not a separate lxc info call | Find target, reject absent/unowned instance and return its complete record. CLI/menu formats JSON. |
| start | Require owned target; allow Stopped or Running only; before a real transition sequentially call shared unmountfs for recorded paths; before start also reuse GPU.ensure | Stopped: lxc start local:TARGET; then lxc exec runs USER_SETUP | Wait Running before setup. Already Running skips native start but still runs USER_SETUP. GPU.prepare performs required internal runtime preparation for recorded WSL GPU settings; its failure prevents complete start success and mount restoration. Wait for setup command completion and Running afterward; after a real transition restore captured mounts through shared mountfs. |
| stop | Require owned target; allow Running or Stopped only; before a real transition sequentially call shared unmountfs for recorded paths; before start also reuse GPU.ensure | Running: lxc stop local:TARGET --timeout TIMEOUT | Wait Stopped and restore captured mounts through shared mountfs. Already Stopped returns success with negligible elapsed and issues no stop command. |
| stop --all | Get sorted owned list | Call shared stop for each target | Continue after individual Error/OSError exceptions; aggregate failures and report them after attempting the list. |
| delete | Require owned, stopped target; confirm; recheck ownership and stopped state after confirmation | lxc delete local:TARGET | Wait for native completion and confirmed absence. Decline causes no mutation. |
| import | Require absent TARGET; expand '~' and make FILE absolute; require a file | lxc import local: FILE TARGET | First wait for native completion and Stopped without requiring a marker. Reject non-container result and leave it unmanaged. Then lxc config set local:TARGET user.mas.managed=true and wait for stopped managed result. Marking failure is reported; no rollback/deletion is invented. |
| export | Require owned, stopped target; expand '~' and make FILE absolute; confirm existing destination overwrite; reject confirmed symlink/nonregular destinations; recheck ownership/state; require existing parent directory | Create a temporary directory in the destination's parent; lxc export local:TARGET TEMP/backup.tar.gz | Wait native completion and Stopped; open archive and require backup/index.yaml. Existing file: os.replace; initially absent file: os.link, so a concurrently created destination is not overwritten. Clean temporary directory on success or failure. Archive/metadata/native/publication failures preserve an existing destination. This is metadata/readability validation, not a new archive format or a claim to inspect every restored file. |
| enter | Require owned target; always invoke shared start, including its setup on already Running targets | lxc exec local:TARGET -- su --login sandbox | On normal subprocess return, call shared on_exit; afterward report a nonzero shell return code. If on_exit also fails, retain both errors. Then finish the mas invocation and return to the host shell, even for post-shell errors. No duplicated native start logic. |
| on_exit | Ask whether to stop; default No | If confirmed, call shared stop | Otherwise leave running. No mas exit command. |

## USER_SETUP inside start

In order:

1. If cloud-init exists, wait for it; accept exit 0 or 2.
2. If sudo is missing, apt-get update and install sudo noninteractively inside the container.
3. If sandbox is absent, create it with a home directory and /bin/bash. Preserve an existing account's UID, home and configured shell; reject UID 0.
4. Ensure /etc/sudoers.d exists with mode 0750. With umask 077, write the temporary rule `sandbox ALL=(ALL:ALL) NOPASSWD: ALL`.
5. Validate with visudo, set rule mode 0440 and move it to /etc/sudoers.d/90-mas-sandbox, replacing the mas-owned rule.
6. Verify passwordless sudo through sandbox's login session using sudo -n /usr/bin/true.

Root's password is not set to empty. The ownership marker, user/sudo preparation and the independently managed GPU resources below are mas-specific container configuration. GPU driver mappings are read-only; general host-directory sharing, network policy, port forwarding and custom profiles are not added. Fresh-host storage/network initialization, LXD installation, sudo authentication and host PATH setup belong to mas/install.py, not to container operation hooks.


## Filesystem extension (0.1.9–0.1.12)

Manager delegates all three commands to one per-user Filesystems implementation. mountfs verifies ownership, resolves/validates the container directory through native LXD file APIs, locks mount records, rejects overlap and existing host destinations, creates tracked host directories, starts the native authenticated loopback listener and SSHFS, then checks the actual mount table and live helpers. unmountfs selects an exact recorded path, verifies mount identity, uses fusermount3, waits for disappearance, terminates identity-matched helpers and removes only tracked empty directories/private connection files. The SSH known-hosts path is explicitly quoted and absolute inside private per-mount state. mountedfs reconciles records with mount table and helper identity without mounting or changing container state.

Delete refuses this user's recorded mounts. Real start/stop transitions snapshot records and sequentially invoke the existing single-path unmountfs before native execution, then mountfs after success. The first unmount failure aborts the sequence and native transition, reporting completed/failed/pending paths without rollback. Native transition or user-setup failure propagates unchanged; the restoration suffix is naturally not executed. Restoration attempts every captured path, preserving its exact directory and default-home tag; failures are aggregated with container/host paths and the completed state. No separate batch mount implementation or caller-owned cleanup is added. Permissions/UID/GID/ACLs in the container are not rewritten; native new-file semantics apply. The registry is private under XDG_STATE_HOME and separate from the LXD container ownership marker.

The same private registry lock spans mount creation and native start-from-Stopped, stop-from-Running, and deletion; ownership/state is rechecked inside the lock. The cached Filesystems object provides a reentrant lock so nested foundational calls reload the committed registry without dropping the outer cross-process lock. Locks coordinate this user only. A repeated start of an already-running target retains user setup; stopped stop remains a no-op.

Registry reads validate paths, directory identities, process tokens and required field types. New directory identities use filesystem ID/inode/owner; legacy device/inode records are compared conservatively. Helpers are checked against process start/boot identity and per-mount native command arguments. Exact owned helper arguments allow recovery when interrupted before PID publication. Only a verified helper may be signalled. Final unmount success follows detach, helper exit and directory/private-file cleanup, including total elapsed time. A native timeout preserves records for retry.

## 0.1.11 host access and presentation

New SSHFS processes use allow_root. The installer enables the host FUSE user_allow_other gate when absent; mountfs checks that prerequisite for non-root callers before creating resources. The mount permits the mounting user and host root, not arbitrary ordinary users. No container permission/ownership mapping is added. Existing mounts keep their original options until explicitly unmounted and remounted.

UI.present provides a blank-line/title entry and a dedicated result/Back step for operation success, cancellation and error. Navigation sections retain their own menus. The parent is redrawn only after return, preserving its selection. The exception is an entered container terminal: after shared on_exit finishes or fails, the invocation ends at the host shell without another menu/result page. Pre-entry errors retain the ordinary result page. Shared output boundaries add one blank line before first operation output after a title/input; native diagnostics remain consecutive. Shared selection rows left-align display-width-aware columns, preserve status colors/text, and use one column structure per list. Unmount omits a duplicate table and shows a status column for every row only when abnormalities require it. Input wording identifies the requested value and default; long input instructions wrap within the inline block. Shared Selection.move wraps in both directions without changing checked values. These presentation changes do not duplicate or change Manager lifecycle operations.

The pre-Python bootstrap and independent installer use mas/dependencies.sh for missing-package detection, a single APT refresh, grouped installation and APT presentation. It preserves native prompts and diagnostics, including prompts without a newline. The Python installer loads the same packaged resource; the generated shell entry embeds it. Product archives exclude it. Snap retains native progress. No standalone sudo -v, password storage or keepalive is used.


## Responsibility boundaries in 0.1.14

Stages follow responsibility, not the ordering of native commands or whether code runs inside the container. Internal mas work includes required validation, native execution, successful and failed branches, completion verification and cleanup of owned resources. An external pre/post stage coordinates another foundation. Empty stages and a generic hook framework are deliberately absent.

| Function | Internal responsibility | External coordination |
| --- | --- | --- |
| new | Name/image validation, native init, managed/stopped verification | None |
| list / info | Structured query, schema validation, ownership filtering/lookup, sorting for list | None; result formatting belongs to presentation |
| start | State validation, native start when needed, Running verification, sandbox preparation and passwordless-sudo verification | `_before_lifecycle` unmounts recorded paths; `_after_lifecycle` restores them only after `_execute_lifecycle` succeeds |
| stop | State validation, native stop when needed, Stopped verification | Same shared pre/post sequence as start |
| delete | Confirmation, deletion-only no-mount guard, locked ownership/state recheck, native delete, absence verification | None; deletion does not orchestrate mounts |
| import | Name/file validation, native import, stopped/container check, ownership marking and verification | None; marking is required internal completion |
| export | State/path/consent validation, native export, archive metadata validation, final file publication, temporary-file cleanup | None; publication and cleanup are internal, despite acting on host files |
| mountfs | Validate path/ownership/dependencies, journal and create owned resources, launch listener, observe readiness, launch SSHFS, observe mount, publish identity; clean failed attempts | None |
| unmountfs | Select exact record, verify identities, detach/wait, terminate owned helpers, reclaim tracked paths/private files, save removed record | None |
| mountedfs | Reconcile stored entries with mount/process observations; preserve recovery-only access without querying replacement containers | None |
| enter / on_exit / stop-all | Compose existing foundations; enter owns interactive-shell lifetime, on_exit owns the stop decision, stop-all aggregates target-specific Error/OSError failures | Inherit lifecycle coordination exclusively through start/stop |
| config | Validate and atomically save preferences; clean its temporary file | No lifecycle stages |
| installation | Detect/prepare dependencies and access, preserve existing LXD setup, atomically install artifacts, configure PATH | Its own installation lifetime; no container lifecycle hooks |

`_lifecycle` retains one registry lock over external pre-processing, full internal execution and external post-processing. Lock acquisition is followed by an ownership/state recheck. An already-satisfied state skips external mount coordination; Running start still prepares sandbox. Internal failure propagates unchanged and never calls external post-processing. Required user preparation is part of mas start, not its external post-stage. Partial restoration failures identify every failed path and state that the internal start/stop completed.

`_run_lxd_until_state` emits native-scoped events. Their success means only the native step completed with its structured postcondition. Function-scoped success follows required internal work. Native success and waiting are transient in interactive output and omitted when redirected; function completion and native diagnostics remain. The test log retains structured events. `mas/presentation.py` supplies shared progress, info and filesystem-list formatting; menus no longer import CLI. Core operations no longer import the terminal menu for confirmation.

Mount preparation is inside failure protection from its first journal write. `_listener_details` and `_mount_observation` only observe; process launches and registry writes live in their named steps. Listener and mount readiness consume one shared deadline after listener launch. New registry records include a boolean `work_created` to distinguish successfully created private work directories from a pre-existing collision; legacy records remain accepted. Cleanup refuses a pre-existing work directory and retains the recovery record when it cannot safely finish. Explicit unmount and failed mount recovery use the same cleanup implementation.

Shared `cleanup_scope` preserves an original failure when cleanup also fails and reports the secondary failure where output remains possible. A cleanup failure on an otherwise successful path still fails the operation. Reporting callbacks are observers: their failures produce best-effort diagnostics without replacing the operation result/error. Interrupts are not converted into successful outcomes. Native client cleanup, export temporary directories, registry/config temporary files and installer temporary files reuse this policy; no lifecycle rollback, extra failure-state query or automatic failure recovery was added.


## 0.1.15 installation and navigation

The common Bash dependency helper now runs its APT/tee/renderer pipeline inside the command invoked by sudo, leaving sudo itself attached to the interactive terminal so its foreground process setup precedes APT child reads. No separate authentication command, password handling, sudoers edit or alternate sudo implementation is introduced. Redirected output supplies noninteractive EOF to the package manager; sudo retains responsibility for any authentication via its controlling terminal. Failures preserve the native output and exit status. APT fragments remain buffered across timed reads and carriage-return boundaries; known normal prefixes stay transient, while unknown prompts can be displayed before a newline and warnings/errors remain permanent.

Bare mas directly opens my-ai-sandbox with list, new, import, mas preferences and exit. Chinese preferences is mas 选项; English is mas Preferences. Per-container actions remain behind container selection. Stop all containers is a non-container control on the selection page, placed before Back and shown only for more than one managed container with at least one state other than exact Stopped. Live LXD state is authoritative, including native lxc changes; query errors are not treated as empty or all stopped. The menu calls unchanged Manager.stop_all, then reloads the list. Already-stopped requests do not repair independent filesystem issues. Future host/per-container settings are placement conventions only, not new features.

Deletion continues to require explicit unmount/cleanup. Its bilingual instruction now refers only to deletion; it no longer incorrectly includes start/stop.


## GPU module — current through 0.2.3

`Manager.hardware` is the shared CLI/menu entry to `mas/gpu.py`. `GPU.status`, `GPU.set`, `GPU.ensure` and `GPU.prepare` separate queries, stopped-container resource configuration, default/driver refresh orchestration, and required internal runtime preparation. GPU configuration shares the lifecycle/filesystem lock. Configuration and exact ownership metadata are published in one native LXD config edit; structured readback must match before success. Disabling verifies removal of the owned loader file, then removes owned devices and saves explicit off. Native errors preserve actionable state rather than publishing success.

WSL NVIDIA uses an owned unix-char `/dev/dxg` (container mode 0666), read-only `/usr/lib/wsl/lib`, and read-only active driver-store directories selected by the LXD-bundled NVIDIA tool in WSL mode. Production discovery does not scan candidate directories. The complete driver-store parent is not shared. Runtime files are fixed-content `/etc/ld.so.conf.d/mas-gpu.conf` and `/etc/profile.d/mas-gpu.sh`; the latter adds `/usr/lib/wsl/lib` to login-shell PATH. Both are checked before writes/removal, and disabled GPU removes both owned files. `ldconfig` runs inside the container. Existing 0.2.5 records acquire the profile inventory on the next stopped start. Native file pull preserves type so symlinks are rejected without following them on the host. Foreign content and conflicting or modified devices are refused. Empty native mount-point directories or stale linker-cache references are not GPU access; the next start refreshes the cache. No arbitrary container data is removed and no host package/driver is installed.

The current detector supports NVIDIA; native Ubuntu uses LXD's nvidia.com/gpu=all CDI device and remains unverified on native hardware. LXD automatic CDI previously failed NVML discovery on the measured snap, so WSL explicitly uses the native device path above, not automatic fallback after partially modifying a container. A missing supported GPU hides the menu switch; actual discovery errors remain errors. Closing recorded access remains possible through CLI even if discovery is broken. The module does not implement the pending project/profile hardening.

Before a real start with GPU enabled, official WSL discovery generates JSON to stdout; mas validates selected CUDA source paths and reuses GPU.set to refresh changed mappings. Returned hooks are never executed and the CDI document is never applied. Missing tools, failed or invalid discovery have no scanning/cached fallback and prevent startup. The disabled path and owned cleanup remain independent of discovery. Running mappings are not refreshed. Native diagnostics are retained except informational discovery logs.

## Diagnostic and GPU integration — 0.2.4

Native GPU/LXD diagnostics share a callback-aware emitter and the current permanent-output renderer; they do not bypass active progress via direct stderr printing. The tester records direct diagnostics and product-query events, rendering captured CLI warnings once and PTY query events once. Hardware-menu cancellations retain the current snapshot; mutation attempts refresh it. Resource discovery before actual starts remains uncached.

The WSL query disables unused hooks and nvsandboxutils discovery using official flags and resolves compatibility hook paths to the existing tool. It still only reads resource JSON. Remaining warnings are not filtered out. Driver path syntax and loader file content are shared definitions; malformed ownership versions and malformed collection/option types are rejected.

0.2.6 passes `--library-search-path=/usr/lib/wsl/lib` to the WSL discovery command. Only a recognized multiple-driver-store-path warning is omitted after successful product discovery and validation; tester contexts explicitly retain it. All other warnings and failure diagnostics remain visible. Independent test observation loads the host CUDA driver and reads /proc/self/maps, comparing the loaded driver directory with container mappings. No timestamps/version-name guessing is used.
