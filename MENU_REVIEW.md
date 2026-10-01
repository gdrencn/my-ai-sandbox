# Menu interaction review — October 2026

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
