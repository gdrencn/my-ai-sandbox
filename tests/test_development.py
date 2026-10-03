"""Preparation completion, native failure preservation and APT development packages."""
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import Mock, patch

from mas import development
from mas.core import CLOUD_INIT_WAIT, Error, MANAGED, Manager, USER_SETUP

FINISH = development.finish


class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        language = patch('mas.config.language', return_value='en_us')
        language.start(); self.addCleanup(language.stop)
        self.item = dict(name='fixture',status='Stopped',type='container',config={MANAGED:'true','volatile.uuid':'owned-id'})
        self.manager = Manager(Mock(timeout=600), report=Mock(), isolation=Mock())
        self.manager.absent = Mock()
        self.manager.gpu = Mock()
        self.manager.find = Mock(side_effect=lambda target:self.item.copy())
        self.manager.require = Mock(side_effect=lambda target,**kw:self.item.copy())
        self.trace=[]
        def operation(action,*args,**kwargs):
            self.trace.append(action)
            return self.item.copy()
        self.manager._run_lxd_until_state=Mock(side_effect=operation)
        self.manager.start=Mock(side_effect=lambda target:self.trace.append('start'))
        self.manager.stop=Mock(side_effect=lambda target:self.trace.append('stop'))
        finish=patch.object(development,'finish')
        self.finish=finish.start();self.addCleanup(finish.stop)

    def test_creation_completes_only_after_shared_start_verification_and_stop(self):
        self.manager.new('fixture','ubuntu:26.04')
        self.assertEqual(self.trace,['new','start','prepare-development','stop'])
        event=self.manager.report.call_args.args[0]
        self.assertEqual((event['action'],event['status'],event['observation']),('new','ok','Stopped'))
        arguments=self.manager._run_lxd_until_state.call_args_list[0].args[2]
        data=next(value.split('=',1)[1] for value in arguments if value.startswith('cloud-init.user-data='))
        conf=json.loads(data.split('\n',1)[1])
        self.assertEqual(conf['packages'],list(development.PACKAGES))
        self.assertTrue(conf['package_update']);self.assertFalse(conf['package_upgrade'])
        self.assertIn('nodejs',conf['packages']);self.assertIn('npm',conf['packages'])
        self.assertNotIn('runcmd',conf);self.assertNotIn('write_files',conf)

    def test_preparation_failure_stops_without_publishing_creation_success(self):
        primary=Error('native package preparation failed')
        self.manager._run_lxd_until_state.side_effect=[self.item.copy(),primary]
        with self.assertRaises(Error) as caught:self.manager.new('fixture','ubuntu:26.04')
        self.assertIs(caught.exception,primary)
        self.manager.stop.assert_called_once_with('fixture')
        self.assertFalse(any(call.args[0]['status']=='ok' for call in self.manager.report.call_args_list))

    def test_secondary_stop_failure_preserves_primary_error(self):
        primary=Error('primary package failure')
        self.manager._run_lxd_until_state.side_effect=[self.item.copy(),primary]
        self.manager.stop.side_effect=Error('secondary stop failure')
        with self.assertRaises(Error) as caught:self.manager.new('fixture','ubuntu:26.04')
        self.assertIs(caught.exception,primary)
        self.assertIn('secondary stop failure',self.manager.report.call_args.args[0]['native_stderr'])

    def test_failed_stop_cannot_publish_creation_success(self):
        self.manager.stop.side_effect=Error('native stop failed')
        with self.assertRaisesRegex(Error,'native stop failed'):self.manager.new('fixture','ubuntu:26.04')
        self.manager.report.assert_not_called()

    def test_replacement_container_is_not_stopped(self):
        def start(target):self.item['config']={MANAGED:'true','volatile.uuid':'replacement'}
        self.manager.start.side_effect=start
        with self.assertRaisesRegex(Error,'changed identity'):self.manager.new('fixture','ubuntu:26.04')
        self.manager.stop.assert_not_called()

    def test_configuration_conflict_fails_and_preserves_other_configuration(self):
        self.finish.side_effect=Error('configuration changed during preparation')
        with self.assertRaisesRegex(Error,'configuration changed'):self.manager.new('fixture','ubuntu:26.04')
        self.manager.stop.assert_called_once_with('fixture')
        self.manager.report.assert_not_called()

    def test_completed_container_does_not_reinstall_removed_sudo(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);record=root/'record';record.write_text('{}')
            apt=root/'apt-get';apt.write_text('#!/bin/sh\necho unexpected-apt\n');apt.chmod(0o755)
            command=USER_SETUP.replace('/var/lib/mas/development.json',str(record))
            result=subprocess.run(['/bin/sh','-c',command],env={'PATH':str(root)},capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('sudo was removed',result.stderr)
            self.assertNotIn('unexpected-apt',result.stdout)

    def test_failed_cloud_init_preserves_native_diagnostic_and_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,script in [('cloud-init','exit 1'),('tail','echo "E: Unable to locate package missing-fixture"')]:
                path=root/name;path.write_text('#!/bin/sh\n'+script+'\n');path.chmod(0o755)
            result=subprocess.run(['/bin/sh','-c','set -eu\n'+CLOUD_INIT_WAIT],env={'PATH':str(root)},capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertIn('E: Unable to locate package missing-fixture',result.stderr)

    def test_retirement_preserves_unrelated_config_and_uses_etag(self):
        data=development.cloud_config();api=Mock()
        item={'config':{'volatile.uuid':'id','cloud-init.user-data':data,'user.custom':'preserve'},'devices':{'root':{'type':'disk'}}}
        api.read.side_effect=[(item,'"etag"'),({'config':{'volatile.uuid':'id','user.custom':'preserve'}},'"new"')]
        manager=Mock();manager.lxd.configuration=api
        FINISH(manager,'fixture',data,'id')
        args=api.write.call_args.args
        self.assertEqual(args[0],'fixture');self.assertEqual(args[2],'"etag"')
        self.assertEqual(args[1]['config'],{'volatile.uuid':'id','user.custom':'preserve'})
        self.assertEqual(args[1]['devices'],{'root':{'type':'disk'}})

    def test_retirement_conflicts_do_not_overwrite_another_operation(self):
        data=development.cloud_config()
        for config in ({'volatile.uuid':'replacement','cloud-init.user-data':data},
                       {'volatile.uuid':'id','cloud-init.user-data':'custom change'}):
            api=Mock();api.read.return_value=({'config':config},'"etag"')
            manager=Mock();manager.lxd.configuration=api
            with self.assertRaises(Error):FINISH(manager,'fixture',data,'id')
            api.write.assert_not_called()

    def test_start_failure_and_interrupt_attempt_standard_stop(self):
        for error in (Error('start failed'),KeyboardInterrupt()):
            self.manager.start.side_effect=error;self.manager.stop.reset_mock()
            with self.assertRaises(type(error)) as caught:self.manager.new('fixture','ubuntu:26.04')
            self.assertIs(caught.exception,error)
            self.manager.stop.assert_called_once_with('fixture')

    def test_live_wait_streams_log_and_reaps_tail_after_success_or_failure(self):
        for code in (0,1):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                cloud=root/'cloud-init'
                cloud.write_text('#!/bin/sh\nsleep 0.1\nexit '+str(code)+'\n');cloud.chmod(0o755)
                log=root/'cloud.log';log.write_text('Unpacking nodejs fixture\nSetting up npm fixture\n')
                script='set -eu\n'+development.live_wait().replace('/var/log/cloud-init-output.log',str(log))
                result=subprocess.run(['/bin/sh','-c',script],env={'PATH':str(root)+':/usr/bin:/bin'},capture_output=True,text=True,timeout=3)
                self.assertEqual(result.returncode,code)
                self.assertIn('Unpacking nodejs fixture',result.stdout)
                self.assertIn('Setting up npm fixture',result.stdout)
                if code:self.assertIn('Setting up npm fixture',result.stderr)
