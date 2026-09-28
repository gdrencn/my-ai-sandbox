"""Preserve native diagnostics without translating or rewriting their content."""
import re

WARNING = re.compile(r'(?<![\w-])(?:warning|error|failed|failure|fatal|traceback|deprecated)(?![\w-])|警告|错误|失败', re.I)


def diagnostic_lines(stdout, stderr):
    return stderr.splitlines() + [line for line in stdout.splitlines() if WARNING.search(line)]
