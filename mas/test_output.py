"""Transient terminal progress with permanent diagnostics and stage summaries."""
import re
from collections import Counter
from .output import Output as TerminalOutput

# Raw external output is never translated. Unknown stderr is kept, not hidden.
PROGRESS = re.compile(r'^\[(?:waiting|ok|Native step complete|等待中|成功|原生步骤完成)\] .*?(?:waited|已等待) .*(?:s|秒)$')
from .diagnostics import WARNING


class Output(TerminalOutput):
    def diagnostics(self, stdout, stderr, failed=False, exclude=()):
        # All non-progress stderr is retained, including unknown warnings on exit 0.
        lines = [line for line in stderr.splitlines() if not PROGRESS.match(line)]
        lines += [line for line in stdout.splitlines() if failed or WARNING.search(line)]
        seen = Counter(exclude)
        pending = []
        for line in lines:
            if seen[line]:
                seen[line] -= 1
            else:
                pending.append(line)
        lines = pending
        if lines:
            self.keep('\n'.join(lines))
        return lines
