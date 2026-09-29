"""Preserve native diagnostics without translating or rewriting their content."""
import re
import sys
from contextlib import contextmanager

WARNING = re.compile(r'(?<![\w-])(?:warning|error|failed|failure|fatal|traceback|deprecated)(?![\w-])|警告|错误|失败', re.I)


def diagnostic_lines(stdout, stderr):
    return stderr.splitlines() + [line for line in stdout.splitlines() if WARNING.search(line)]


def emit_native(message, callback=None):
    """Use the caller's active renderer; keep native content unchanged."""
    if not message:
        return
    if callback is not None:
        notify(callback, message.rstrip('\n'))
    else:
        from .output import Output
        Output(sys.stderr).keep(message.rstrip('\n'))


def warn(message, error):
    """Best-effort secondary diagnostics; never replace the primary exception."""
    try:
        from .i18n import t
        print(t(message, error=error), file=sys.stderr)
    except Exception:
        pass


def notify(callback, *args):
    """Observers cannot replace an operation's result or primary failure."""
    try:
        callback(*args)
    except Exception as exc:
        warn('report_failed', exc)


@contextmanager
def cleanup_scope(cleanup, on_error=None):
    """Always release owned resources; a second failure cannot replace the first."""
    try:
        yield
    except BaseException:
        try:
            cleanup()
        except Exception as exc:
            if on_error is None:
                warn('cleanup_secondary', exc)
            else:
                notify(on_error, exc)
        raise
    else:
        cleanup()
