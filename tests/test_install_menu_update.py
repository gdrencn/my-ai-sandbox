"""Real sudo/PTY boundaries, streamed APT fragments and merged navigation."""
import contextlib
import io
import os
from pathlib import Path
import pwd
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from mas.core import Error
from mas.install import dependency_script
from mas.terminal_ui import UI, STOP_ALL
from mas.testing import Terminal


class NavigationTests(unittest.TestCase):
    def test_main_menu_direct_entries_and_exit(self):
        view, manager = Mock(), Mock()
        view.choose.return_value = 'exit'
        UI(view, manager).loop()
        self.assertEqual([key for key, _ in view.choose.call_args.args[1]],
                         ['list', 'new', 'import', 'migrate', 'settings', 'exit'])
        manager.list.assert_not_called()

    def test_stop_all_visibility_uses_count_and_exact_stopped_state(self):
        for states, expected in [([],False),(['Running'],False),(['Stopped'],False),
                (['Stopped','Stopped'],False),(['Running','Stopped'],True),
                (['Stopping','Stopped'],True),(['Frozen','Error'],True)]:
            with self.subTest(states=states):
                view, manager = Mock(), Mock()
                manager.list.return_value = [dict(name=f'test-{i}',status=s) for i,s in enumerate(states)]
                view.choose.return_value = None
                with contextlib.redirect_stdout(io.StringIO()): UI(view, manager).containers()
                keys = [key for key,_ in view.choose.call_args.args[1]]
                self.assertEqual(STOP_ALL in keys, expected)
                self.assertIsNone(keys[-1])
                self.assertEqual(view.choose.call_args.kwargs['default'], 'test-0' if states else None)
                if expected: self.assertIs(keys[-2],STOP_ALL)

    def test_stop_all_reuses_foundation_and_refreshes_visibility(self):
        view, manager = Mock(), Mock()
        manager.list.side_effect = [[dict(name='a',status='Running'),dict(name='b',status='Stopped')],
                                   [dict(name='a',status='Stopped'),dict(name='b',status='Stopped')]]
        view.choose.side_effect = [STOP_ALL, None, None]
        UI(view,manager).containers()
        manager.stop_all.assert_called_once_with()
        self.assertNotIn(STOP_ALL,[key for key,_ in view.choose.call_args.args[1]])
        manager.stop.assert_not_called()

    def test_stop_all_container_name_does_not_collide(self):
        view, manager = Mock(), Mock()
        manager.list.return_value = [dict(name='stop-all',status='Stopped')]
        view.choose.side_effect = ['stop-all',None]
        ui=UI(view,manager);ui.container=Mock()
        ui.containers()
        ui.container.assert_called_once_with('stop-all')
        manager.stop_all.assert_not_called()

    def test_query_failure_is_not_an_empty_list(self):
        view, manager = Mock(), Mock()
        manager.list.side_effect=Error('query failed')
        with self.assertRaisesRegex(Error,'query failed'): UI(view,manager).containers()
        view.choose.assert_not_called()

    def test_preferences_returns_to_same_top_level_selection(self):
        view, manager = Mock(), Mock()
        view.choose.side_effect=['settings','back','exit']
        UI(view,manager).loop()
        self.assertEqual(view.choose.call_args.kwargs['default'],'settings')


class AptStreamingTests(unittest.TestCase):
    def test_fragmented_normal_output_is_not_promoted_to_permanent_lines(self):
        command=dependency_script()+r'''
{ printf 'Rea'; sleep .15; printf 'ding package lists...'; sleep .15; printf '\rBuilding dependency tree...'; sleep .15; printf '\nFetched 45.7 kB'; sleep .15; printf '\nW: preserved warning\n'; } | mas_apt_render
'''
        result=subprocess.run(['bash','-o','pipefail','-c',command],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'W: preserved warning\n')

    def test_fragmented_unknown_prompt_and_diagnostic_are_retained_once(self):
        command=dependency_script()+r'''
{ printf 'Native question: '; sleep .15; printf '\nSetting up package '; sleep .15; printf 'failed\nUnknown final detail'; } | mas_apt_render
'''
        result=subprocess.run(['bash','-o','pipefail','-c',command],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.stdout,'Native question: \nSetting up package failed\nUnknown final detail\n')

    @unittest.skipUnless(shutil.which('sudo'), 'sudo is not installed')
    def test_real_sudo_keeps_child_terminal_read_and_prompt_usable(self):
        # Same-user real sudo exercises its PTY monitor without host privilege
        # changes or credentials. The apt stand-in forks and reads like APT's
        # pre-dpkg input drain, then verifies an unterminated native prompt.
        with tempfile.TemporaryDirectory(prefix='mas-sudo-boundary-') as directory:
            root=Path(directory); apt=root/'apt-get'
            apt.write_text('#!'+sys.executable+'\n'+'''import os,fcntl,time,signal,sys
child=os.fork()
if child==0:
 flags=fcntl.fcntl(0,fcntl.F_GETFL)
 fcntl.fcntl(0,fcntl.F_SETFL,flags|os.O_NONBLOCK)
 try: os.read(0,1)
 except BlockingIOError: pass
 fcntl.fcntl(0,fcntl.F_SETFL,flags)
 os._exit(0)
end=time.monotonic()+5
while time.monotonic()<end:
 found,status=os.waitpid(child,os.WNOHANG)
 if found:
  assert status==0
  break
 time.sleep(.01)
else:
 os.kill(child,signal.SIGKILL);os.waitpid(child,0)
 print('ERROR: child terminal read stopped',flush=True);sys.exit(44)
if os.isatty(0):
 print('Native question: ',end='',flush=True)
 assert input()=='continue'
print('PROBE_FINISHED',flush=True)
''');apt.chmod(0o755)
            username=pwd.getpwuid(os.getuid()).pw_name
            script=dependency_script().replace('[[ $EUID -eq 0 ]]','false').replace('privilege=(sudo)',
                'privilege=(sudo -n -u '+shlex.quote(username)+' env PATH="$PATH")')
            command='export PATH='+shlex.quote(directory+':'+os.environ['PATH'])+'\n'+script+'\nmas_run_apt install -y sshfs'
            for redirected in (False,True):
                with self.subTest(redirected=redirected):
                    if redirected:
                        result=subprocess.run(['bash','-o','pipefail','-c',command],capture_output=True,text=True,timeout=20)
                        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
                        self.assertIn('PROBE_FINISHED',result.stdout)
                    else:
                        term=Terminal(['bash','-o','pipefail','-c',command],300,root/'terminal.log')
                        try:
                            term.expect('Native question: ');term.send('continue\n')
                            term.expect('PROBE_FINISHED');term.finish()
                        finally:term.close()
