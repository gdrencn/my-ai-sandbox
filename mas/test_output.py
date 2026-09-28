"""Transient terminal progress with permanent diagnostics and stage summaries."""
import re
from .output import Output as TerminalOutput

# Raw external output is never translated. Unknown stderr is kept, not hidden.
PROGRESS = re.compile(r'^\[(?:waiting|ok|等待中|成功)\] .*?(?:waited|已等待) .*(?:s|秒)$')
from .diagnostics import WARNING


class Output(TerminalOutput):
    def diagnostics(self, stdout, stderr, failed=False):
        # All non-progress stderr is retained, including unknown warnings on exit 0.
        lines = [line for line in stderr.splitlines() if not PROGRESS.match(line)]
        lines += [line for line in stdout.splitlines() if failed or WARNING.search(line)]
        if lines:
            self.keep('\n'.join(lines))
