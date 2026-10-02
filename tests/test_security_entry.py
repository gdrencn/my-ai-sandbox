"""Shared challenge lifecycle, public routing and separate final fixture."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import bootstrap
from mas import security_testing as security
from mas.core import Error
from mas.test_output import Output
from mas.testing import Suite


class SecurityEntryTests(unittest.TestCase):
    def setUp(self):
        lang = patch('mas.config.language', return_value='en_us')
        lang.start(); self.addCleanup(lang.stop)
        self.item = {'status':'Running', 'config':{'volatile.uuid':'owned-id'}}
        self.manager = Mock()
        self.manager.require.side_effect = lambda target: self.item.copy()
        self.manager.start.side_effect = lambda target: self.item.update(status='Running')
        self.manager.stop.side_effect = lambda target: self.item.update(status='Stopped')
        self.manager.gpu.record.return_value = None
        self.manager.lxd.project = 'fixture-project'
        self.manager.lxd.timeout = 600
        self.manager.lxd.configuration.endpoint.side_effect = lambda path:path+'?project=fixture-project'
        self.manager.lxd.configuration.request.return_value = ({'type':'sync','metadata':{}},None)
        self.challenge = Mock()
        self.challenge.run_target.return_value = None
        self.challenge.probe.result.side_effect = lambda check, status, message, **evidence: dict(check=check,status=status,message=message,evidence=evidence)
        self.report = Mock(data={})

    def run_target(self):
        return security.challenge_target(self.manager, 'fixture', self.challenge, self.report,
                                         timeout=3, positive=True)

    def test_stopped_target_starts_and_stops_through_shared_functions(self):
        self.item['status'] = 'Stopped'
        self.run_target()
        self.manager.start.assert_called_once_with('fixture')
        self.manager.stop.assert_called_once_with('fixture')
        self.assertEqual(self.report.data['lifecycle']['actions'], ['start','stop'])
        self.assertEqual(self.item['status'], 'Stopped')

    def test_running_target_remains_running_without_extra_lifecycle_calls(self):
        self.run_target()
        self.manager.start.assert_not_called(); self.manager.stop.assert_not_called()
        self.assertEqual(self.report.emit.call_args.args[0]['status'], 'PASS')

    def test_running_target_that_stops_during_test_is_restored(self):
        self.challenge.run_target.side_effect = lambda *args, **kwargs: self.item.update(status='Stopped')
        self.run_target()
        self.manager.start.assert_called_once_with('fixture')
        self.assertEqual(self.item['status'], 'Running')

    def test_native_failure_and_interrupt_still_restore_stopped_state(self):
        for error in (Error('native failure'), KeyboardInterrupt()):
            with self.subTest(error=type(error)):
                self.item['status'] = 'Stopped'
                self.manager.reset_mock()
                self.challenge.run_target.side_effect = error
                with self.assertRaises(type(error)) as caught:
                    self.run_target()
                self.assertIs(caught.exception, error)
                self.manager.stop.assert_called_once_with('fixture')
                self.assertEqual(self.item['status'], 'Stopped')

    def test_returned_primary_is_preserved_when_restoration_fails(self):
        self.item['status'] = 'Stopped'
        primary = Error('primary native failure')
        self.challenge.run_target.return_value = primary
        self.manager.stop.side_effect = Error('secondary stop failure')
        self.assertIs(self.run_target(), primary)
        item = self.report.emit.call_args.args[0]
        self.assertEqual((item['check'],item['status']), ('host-state-restore','ERROR'))
        self.assertIn('secondary stop failure',item['evidence']['native_error'])

    def test_start_failure_does_not_run_probe_but_attempts_standard_stop(self):
        self.item['status'] = 'Stopped'
        self.manager.start.side_effect = Error('start failed')
        with self.assertRaisesRegex(Error,'start failed'): self.run_target()
        self.challenge.run_target.assert_not_called()
        self.manager.stop.assert_called_once_with('fixture')

    def test_replaced_target_is_not_stopped_or_started(self):
        self.item['status'] = 'Stopped'
        self.challenge.run_target.side_effect = lambda *args, **kwargs: self.item.update(config={'volatile.uuid':'replacement'})
        self.run_target()
        self.manager.stop.assert_not_called()
        self.assertEqual(self.report.emit.call_args.args[0]['status'],'ERROR')

    def test_invalid_state_and_missing_identity_are_rejected_before_mutation(self):
        for item in ({'status':'Frozen','config':{'volatile.uuid':'id'}}, {'status':'Stopped','config':{}}):
            self.item = item
            with self.assertRaises(Error): self.run_target()
        self.manager.start.assert_not_called(); self.manager.stop.assert_not_called()
        self.challenge.run_target.assert_not_called()

    def test_prompt_retries_invalid_name_and_explicit_target_does_not_prompt(self):
        ui = Mock(); ui.input.side_effect = ['bad/name','fixture']
        self.manager.list.return_value = []
        output=Output(io.StringIO())
        with patch.object(security,'interactive',side_effect=lambda callback:callback(ui)) as prompt:
            self.assertEqual(security.choose_target(self.manager,None,output),'fixture')
            self.assertEqual(security.choose_target(self.manager,'fixture',output),'fixture')
        prompt.assert_called_once()
        self.assertEqual(ui.input.call_count,2)

    def test_noninteractive_missing_target_and_cancellation_do_not_choose_implicitly(self):
        self.manager.list.return_value=[]
        with patch.object(security,'interactive',side_effect=OSError('no tty')):
            with self.assertRaisesRegex(Error,'requires TARGET'):
                security.choose_target(self.manager,None,Output(io.StringIO()))
        ui=Mock();ui.input.return_value=''
        with patch.object(security,'interactive',side_effect=lambda callback:callback(ui)):
            with self.assertRaises(security.Cancelled):
                security.choose_target(self.manager,None,Output(io.StringIO()))

    def test_host_guard_rejects_container_before_target_selection(self):
        with patch.dict(os.environ,{'container':'lxc'}), patch.object(security,'choose_target') as select, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(security.main(['fixture']),2)
        select.assert_not_called()

    def test_suite_challenge_is_last_and_is_not_run_after_functional_failure(self):
        suite=Suite.__new__(Suite);suite.output=Output(io.StringIO());suite.results={}
        calls=[]
        suite.functional_tests=lambda:calls.append('functional')
        suite.security_fixture=lambda:calls.append('challenge')
        suite.run()
        self.assertEqual(calls,['functional','challenge'])
        suite.functional_tests=Mock(side_effect=Error('functional failure'))
        suite.security_fixture=Mock()
        with self.assertRaises(Error):suite.run()
        suite.security_fixture.assert_not_called()

    def test_final_fixture_is_fresh_owned_and_uses_standard_creation_and_start(self):
        suite=Suite.__new__(Suite);suite.targets=['functional-fixture']
        calls=[]
        suite.cli=lambda *args:calls.append(args)
        suite.state=Mock(return_value=True)
        suite.isolation_runtime=lambda target:calls.append(('challenge',target))
        suite.security_fixture()
        target=suite.targets[-1]
        self.assertNotEqual(target,'functional-fixture')
        self.assertEqual(calls,[('new',target),('start',target),('challenge',target)])
        suite.cli=Mock(side_effect=Error('new failed'))
        with self.assertRaises(Error):suite.security_fixture()
        self.assertEqual(len(suite.targets),3)  # Registered even when creation fails.

    def test_independent_download_verifies_only_tester_and_never_installs_product(self):
        data=b'tester'
        selected={'tag_name':'v9.9.9','assets':[{'name':name,'browser_download_url':name} for name in ('mas-test.pyz','SHA256SUMS')]}
        for valid in (True,False):
            def download(name):
                return ((hashlib.sha256(data).hexdigest() if valid else '0'*64)+'  mas-test.pyz\n').encode() if name=='SHA256SUMS' else data
            with self.subTest(valid=valid), patch.object(sys,'argv',['bootstrap','--security','fixture']), \
                    patch.object(bootstrap,'release',return_value=selected),patch.object(bootstrap,'download',side_effect=download) as fetch, \
                    patch.object(bootstrap,'choose_language') as language,patch.object(bootstrap.subprocess,'call',return_value=0) as call, \
                    contextlib.redirect_stdout(io.StringIO()):
                if valid:
                    self.assertEqual(bootstrap.main(),0)
                    self.assertEqual(call.call_args.args[0][2:],['--security','fixture'])
                else:
                    with self.assertRaises(RuntimeError):bootstrap.main()
                    call.assert_not_called()
                language.assert_not_called()
                self.assertEqual([c.args[0] for c in fetch.call_args_list],['SHA256SUMS','mas-test.pyz'])

    def test_gpu_off_functional_check_covers_nodes_mappings_and_managed_files(self):
        suite=Suite.__new__(Suite);suite.manager=Mock()
        disabled={'enabled':False,'devices':{}}
        suite.manager.info.return_value={'devices':{'root':{}},'config':{}}
        suite.manager.gpu.record.return_value=disabled
        initial={'backend':'wsl-nvidia','resources':{'driver_paths':['/usr/lib/wsl/drivers/owned'],'devices':{'mas-gpu-lib':{'type':'disk','path':'/usr/lib/wsl/lib'}}}}
        suite.gpu_off_access('fixture',initial,disabled)
        source=suite.manager.lxd.command.call_args.args[0][-1]
        for path in ('/dev/dxg','/dev/nvidia','/usr/lib/wsl/lib/libcuda.so.1','/usr/lib/wsl/drivers/owned','mas-gpu.conf','mas-gpu.sh'):
            self.assertIn(path,source)
        suite.manager.info.return_value['devices']['mas-gpu-lib']={}
        with self.assertRaises(AssertionError):suite.gpu_off_access('fixture',initial,disabled)

    def test_interrupted_start_waits_for_its_daemon_operation_before_standard_stop(self):
        self.item['status']='Stopped'
        self.manager.start.side_effect=KeyboardInterrupt()
        api=self.manager.lxd.configuration
        api.endpoint.side_effect=lambda path:path+'?project=fixture-project'
        operation=dict(id='11111111-1111-1111-1111-111111111111',class_='task',status_code=103,
                       resources={'containers':['/1.0/instances/fixture?project=fixture-project']})
        operation['class']=operation.pop('class_')
        calls=[]
        def request(method,path):
            calls.append(path)
            if '/wait?' in path:
                self.item['status']='Running'
                return ({'type':'sync','metadata':{'status_code':200,'err':''}},None)
            return ({'type':'sync','metadata':{'running':[operation]}},None)
        api.request.side_effect=request
        def stop(target):
            self.assertEqual(self.item['status'],'Running')
            self.assertTrue('/wait?' in calls[-1])
            self.item['status']='Stopped'
        self.manager.stop.side_effect=stop
        with self.assertRaises(KeyboardInterrupt):self.run_target()
        self.assertEqual(self.item['status'],'Stopped')
        self.assertEqual(self.report.data['lifecycle']['pending_operations'][0]['status_code'],200)

    def test_pending_operation_timeout_is_reported_without_racing_standard_stop(self):
        self.item['status']='Stopped';self.manager.start.side_effect=Error('start failed')
        operation={'id':'11111111-1111-1111-1111-111111111111','class':'task','status_code':103,
                   'resources':{'instances':['/1.0/instances/fixture']}}
        self.manager.lxd.configuration.request.side_effect=[({'type':'sync','metadata':{'running':[operation]}},None),
                                                           ({'type':'sync','metadata':{'status_code':103}},None)]
        with self.assertRaisesRegex(Error,'start failed'):self.run_target()
        self.manager.stop.assert_not_called()
        self.assertEqual(self.report.emit.call_args.args[0]['status'],'ERROR')

    def test_native_entity_url_selects_only_this_target_and_project(self):
        api=self.manager.lxd.configuration
        operation={'id':'11111111-1111-1111-1111-111111111111','class':'task','status_code':103,
                   'resources':{},'metadata':{'entity_url':'/1.0/instances/fixture?project=fixture-project'}}
        others=[dict(operation,metadata={'entity_url':path}) for path in
                ('/1.0/instances/other?project=fixture-project','/1.0/instances/fixture?project=other')]
        api.request.side_effect=[({'type':'sync','metadata':{'running':others+[operation]}},None),
                                 ({'type':'sync','metadata':{'status_code':200,'err':''}},None)]
        lifecycle={}
        security.settle_start(self.manager,'fixture',lifecycle,self.report)
        self.assertEqual(api.request.call_count,2)
        self.assertEqual(lifecycle['pending_operations'],[{'id':operation['id'],'status_code':200,'error':''}])

    def test_gpu_expectation_uses_the_configuration_after_standard_start(self):
        self.item['status']='Stopped'
        def start(target):
            self.item['status']='Running'
            self.manager.gpu.record.return_value={'enabled':True}
        self.manager.start.side_effect=start
        self.run_target()
        self.assertEqual(self.challenge.run_target.call_args.kwargs['gpu'],'on')
        self.assertEqual(self.report.data['gpu_expected'],'on')
        self.assertEqual(self.item['status'],'Stopped')

    def test_identity_is_rechecked_before_any_probe_after_start(self):
        self.item['status']='Stopped'
        self.manager.start.side_effect=lambda target:self.item.update(status='Running',config={'volatile.uuid':'replacement'})
        with self.assertRaisesRegex(Error,'identity changed'):self.run_target()
        self.challenge.run_target.assert_not_called()
        self.manager.stop.assert_not_called()
