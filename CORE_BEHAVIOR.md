# Current shared behavior — 0.2.25

The accepted product is identical in test v0.2.25 and stable/0.2.25. CLI/menu call the same Manager. This describes current behavior; historical responsibility tables and superseded proposals are in [the behavior archive](docs/history/CORE_BEHAVIOR_0_2_25.md). Source-module ownership is mapped in [DEVELOPMENT.md](docs/DEVELOPMENT.md#source-map).

## Operation inventory

| Foundation/composition | Preconditions and completion | Shared coordination |
| --- | --- | --- |
| new | Validate name/image, no collision, fixed policy; native init with managed marker/cloud-init, default supported GPU, standard start, verify 25 APT packages/user/venv/Node, retire payload, standard stop; final Stopped required. Failed preparation retains guest data and attempts original-target stop. | Composes start/stop; no provisioning on later lifecycle/import. |
| list / info | Validate structured local records, instance-local ownership, container type; sorted list/exact lookup; malformed queries never mean empty. | Presentation uses one queried record; info summary/complete JSON does not trigger new discovery. |
| start | Owned Running/Stopped; policy/GPU validation before a real start, then native Running and complete sandbox/GPU runtime preparation. Already Running still prepares sandbox. | Real transition unmounts exact recorded paths before internal work and restores after complete success. |
| stop | Owned Running/Stopped; native stop and Stopped; already Stopped is a no-op. | Same lock/pre/post path composition for real transitions. |
| restart | Standard stop must succeed, then start or enter. | Each foundation keeps its full mount phases; restart-enter prepares only through enter's start. |
| delete | Explicit default-No consent, Stopped, no recorded mounts, locked ownership/state recheck, native deletion and absence. | Does not detach mounts automatically. |
| export | Stopped; validate host destination/consent, native backup, valid archive metadata, safe final publication. | Owned temporary cleanup is mandatory internal work. Concurrent new destinations and foreign symlinks are not overwritten. |
| import | Stage in a unique temporary Project, import/audit while stopped, mark ownership only after validation, restore into target Project/profile, verify completion. | Original archive untouched. Preserve failed imported data for manual handling; clean empty staging only after native absence verification. |
| migrate | Legacy owned default-project source, Stopped, no recorded mounts or name collision, compatible policy/devices, explicit consent. | Native move preserves data/safe inherited config, records approved baseline; preflight refusal preserves source. No invented rollback after daemon-side uncertainty. |
| mountfs | Lock, exact guest directory validation, no path overlap/host collision, owned directory journal, authenticated native LXD listener, SSHFS and real mount/access/helper verification. | One-path foundation; container can be running or stopped. |
| unmountfs | Exact recorded path or explicit selection, identity-matched detach/wait, owned helper termination, empty tracked/private-data cleanup, registry publication. | Same cleanup handles failed attempts; unsafe residual resources remain recorded for recovery. |
| mountedfs | Reconcile mount/helper identity and journal. | Recovery listing can work without adopting/querying a replacement instance; legacy switch only selects old registry scope. |
| enter / on_exit | Complete standard start, sandbox login shell, explicit stop/restart/menu/exit for any shell code. | Own interactive-shell lifetime; chosen menu return skips result page and retains Enter focus; nonzero status remains. |
| stop-all | Sorted owned list, standard stop for each, aggregate failures. | Never stop unmanaged objects; tests use isolated Projects. |
| hardware | Query or stopped-UUID guarded GPU/network change, exact owned metadata/device audit, valid ETag update/readback. | Uses the lifecycle/filesystem lock; no implicit stop or full security challenge. |
| config / About | Atomic shared preferences or running numeric version; no backend query. | Shared controls/catalogs; Back retains parent focus. |

## Completion and identity

Local LXD operations always name the selected Project explicitly; production uses mas, tests unique owned Projects, legacy access default only through explicit paths. TARGET is a local valid name. Ownership is an instance-local `user.mas.managed=true` marker and type container, not inherited metadata.

Queries retain native errors and validate JSON/schema. Mutations stream to owned temporary files to avoid pipe blockage, check actual state every second and after completion, and require both process exit zero and the final postcondition. Default timeout 600/minimum 300 applies per operation; terminal shell has no operation timer. Client termination does not cancel daemon work by assertion. Report native-step completion separately from full internal success.

Policy, ETag and original UUID guards reject drift, stale updates and same-name replacement. A matching GPU record on a replacement is not the original identity. Native/primary failures remain actionable; separate cleanup/restoration errors are retained. Reporting callbacks are observers and cannot replace an operation outcome. No generic automatic repair, retries or rollback was added.

## Lifecycle and filesystem ownership

The per-user reentrant registry lock spans unmount → complete internal start/stop → restoration. First pre-unmount failure aborts; restoration attempts each captured path and aggregates failures. Already-satisfied native state skips external mount coordination. Startup user/GPU preparation belongs inside the operation, so its failure prevents restoration.

Filesystem paths map guest directories under `~/LXDCMFS/TARGET`, with private state under XDG_STATE_HOME. Absolute/non-symlink guest directories only, no overlapping mounts or existing/replaced host destinations. Native LXD file mount provides root-authenticated loopback SFTP; SSHFS uses quoted private known_hosts and allow_root. User/group/mode/ACL semantics are preserved.

Journal identities include instance UUID, mount/source/device, directories and process PID/start/boot. Never remove replaced/nonempty/pre-existing directories or terminate an unrelated/reused PID. Early attempt creation is cleanup-protected; an unverified residual record is retained. Delete requires explicit cleanup. Host-user locks are not global administrator locks.

## Preparation and resources

Native cloud-init installs exactly the 25 APT packages listed in REQUIREMENTS.md, including nodejs/npm. New verifies sandbox commands, venv/pip and `/var/lib/mas/development.json`, then conditionally removes provisioning payload before final stop. Later lifecycle/import does not reinstall removed packages. USER_SETUP preserves existing UID, home, login shell and data; prepared missing sudo is explicit failure, while compatible unprepared containers retain old setup behavior. No empty guest-root password or host sudoers change.

Fixed project/profile policy, absence rules, approved storage/network and exact GPU definitions are audited from expanded configuration. Startup refuses drift; safe stop/list/recovery remain usable. Import uses disposable staging because restricted Projects reject some native backup operations during intermediate restoration; rejected imported data is not automatically erased. Root/PID/mount/network boundaries and actual seccomp are measured, not inferred from startup alone.

WSL NVIDIA uses `/dev/dxg` plus readonly `/usr/lib/wsl/lib` and active exact driver directories discovered by the LXD-bundled nvidia-ctk. Do not scan the driver store, apply returned CDI documents/hooks or refresh running mappings. Native NVIDIA uses `nvidia.com/gpu=all` CDI, separately unverified. Runtime preparation owns `/etc/ld.so.conf.d/mas-gpu.conf` and `/etc/profile.d/mas-gpu.sh`, checks foreign contents and refreshes ldconfig; disable removes only the exact owned resources. DXG is not per-card isolation.

Network off overrides approved inherited eth0 with `type=none`; on restores the exact approved NIC/MAC. Records, UUID, stopped state, ETag and devices are guarded. IPv4/IPv6 external routes disappear, loopback and host LXD/SFTP management remain. No bridge/profile/firewall/other-container rule changes.

## Shared interface and output

Main menu: Containers, New, Import, Migrate legacy version containers, mas Preferences, Exit. Container list embeds Stop all before Back only for more than one owned container when some state is not exact Stopped. Selected-container page: Info, Start, Enter, Stop, Restart, Export, Delete, Filesystem, Hardware, Back. Filesystem groups list/mount/unmount; Hardware offers GPU where supported and Network; Preferences is Language, About, Back. Info provides summary and complete config using one record.

About uses view.choose with mas.__version__ and one Back choice, no network/LXD operation. Enter/Right or Escape/Left returns with About selected, then Preferences focus on main. Ordinary action results/errors/cancellation remain before Back; post-terminal destinations bypass this page.

Shared Screen parks its cursor at the active region's first row, clears visible remainder from that anchor and draws one bounded block. Titles/permanent output and native scrollback survive. Input, checked values and focus survive resize; mode/cursor restore on all exits. Extreme contraction can shift old activity into native scrollback; it is preserved history. The minimal Bash language fallback has explicit supported-size limits.

Shared output owns terminal dimensions, display cells, semantic foregrounds and transient progress. Native first-boot output is sampled every 50 ms independently of one-second state queries; latest output replaces fallback on one physical row and unchanged text is not redrawn. Permanent diagnostics clear activity first. Queries use scoped waiting on stderr so JSON stdout stays clean. Redirections have no cursor escapes/ticks. APT prompts/errors/warnings remain native; Bash before Python handles only known ASCII progress, not a second Unicode renderer. Snap uses its native progress.

Host installation is its own lifetime: grouped missing dependencies, ordinary sudo, persistent socket/group/FUSE setup, conditional LXD initialization, atomic artifact and PATH updates. Installer does not orchestrate tests; tester calls it. Exact stable/test routing and archive exclusions are in DEVELOPMENT.md.
