# Accepted design decisions

This records current outcomes and why later work must preserve them. Original approvals and chronology remain in docs/history; a pending decision is not approval to implement it.

| Decision | Accepted outcome and consequence |
| --- | --- |
| Shared foundations | CLI/menu/test compose one Manager and one filesystem/GPU/network/policy implementation. Correct the owning shared component, not each consumer independently. |
| Completion | A native successful command is only an intermediate result. Require state, user/runtime preparation, identity/readback and applicable restoration before complete success. |
| Ownership | Dedicated mas Project, instance-local marker and exact resource metadata. Same name/record does not equal original UUID. Host admins remain trusted, not confined by the marker. |
| Lifecycle mounts | Per-user journal lock; standard single-path unmount/mount around real transitions. No caller-owned bulk algorithm, implicit delete detach, automatic rollback or generic hook framework. |
| Backups/import | Restoration preserves native MAC identity. Staged import solves restricted-Project intermediate compatibility; rejected imported data is retained, not silently deleted or turned into a clone. |
| Guest administration | sandbox has native passwordless sudo; root remains usable inside an unprivileged container. Guest workloads are not filtered and host sudo is ordinary system authentication. |
| Development packages | Exactly 25 Ubuntu APT packages, including nodejs/npm. Official-Node latest-LTS download was explicitly replaced in 0.2.21. New-only provisioning retires its payload; later lifecycle/import preserves user software. |
| GPU | WSL NVIDIA uses official active discovery and exact readonly resource mappings because measured snap CDI automatic discovery failed. No broad driver-store scan/fallback, host driver install, hook execution or per-card DXG claim. |
| Network | Per-container NIC on/off without touching bridge/profile/guest firewall. Traffic/login/port policy is separate and pending. Offline host management uses LXD, not a newly added network service. |
| devlxd/AppArmor | Keep instance API for cloud-init while volume management is disabled. Record actual AppArmor availability; do not enable it or claim protection when WSL reports disabled. |
| Inline UI | Preserve terminal history; one active region and shared display-width/output policy. Extremes may move old activity to native scrollback. Bash remains a limited pre-Python dependency adapter. |
| About | Existing shared selection page, running __version__, one Back, retained focus and no remote/backend lookup or extra result page. |
| Terminal exit | Four choices with default Exit, independent of shell return code. Restart→host is current; restart-entry refinement remains pending. CLI restart --enter is already delivered. |
| Security testing | One host-assisted full challenge after all functional stages on a fresh temporary container; independent host entry reuses it and restores initial state. No guest/public second implementation. |
| Versions/releases | Product submission batches increment phase batch once; docs and stable promotion do not. a remains 0 until user says otherwise. Immutable test assets, separately accepted stable promotion and exact same-version pairing. |
| Stable branch | Product/installer/shared-build sources and product docs only. Advance by stable publications, preserve old release history/tags and do not merge main's tests/handoff archive. |
| Project guidance | Root AGENTS.md explicitly applies docs/CODE_PRINCIPLE.md and docs/CLI_TUI_GUIDELINES.md. All three are project-owned files; restoring the repository does not write Codex global instructions or configuration. |
| Handoff | Full selected Git history, portable instructions and immutable baseline manifest. Publish archive on main; subsequent receipt/archive upload commits can be fetched without changing the frozen snapshot. |
| Corrected handoff | Retain the first archive already committed to main via explicit --include-prior-archives and record its blob/hash/size. Do not filter history or include this generation's upload in its own baseline. Future distribution-policy changes still require discussion. |

Current pending choices and required confirmations are complete in [REQUIREMENTS.md](../REQUIREMENTS.md#pending-decisions). Measured platform limits are in [TEST_COVERAGE.md](../TEST_COVERAGE.md#current-measured-limits).
