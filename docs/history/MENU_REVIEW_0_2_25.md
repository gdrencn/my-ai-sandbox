> Historical snapshot of `MENU_REVIEW.md` at main `477f6a5b0c343c642e5cf2b8ec0832aac3a946b6` before the documentation/handoff batch. Statements about current versions, pending work and machine paths below are historical. Only this notice and relative Markdown links were adjusted; use the root documents for current guidance.

# Menu interaction review — October 2026

## Preferences About page — 0.2.25

The authorized About entry appears after Language and before Back. It uses the shared selection page to show the running product version and one Back choice; returns retain the parent focus. Real-PTY checks cover both languages, Enter/Right/Escape/Left navigation, title/spacing, terminal restoration and unchanged language configuration. The frozen native complete menu flow also visits About in both languages. The user has accepted this About/version page and authorized its stable/0.2.25 promotion. The handoff work remains subsequent.

## Stable 0.2.24 user acceptance (2026-10-04)

The user confirmed that terminal maximization/restoration no longer duplicates menus, supplied two successful complete v0.2.24 runs and an independent security run using shared container selection, and authorized stable publication. This is user-reported native-terminal acceptance, separate from the recorded tmux/PTy evidence. Stable product/installer bytes and all menu behavior remain identical to the accepted v0.2.24 test release; promotion changes distribution routing only.

These recommendations were requested alongside the 0.2.12 test/probe review and all ten were approved for batch 0.2.13. REQUIREMENTS.md section 42 records their implementation and acceptance scope. All ten are implemented and locally verified in frozen 0.2.13: 340 packaged units and 26 native stages passed in 663.7 seconds. Public-entry verification also passed all 340 units and 26 stages in 634.3 seconds, with no skipped units or cleanup errors; see validation/V0_2_13_PUBLIC_REPORT.json. Existing lifecycle, default-No confirmations, arrow navigation, inline history and exit-to-host-shell behavior remain the accepted baseline.

## Approved changes implemented in 0.2.13

| Prior behavior | Applied change | Reason and scope |
| --- | --- | --- |
| `UI.present(..., back=False)` printed a heading before a selector printed it again. | Navigation selectors own one title; actions and failures retain explicit entry headings. | Removes duplicate preferences/hardware/container titles while retaining function-entry context. |
| Main entry was `查看容器`. | Entry and destination now use `容器列表` / `Containers`. | Names the selectable management page's task. |
| Selected-container menu had eleven rows with three filesystem actions. | `文件系统` / `Filesystem` groups view, mount and unmount; info/start/enter/stop/export/delete/hardware/Back remain in the container page. | This approved task-specific layer shortens the menu; the merged main page remains. |
| `迁移旧容器` did not identify what qualifies as old. | `迁移旧版本容器` explains earlier mas-managed default-project containers, stopped state and no recorded mounts. | Explicit empty result remains; no startup query is added solely to hide this entry. |
| Container-name prompts lacked syntax guidance. | New/import explain 1–63 letters/digits/hyphens, initial letter and final letter/digit. | The existing backend validator remains the authority. |
| Mount input omitted the absolute/non-symlink requirements. | `请输入容器内的绝对目录路径` retains the sandbox-home default; operation help explains symbolic-link refusal. | Describes the accepted value before submission. |
| Backup inputs did not distinguish host and guest paths. | Import/export explicitly request paths on the host. | Identifies the resource being selected after entering or mounting a container. |
| Read-only mount rows used tabs. | The shared display-width-aware formatter left-aligns container path, complete host destination and status using spaces, without ANSI. | Preserves all columns and complete paths; selections retain existing status colors. |
| Information page only showed raw JSON. | Name/state/recorded-GPU summary offers Complete configuration and Back, using one queried record without GPU discovery. | Preserves complete diagnostic data and unchanged CLI JSON. |
| Footer always said `Esc/← 返回`. | Shared component uses Exit, Back or Cancel according to the page/decision in both languages and installation language selection. | Accurately describes existing key behavior; input cursor keys remain separate. |

## Verification and retained behavior

Both language catalogs and real PTYs were checked, including exact heading count, blank-line boundaries, return focus, zero/one/multiple container lists, ordinary and residual mount rows, narrow/short terminals, result-before-navigation order, default-No confirmation and shell exit to the host. Existing CLI/backend reuse and native failure handling are retained. Evidence: tests/test_menu_refinements.py and validation/V0_2_13_LOCAL_REPORT.json. Further structural changes remain subject to discussion.

## Subsequent approved change — 0.2.14

Section 43 supersedes the prior unconditional exit after an entered terminal. The selected-container page now includes Restart after Stop. Terminal completion offers Stop container, Restart container, Return to mas and Exit mas; default/dismissal is Exit mas. Return to mas preserves Enter focus from that menu and bypasses the result page. CLI terminal entry opens the selected-container page on the same choice. Shell codes remain diagnostics rather than selecting a destination. The ten earlier menu refinements remain implemented.

## Subsequent approved changes — 0.2.20–0.2.22

The independent host security entry uses the same container selector as mas: names and states, arrow navigation, explicit cancellation and an empty-list message, with no interactive name input. Explicit command-line TARGET remains supported. The hardware page includes Network on/off even when GPU access is unavailable. Both entries retain shared lifecycle, result/return and selection behavior.

The 0.2.22 preparation display uses one transient physical row containing the latest native output, with status as its fallback. Output is sampled independently of state checks and unchanged text is not redrawn. Normal output is cleared before summaries and diagnostics. This does not change menu navigation, confirmations or the agreed pending post-terminal restart-entry refinement. Verification details belong to TEST_COVERAGE.md and IMPLEMENTED.md.

## Shared component corrections — 0.2.23

GPU/network switching and settings language selection now let the input component own the entry title; result/return pages and retained parent focus remain. Information, hardware, migration and mount list queries use the common scoped waiting component before blocking, clear transient feedback and preserve native failures. CLI container listing uses the existing selection-row column formatter, including explicit empty feedback, complete names, localized states and spaces rather than tabs.

Host APT with Python, product progress and tester output share one renderer and diagnostic policy. Common terminal dimensions and semantic foreground colors are no longer implemented separately by the menu and tester. APT prefix warnings and secondary reporter diagnostics remain visible. Bash is retained only for preparing Python itself, with ASCII transient progress, complete non-ASCII/native diagnostics, a minimum-sized language menu and the same cancellation exit code 130. It is an explicit bootstrap limitation, not a separate general CLI/TUI component library.

Eleven focused guideline tests cover both languages, title ownership, result/return focus, delayed and failed queries, list alignment/empty feedback, language cancellation, narrow bootstrap rejection, Unicode/resize/prompts, APT prefix diagnostics, secondary output clearing and split CRLF consumption. Final frozen and exact public-entry runs each passed 439 units, 28 stages and one 76-check challenge, without skips, unexecuted stages or cleanup errors. Both-language public installation cancellation returned 130 with terminal restoration and no installed-file changes. Published test v0.2.23; see IMPLEMENTED.md Stage 42 for the complete verified outcomes.


## Shared resize correction — 0.2.24

Terminal dimensions previously caused Screen.draw to append a fresh menu block. The shared component now parks at the first active row and replaces visible activity from that anchor, preserving permanent output and prompt state. Shorter blocks clear obsolete rows and prompt exit restores normal input/cursor placement. Installation language, product menus and host security selection all reuse this correction. Native tmux grow/restore and height-only captures contain one menu in both languages; narrower Unicode/input/viewport cases preserve the active controls. Extreme native reflow can move old rows into scrollback, which remains history. See IMPLEMENTED.md Stage 43 for coverage and actual terminal limits.

Final frozen and exact public suites each passed 444 units, all 28 stages and one 76-check challenge without skips or cleanup errors. Actual public installer resize/cancellation and the host security selector's resized prompt passed. All current menu/behavior/coverage/status documents are synchronized with the verified batch; earlier phase records remain historical. Published test v0.2.24; stable/0.1.15 remains unchanged.
