"""Real PTY coverage for shell output preceding terminal restoration."""
from pathlib import Path
import sys
import tempfile
import unittest

from mas.testing import Suite, Terminal


# A sudo-like child emits its result before restoring/flushing the terminal.
# Delays model the race deterministically; production synchronization has none.
SHELL = r'''
import os, select, sys, termios, time

def emit(text):
    sys.stdout.write(text)
    sys.stdout.flush()

def prompt():
    emit('\x1b]3008;user=sandbox;hostname=original-host\x1b\\')
    emit('\x1b[?2004h\x1b]0;sandbox@original-host: ~\x07')
    emit('sandbox@original-host:')
    time.sleep(0.05)
    emit('~$ ')

emit('\x1b]0;sandbox@misleading-title: ~\x07')
time.sleep(0.05)
prompt()
command = sys.stdin.readline()
assert "printf 'MAS_%s" in command, repr(command)
emit('MAS_SHELL\nsandbox\n0\n')
time.sleep(0.2)
termios.tcflush(0, termios.TCIFLUSH)
prompt()
if select.select([0], [], [], 1)[0]:
    command = sys.stdin.readline()
    assert command == 'exit\n', repr(command)
    emit('\nlogout\nEXIT_RECEIVED\n')
else:
    emit('\nINPUT_LOST\n')
'''


class TerminalSyncTests(unittest.TestCase):
    def terminal(self, directory):
        terminal = Terminal([sys.executable, '-c', SHELL], 300,
                            Path(directory) / 'shell.log')
        self.addCleanup(terminal.close)
        return terminal

    def test_output_only_handshake_reproduces_lost_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = self.terminal(directory)
            terminal.shell_ready()
            terminal.send("printf 'MAS_%s\\n' SHELL; id -un; sudo -n id -u\n")
            terminal.expect('MAS_SHELL\r\n')
            terminal.expect('sandbox\r\n')
            terminal.expect('0\r\n')
            terminal.send('exit\n')
            terminal.expect('INPUT_LOST')
            terminal.finish()

    def test_shared_probe_waits_for_prompt_after_terminal_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = self.terminal(directory)
            Suite.check_shell(None, terminal)
            terminal.send('exit\n')
            terminal.expect('EXIT_RECEIVED')
            terminal.finish()
            self.assertNotIn(b'INPUT_LOST', terminal.buffer)
