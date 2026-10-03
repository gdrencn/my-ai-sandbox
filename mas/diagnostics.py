"""Preserve native diagnostics without translating or rewriting their content."""
import re
import sys
from contextlib import contextmanager

WARNING = re.compile(r'^\s*(?:[WE]:|Err:)|(?<![\w-])(?:warning|error|failed|failure|fatal|traceback|deprecated)(?![\w-])|警告|错误|失败', re.I)


APT_NORMAL = (
    'Hit:', 'Get:', 'Ign:', 'Reading package lists', 'Building dependency tree',
    'Reading state information', 'Solving dependencies', 'The following ', 'Suggested packages:',
    'Recommended packages:', 'Need to get ', 'After this operation,', 'Fetched ',
    'Selecting previously unselected package ', 'Preparing to unpack ', 'Unpacking ',
    'Setting up ', 'Processing triggers for ', '(Reading database ', 'Scanning ',
    'All packages are up to date.', 'Reading changelogs', 'Extracting templates from packages:')


def normal_apt_line(line, complete=True, package_list=False):
    if WARNING.search(line):
        return False
    return (not line or any(line.startswith(prefix) or not complete and prefix.startswith(line)
                           for prefix in APT_NORMAL)
            or package_list and re.fullmatch(r'\s+[a-z0-9][a-z0-9.+:~_ -]*', line) is not None
            or re.match(r'^\d+ upgraded,', line) is not None)


def diagnostic_lines(stdout, stderr):
    return stderr.splitlines() + [line for line in stdout.splitlines() if WARNING.search(line)]


def failure_text(stdout, stderr):
    """Preserve both native streams, with a boundary even without newlines."""
    return '\n'.join(value.strip() for value in (stdout or '', stderr or '') if value.strip())


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
        emit_native(t(message, error=error))
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
