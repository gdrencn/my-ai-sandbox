# Phase 1 stable audit: 0.1.15

Promotion review of the unchanged product from test tag v0.1.15 (source 634e37e0feddb8b97740d1c2b71e98ecc9548c46). Stable channel tag: stable/0.1.15. Final execution/publication results are recorded in IMPLEMENTED.md after verification.

## Reviewed responsibilities

| Area | Review finding | Existing verification |
| --- | --- | --- |
| Ownership and targets | Local instance marker and container type gate operations; collisions include unmanaged instances; query failure is never absence. | Native isolation/missing-target cases and schema/marker units. |
| Basic operations | Creation remains stopped; import requires absence and establishes the marker after native success; delete/export require stopped state and consent. | CLI/menu lifecycle, native backup round trip, unmarked import and failure injection. |
| Start/stop phases | External unmount coordination surrounds the full internal operation. User preparation belongs inside start; internal failure skips restoration. Restoration attempts remaining paths and names failures. | Native multi-path/root restoration and ordered-call/failure-boundary units. |
| Bulk stop | Iterates shared single-target stop and aggregates target failures; menu eligibility follows actual LXD state. | Native isolation/menu and continued-error unit checks. |
| Waiting | Structured state plus native completion are required; native failure terminates promptly, polling is one second and default timeout is 600 seconds. | Native elapsed events and simulated timeout/query/error/interruption units. |
| Filesystems | Native LXD SFTP plus SSHFS; exact-path unmount, overlap/collision checks, persisted identities and shared cleanup. Recovery does not adopt unmanaged containers. | Native running/stopped access, metadata, Windows UNC, failure recovery and registry/PID/lock units. |
| Entry and menus | CLI/menu share foundations; confirmations are injected; entered-shell completion returns to the host terminal. Menu rows and progress use shared presentation. | Native PTY workflows, both languages, result boundaries, cancellation, circular navigation and shell errors. |
| Dependencies/install | One shared Bash dependency flow; native sudo authentication; the APT pipeline runs inside the sudo command; existing LXD configuration is retained. | Same-user real sudo terminal probe, isolated-container privileged APT installation, installer fixtures and pinned public installation. |
| Packaging/release | Published archives match local archives and included source. Product and installer exclude tester code. Stable preserves these bytes and the same-version test release. | SHA-256, archive inspection, Python 3.10 grammar and shell syntax. |
| Test safety | Integration resources are scoped to an isolated LXD project and random test targets. Reports distinguish failures, not-run cases and cleanup errors. | Native suite cleanup plus independent registry/project/mount verification. |

No product-code change or additional prerequisite for phase 1 promotion was identified in this review. No claim of exhaustive branch coverage or absence of all future defects is made.

## Boundaries retained

- Native Ubuntu/cloud hosts, other CPU architectures and offline WSL VHDX access have not been verified by this review. Current live verification is Ubuntu 26.04 WSL with LXD 6.9.
- The user's fresh-host 0.1.15 log confirms dependency, FUSE, snap/LXD initialization and installation completion. That run subsequently failed on a remote HTTPS connection reset while obtaining the first image; its later tests were not run. It is not recorded as a passed full suite. The reset's remote/network cause is undetermined.
- Failure injection covers unsafe-to-provoke branches; it does not establish live disk-exhaustion, daemon-outage or every terminal implementation behavior.
- GPU access, host resource allowlists, additional LXD security policy and general package presets remain outside phase 1. The existing LXD default profile and native permission behavior are retained.
- Stable installation pins --release v0.1.15 to the matching numeric release. The unpinned existing entry intentionally remains latest test. This release does not implement a new channel-selection API.


## Final outcome

162 units and all 21 report stages passed in 394.0 seconds; no skips or cleanup errors. Windows UNC passed and independent resource-reclamation checks passed. Pinned public installation passed. Stable published as GitHub latest with exactly product, installer and checksums; downloaded assets match the unchanged test binaries. Original test prerelease assets and metadata remain unchanged. The unpinned latest-test and pinned numeric resolvers still work. Detailed evidence is retained in V0_1_15_STABLE_REPORT.json, V0_1_15_STABLE_INSTALL.json and V0_1_15_STABLE_RELEASE.json alongside this file.
