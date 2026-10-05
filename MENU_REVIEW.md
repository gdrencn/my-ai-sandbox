# Current menu contract and review — 0.2.25

The accepted stable/test product uses one shared inline UI. Earlier approved ten refinements, shell-flow changes and resize investigations are preserved in [the menu history](docs/history/MENU_REVIEW_0_2_25.md). Current workflow applies the repository copy of [CLI_TUI_GUIDELINES.md](docs/CLI_TUI_GUIDELINES.md); implementation details are in CORE_BEHAVIOR.md.

## Navigation inventory

| Page/control | Order and behavior |
| --- | --- |
| Main | Containers, New, Import, Migrate legacy version containers, mas Preferences, Exit. No pointless extra top-level page. |
| Containers | Name/state aligned selection; Stop all before Back only for more than one owned target with some non-Stopped state. Query failure is not an empty list. |
| Selected container | Info, Start, Enter, Stop, Restart, Export, Delete, Filesystem, Hardware, Back. |
| Info | Summary including GPU/network, Complete configuration, Back; one original record reused. |
| Filesystem | Recorded mounts, Mount, Unmount, Back; exact directory choices and full abnormal-status column only when needed. |
| Hardware | GPU when supported, Network, Back. Stopped changes and shared result/parent focus. |
| Preferences | Language, About my-ai-sandbox, Back. Language changes persist immediately. |
| About | Running mas.__version__ and one Back; no backend/download. Enter/Right or Escape/Left returns with About selected. |
| After entered shell | Stop container, Restart container, Return to mas, Exit mas; default/dismissal Exit. Restart does not re-enter. Return preserves Enter focus without a result page. |
| Independent host security | Same container name/state selector, explicit TARGET also supported; empty/cancel changes no state. Standard lifecycle restores initial state. |

## Shared interaction boundaries

Navigation selectors own one title. Action entry has explicit spacing/title, then necessary input, waiting/output, result and Back. Results/warnings/errors appear before parent navigation, not after a premature parent redraw. Parent focus is retained. New/import specify valid name syntax; import/export paths are on the host; mounts request an absolute non-symlink guest directory. Destructive consent defaults No; missing noninteractive consent does not imply Yes.

↑/↓ wraps selection; Enter/Right confirms; Esc/Left means Exit at root, Back below, Cancel in decisions. Text arrows edit the cursor. Labels/control characters are escaped and columns align by terminal display cells. Color is supplemental. Completion/cancellation/interruption restores terminal modes and cursor.

Screen replaces visible active rows from its first-row anchor; permanent titles/results and scrollback survive resize. It removes obsolete shorter rows and preserves input/checks/focus. Extreme reflow can put obsolete activity into native scrollback, which remains historical. Pre-Python language choice has documented minimum dimensions; explicit --language avoids its interactive control.

Normal progress is one temporary physical row; first-boot output updates independently of state checks. Scoped waiting precedes slow list/info/hardware/migration/mount queries. Permanent native diagnostics clear transient activity first; redirects remain plain. After Python exists, installation/test/product reuse common output. Bash is only the necessary limited adapter before Python, not a second general UI framework.

## Verification and pending choice

449 final packaged units include the About PTY regression in both languages and all four return keys. Native final test/stable menu stages visit both languages, then finish complete operations. Current frozen/public/stable runs are recorded in IMPLEMENTED.md. Earlier native tmux display-engine captures cover grow/restore/height-only changes and Unicode reflow; user accepted actual maximization/restoration and About.

The post-terminal Restart→re-enter refinement remains a discussion item; current Restart returns to host, while explicit `mas restart TARGET --enter` already exists. Other structural changes require a concrete requirement and authorization. Do not reintroduce full-screen UI, duplicate generic renderers or an extra About result page.
