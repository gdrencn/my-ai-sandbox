# Menu interaction review — October 2026

These are recommendations requested alongside the 0.2.12 test/probe review. They are not implemented menu requirements. Existing lifecycle, default-No confirmations, arrow navigation, inline history and exit-to-host-shell behavior remain the accepted baseline.

## Recommended wording and structure

| Current behavior | Recommendation | Reason and scope |
| --- | --- | --- |
| `UI.present(..., back=False)` prints a section heading; settings, hardware and container selection immediately print the same heading again. | Navigation pages should let their own selection component provide the title once. Keep explicit function-entry headings for operations and failures. | Removes the observed duplicate `mas 选项` and hardware/container titles without removing the user's function-entry experience. |
| Main entry says `查看容器`; the destination is a selectable container list supporting further management. | Use `容器列表` / `Containers`, matching the destination title. | Names the page's actual task rather than implying a read-only display. |
| Selected-container menu has eleven rows, including three filesystem actions. | Consider a purposeful `文件系统` / `Filesystem` page containing view, mount and unmount. Keep info, enter, start, stop, hardware, export, delete and back in the container page. | Reduces the long per-container menu; adds a task-specific layer, so adoption requires a user decision. Do not reintroduce a general container-management intermediate page. |
| `迁移旧容器` does not explain what qualifies as old. | Use `迁移旧版本容器`; explain on entry that this moves containers managed by earlier mas versions into the current management scope and requires stopped state plus no recorded mounts. | Clarifies purpose and preconditions before selection/confirmation. Keep the entry available with an explicit empty result; do not add a startup query solely to hide it. |
| Container-name prompt gives no syntax guidance. | Explain the existing rule before submission: starts with a letter, 1–63 letters/digits/hyphens, ends with a letter or digit. | Uses the same actual validation rule; does not invent a second validator in the UI. |
| Directory mount input says `容器内目录路径`, but accepts only absolute, non-symlink directory paths. | Say `请输入容器内的绝对目录路径`, preserve the sandbox-home default, and explain the non-symlink restriction in the operation context/help. | Makes the requested input clear before an avoidable failure. |
| Import/export file inputs do not distinguish host and guest paths. | Say `宿主上的备份文件路径` and `宿主上的备份保存路径`. | Especially useful after users have just entered or mounted a container. |
| Mount listing uses literal tabs; selectable rows already use display-width-aware space alignment. | Reuse the existing column formatter for the read-only mount view, keeping path, host destination and status left-aligned. | Aligns translated wide text consistently with selection views. Do not remove necessary status columns. |
| Information page shows raw expanded JSON only. | Consider a concise name/state/GPU summary with an explicit way to see complete configuration. | Improves routine inspection while preserving exact diagnostic data; details-page behavior requires discussion. CLI JSON output should remain unchanged. |
| Shared menu footer says `Esc/← 返回`, even at the main page and in confirmations. | Let the same component select an accurate footer for `退出`, `返回` or `取消`, preserving identical keys. | Describes the existing behavior rather than changing navigation. |

## Verification before any later implementation

Use both language catalogs and real PTYs. Check exact heading count, blank-line boundaries, return focus, zero/one/multiple container lists, ordinary and residual mount rows, narrow terminals, result-before-navigation order, default-No confirmation and shell exit to the host. Preserve existing CLI/backend reuse and native failure handling. Recommendations that change menu layering or details views must be discussed before implementation.
