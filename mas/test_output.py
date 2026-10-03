"""Transient terminal progress with permanent diagnostics and stage summaries."""
import re
from collections import Counter
from .output import Output as TerminalOutput, terminal_size
from .i18n import t

# Raw external output is never translated. Unknown stderr is kept, not hidden.
PROGRESS = re.compile(r'^\[(?:waiting|ok|Native step complete|等待中|成功|原生步骤完成)\] .*?(?:waited|已等待) .*(?:s|秒)$')
from .diagnostics import WARNING


class Output(TerminalOutput):
    def section(self, category, name, description):
        columns = terminal_size(self.stream).columns
        self.keep('─' * max(1, min(80, columns - 1)))
        self.keep(t('test_stage', category=category, name=name, description=description))

    def result(self, message, passed):
        mark = '✓' if passed else '✗'
        if message.startswith(mark):
            message = self.foreground(mark, 'green' if passed else 'red') + message[1:]
        self.keep(message)

    def expected_error(self, command):
        label = self.foreground(t('expected_error_label'), 'yellow')
        self.keep(t('expected_error', label=label, command=command))

    def challenge(self, message):
        # Only owned status lines receive color; commands/evidence stay intact.
        if message.startswith('[通过]'):
            message = self.foreground('✓', 'green') + ' ' + message
        elif message.startswith('[失败]'):
            message = self.foreground('✗', 'red') + ' ' + message
        self.keep(message)

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
