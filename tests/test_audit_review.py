"""Regression coverage for the reliability and presentation audit."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from mas import config
from mas.cli import parser
from mas.core import Error, LXD
from mas.install import configure_path, run
from mas.test_output import Output
from mas.testing import Suite, Terminal, python_command


class AuditTests(unittest.TestCase):
    def test_damaged_path_blocks_fail_before_any_startup_file_is_changed(self):
        begin, end = '# >>> my-ai-sandbox PATH >>>', '# <<< my-ai-sandbox PATH <<<'
        for damaged in (begin, end, end+'\n'+begin, begin+'\nx\n'+begin+'\n'+end,
                        begin+'\nx\n'+end+'\n'+end, 'prefix '+begin+'\nx\n'+end):
            with self.subTest(damaged=damaged), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                (home/'.profile').write_text('unrelated login content\n')
                (home/'.bashrc').write_text(damaged)
                with self.assertRaises(Error):configure_path(home, '/bin/bash')
                self.assertEqual((home/'.profile').read_text(), 'unrelated login content\n')
                self.assertEqual((home/'.bashrc').read_text(), damaged)

    def test_path_write_is_atomic_preserves_mode_and_user_content(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            startup = home/'.profile'
            startup.write_text('export USER_SETTING=keep\n')
            startup.chmod(0o640)
            with patch('mas.install.os.replace', side_effect=OSError('publish failed')):
                with self.assertRaisesRegex(OSError, 'publish failed'):configure_path(home, '/bin/bash')
            self.assertEqual(startup.read_text(), 'export USER_SETTING=keep\n')
            self.assertFalse(list(home.glob('*.mas-*')))
            configure_path(home, '/bin/bash')
            self.assertEqual(startup.stat().st_mode & 0o777, 0o640)
            self.assertIn('export USER_SETTING=keep', startup.read_text())
            original = startup.read_bytes()
            configure_path(home, '/bin/bash')
            self.assertEqual(startup.read_bytes(), original)

    def test_startup_symlink_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home/'user-profile'
            target.write_text('keep')
            (home/'.profile').symlink_to(target)
            with self.assertRaises(Error):configure_path(home, '/bin/bash')
            self.assertEqual(target.read_text(), 'keep')
            self.assertTrue((home/'.profile').is_symlink())

    def test_captured_success_keeps_diagnostics_and_failure_keeps_both_streams(self):
        with patch('mas.install.subprocess.run', return_value=subprocess.CompletedProcess([],0,'result','native warning')):
            with contextlib.redirect_stderr(io.StringIO()) as stream:
                self.assertEqual(run(['fixture'], capture=True, display=False), 'result')
            self.assertEqual(stream.getvalue().count('native warning'), 1)
        result = subprocess.CompletedProcess([],1,'stdout detail','stderr detail')
        with patch('mas.install.subprocess.run', return_value=result):
            with self.assertRaisesRegex(Error, 'stdout detail\nstderr detail'):run(['fixture'], capture=True, display=False)
        with patch('mas.core.shutil.which', return_value='/fixture/lxc'):
            lxd = LXD()
        with patch('mas.core.subprocess.run', return_value=result):
            with self.assertRaisesRegex(Error, 'stdout detail\nstderr detail'):lxd.command(['list'])

    def test_sigterm_ignoring_terminal_is_killed_reaped_and_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = Terminal(python_command("import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('READY',flush=True);time.sleep(60)"),
                                1, Path(directory)/'pty.log')
            try:
                terminal.expect('READY')
                terminal.close()
                self.assertEqual(terminal.status, -signal.SIGKILL)
                self.assertIsNone(terminal.fd)
                self.assertTrue(terminal.transcript.closed)
                terminal.close()  # Idempotent finalization.
                with self.assertRaises(ChildProcessError):os.waitpid(terminal.pid, os.WNOHANG)
            finally:
                if terminal.fd is not None:
                    with contextlib.suppress(ProcessLookupError):os.killpg(terminal.pid,signal.SIGKILL)
                    terminal.close()

    def test_terminal_cleanup_failure_preserves_primary_and_restores_language(self):
        with tempfile.TemporaryDirectory() as directory:
            suite = Suite(Path(directory)/'report', 600)
            self.addCleanup(suite.workspace.cleanup)
            suite.current_case = 'tui'
            suite.output = Output(io.StringIO())
            with patch.dict(os.environ, {'XDG_CONFIG_HOME':str(suite.config_home)}):
                config.set_value('language','zh_cn')
            terminal = Mock()
            terminal.close.side_effect = Error('close failed')
            with patch('mas.testing.Terminal', return_value=terminal):
                with self.assertRaisesRegex(AssertionError, 'primary failure'):
                    with suite.terminal([]):
                        suite.event_path.write_text(json.dumps({'status':'warning','native_stderr':'final native warning'})+'\n')
                        raise AssertionError('primary failure')
            self.assertEqual(suite.cleanup_errors, ['close failed'])
            self.assertTrue(any(e.get('native_stderr') == 'final native warning' for e in suite.events))
            with patch.dict(os.environ, {'XDG_CONFIG_HOME':str(suite.config_home)}):
                self.assertEqual(config.get('language'),'zh_cn')

    def test_unconfirmed_killed_terminal_reports_bounded_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal=Terminal.__new__(Terminal)
            terminal.pid=999999;terminal.timeout=600;terminal.status=None;terminal.on_read=None
            terminal.fd, write_fd=os.pipe()
            self.addCleanup(os.close,write_fd)
            terminal.transcript=(Path(directory)/'transcript').open('wb')
            clock=[0]
            terminal._reap=Mock(side_effect=lambda:clock.__setitem__(0,clock[0]+100))
            with patch('mas.testing.os.killpg') as kill, patch('mas.testing.time.monotonic',side_effect=lambda:clock[0]), patch('mas.testing.time.sleep'):
                with self.assertRaises(Error):terminal.close()
            self.assertEqual([call.args[1] for call in kill.call_args_list],[signal.SIGTERM,signal.SIGKILL])
            self.assertIsNone(terminal.fd)
            self.assertTrue(terminal.transcript.closed)

    def test_terminal_exec_failure_exits_child_without_running_parent_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal=Terminal(['/missing-mas-test-executable'],300,Path(directory)/'pty.log')
            try:
                with self.assertRaises(AssertionError):terminal.finish()
                self.assertEqual(terminal.status,127)
                self.assertIn(b'FileNotFoundError',terminal.buffer)
            finally:terminal.close()

    def test_incremental_events_wait_for_complete_lines_and_display_once(self):
        with tempfile.TemporaryDirectory() as directory:
            suite = Suite.__new__(Suite)
            suite.events=[];suite.output=Output(io.StringIO());suite.current_case='tui'
            path=Path(directory)/'events.jsonl'
            line=json.dumps({'status':'warning','native_stderr':'older warning'})
            path.write_text(line[:8])
            self.assertEqual(suite.read_events(path,True),[])
            with path.open('a') as stream:stream.write(line[8:]+'\n')
            self.assertEqual(suite.read_events(path,True),['older warning'])
            self.assertEqual(suite.read_events(path,True),[])
            self.assertEqual(len(suite.events),1)
            self.assertEqual(suite.events[0]['case'],'tui')
            self.assertEqual(suite.output.stream.getvalue().count('older warning'),1)

    def test_pty_diagnostics_arrive_before_a_later_direct_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            suite = Suite(Path(directory)/'report',600)
            self.addCleanup(suite.workspace.cleanup)
            suite.current_case='tui';suite.output=Output(io.StringIO())
            event_path=suite.directory/'stream-events.jsonl'
            source=(f"from pathlib import Path;import json,sys;Path({str(event_path)!r}).write_text(json.dumps(dict(status='warning',native_stderr='older warning'))+'\\n');"
                    "print('PAUSE',flush=True);sys.stdin.readline();print('DONE',flush=True)")
            def command(args):
                suite.event_path=event_path
                return python_command(source)
            with patch.object(suite,'command',side_effect=command):
                with suite.terminal([]) as terminal:
                    terminal.expect('PAUSE')
                    self.assertIn('older warning',suite.output.stream.getvalue())
                    suite.native_diagnostic('newer warning')
                    terminal.send('\n');terminal.finish()
            output=suite.output.stream.getvalue()
            self.assertLess(output.index('older warning'),output.index('newer warning'))
            self.assertEqual(output.count('older warning'),1)

    def test_native_failure_event_is_logged_without_duplicate_display(self):
        with tempfile.TemporaryDirectory() as directory:
            suite = Suite.__new__(Suite)
            suite.events=[];suite.output=Output(io.StringIO());suite.current_case='missing-image'
            path=Path(directory)/'events.jsonl'
            path.write_text(json.dumps(dict(status='error',native_failure=True,native_stderr='native error'))+'\n')
            self.assertEqual(suite.read_events(path,True),[])
            self.assertEqual(suite.events[0]['native_stderr'],'native error')
            self.assertEqual(suite.output.stream.getvalue(),'')

    def test_windows_unc_failure_records_observed_content_and_linux_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/'mounted';home.mkdir()
            (home/'windows-created').write_text('from Windows')
            suite=Suite.__new__(Suite);suite.events=[];suite.timeout=600;suite.directory=root
            output=json.dumps(dict(step='write',expected='from Windows',observed='',observed_length=0))+'\n'
            result=subprocess.CompletedProcess([],1,output,'native UNC detail')
            with patch.dict(os.environ,{'WSL_DISTRO_NAME':'fixture'}), patch('mas.testing.shutil.which',return_value='/fixture/tool'), \
                 patch('mas.testing.subprocess.check_output',return_value='\\\\wsl.localhost\\fixture\\path\n'), patch('mas.testing.subprocess.run',return_value=result):
                with self.assertRaises(AssertionError):suite.windows_filesystem(home)
            evidence=suite.events[0]
            self.assertEqual(evidence['status'],'error')
            self.assertEqual(evidence['steps'][0]['observed_length'],0)
            self.assertEqual(evidence['linux']['windows-created']['bytes_hex'],b'from Windows'.hex())
            self.assertEqual((root/'windows-unc.stderr.log').read_text(),'native UNC detail')

    def test_all_cli_commands_have_localized_descriptions_and_examples(self):
        for language in ('zh_cn','en_us'):
            with patch('mas.config.language',return_value=language):
                for command in ('new','list','start','stop','delete','info','import','export','enter','mountfs','unmountfs','mountedfs','hardware','config'):
                    with self.subTest(language=language,command=command), contextlib.redirect_stdout(io.StringIO()) as output:
                        with self.assertRaises(SystemExit) as exc:parser().parse_args([command,'--help'])
                        self.assertEqual(exc.exception.code,0)
                        self.assertIn('示例：' if language=='zh_cn' else 'Examples:',output.getvalue())
