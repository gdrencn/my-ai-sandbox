"""Transient terminal progress with permanent diagnostics and stage summaries."""
import re
import os
import shutil
from collections import Counter
from .output import Output as TerminalOutput
from .i18n import t

# Raw external output is never translated. Unknown stderr is kept, not hidden.
PROGRESS = re.compile(r'^\[(?:waiting|ok|Native step complete|等待中|成功|原生步骤完成)\] .*?(?:waited|已等待) .*(?:s|秒)$')
from .diagnostics import WARNING


class Output(TerminalOutput):
    def foreground(self, text, color):
        return f'\033[{color}m{text}\033[0m' if self.tty else text

    def section(self, category, name, description):
        try:
            columns = os.get_terminal_size(self.stream.fileno()).columns
        except (AttributeError, OSError, ValueError):
            columns = shutil.get_terminal_size().columns
        self.keep('─' * max(1, min(80, columns - 1)))
        self.keep(t('test_stage', category=category, name=name, description=description))

    def result(self, message, passed):
        mark = '✓' if passed else '✗'
        if message.startswith(mark):
            message = self.foreground(mark, 32 if passed else 31) + message[1:]
        self.keep(message)

    def expected_error(self, command):
        label = self.foreground(t('expected_error_label'), 33)
        self.keep(t('expected_error', label=label, command=command))

    def challenge(self, message):
        # Only owned status lines receive color; commands/evidence stay intact.
        if message.startswith('[通过]'):
            message = self.foreground('✓', 32) + ' ' + message
        elif message.startswith('[失败]'):
            message = self.foreground('✗', 31) + ' ' + message
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
