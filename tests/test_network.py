"""Conditional NIC changes and effective isolation, including preserved MACs."""
import copy
import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

from mas.core import Error, MANAGED
from mas.gpu import GPU
from mas.isolation import BASE_CONFIG, Isolation, PROFILE, PROFILE_KEY
from mas.network import KEY, MASK, Network, record
from mas.terminal_ui import UI


class NetworkTests(unittest.TestCase):
    def setUp(self):
        language = patch('mas.config.language', return_value='en_us')
        language.start();self.addCleanup(language.stop)
        self.manager=Mock();self.manager.lxd.project='mas'
        self.manager.gpu=GPU(self.manager)
        self.policy=Isolation(self.manager);self.manager.isolation=self.policy
        self.baseline={'version':1,'pool':'default','network':'lxdbr0','backends':[],'driver_paths':[]}
        self.project={'config':self.policy.project_config(self.baseline)}
        self.profile={'config':{**BASE_CONFIG,PROFILE_KEY:'1'},'devices':self.policy.devices(self.baseline)}
        self.policy.resource=Mock(side_effect=lambda kind,name:(copy.deepcopy(self.project if kind=='projects' else self.profile),'"etag"','/fixture'))
        self.policy.check_network=Mock()
        self.item=dict(name='fixture',type='container',status='Stopped',profiles=[PROFILE],devices={},
            config={MANAGED:'true','volatile.uuid':'original','volatile.eth0.hwaddr':'00:16:3e:01:02:03'},
            expanded_config={**BASE_CONFIG,MANAGED:'true'},expanded_devices=self.policy.devices(self.baseline))
        def require(target,stopped=False):
            if stopped and self.item['status']!='Stopped':raise Error('must stop first')
            return copy.deepcopy(self.item)
        self.manager.require.side_effect=require
        self.api=self.manager.lxd.configuration
        self.api.read.side_effect=lambda target:(copy.deepcopy(self.item),'"version"')
        def write(target,value,etag,**kw):
            self.item=copy.deepcopy(value)
            self.item['expanded_config']={**self.profile['config'],**self.item['config']}
            devices={**self.profile['devices'],**self.item['devices']}
            self.item['expanded_devices']={k:v for k,v in devices.items() if v!=MASK}
        self.api.write.side_effect=write
        self.network=Network(self.manager)

    def test_default_query_checks_policy_without_writing(self):
        self.assertEqual(self.network.status('fixture'),{'enabled':True,'configured':False,'resources':None})
        self.api.write.assert_not_called()

    def test_disable_and_enable_preserve_mac_and_unrelated_devices(self):
        self.item['devices']['placeholder']=MASK.copy()
        before=copy.deepcopy(self.item)
        for enabled in (False,False,True,True):
            saved=self.network.set('fixture',enabled)
            self.assertEqual(saved['restore']['hwaddr'],before['config']['volatile.eth0.hwaddr'])
            self.assertEqual(self.item['devices']['eth0'],saved['restore'] if enabled else MASK)
            self.assertEqual(self.item['devices']['placeholder'],MASK)
            self.policy.audit(self.item)
        self.assertTrue(record(self.item)['enabled'])
        self.assertTrue(all(call.args[2]=='"version"' for call in self.api.write.call_args_list))
        self.assertEqual(self.profile['devices'],self.policy.devices(self.baseline))

    def test_running_changes_and_invalid_values_do_not_write(self):
        self.item['status']='Running'
        with self.assertRaisesRegex(Error,'stop'):self.network.set('fixture',False)
        for value in ('off',0,None):
            with self.assertRaises(Error):self.network.set('fixture',value)
        self.api.write.assert_not_called()

    def test_nic_drift_and_extra_nic_are_refused_without_repairs(self):
        self.network.set('fixture',False);self.api.write.reset_mock()
        self.item['devices']['eth0']={'type':'nic','name':'eth0','network':'other'}
        with self.assertRaises(Error):self.network.set('fixture',True)
        self.item['devices']['eth0']=MASK.copy()
        self.item['expanded_devices']['extra']=self.profile['devices']['eth0'].copy()
        with self.assertRaises(Error):self.network.status('fixture')
        self.api.write.assert_not_called()

    def test_state_identity_and_concurrent_device_change_are_refused(self):
        for key,value in (('status','Running'),('config',{MANAGED:'true','volatile.uuid':'replacement'}),
                          ('devices',{'other':MASK})):
            changed={**copy.deepcopy(self.item),key:value}
            self.api.read.side_effect=None;self.api.read.return_value=(changed,'"version"')
            with self.assertRaises(Error):self.network.set('fixture',False)
        self.api.write.assert_not_called()

    def test_stale_etag_is_not_retried_or_reported_as_success(self):
        failure=Error('configuration changed')
        self.api.write.side_effect=failure
        with self.assertRaises(Error) as caught:self.network.set('fixture',False)
        self.assertIs(caught.exception,failure)
        self.api.write.assert_called_once();self.manager._completed.assert_not_called()
        self.assertNotIn(KEY,self.item['config'])

    def test_invalid_record_cannot_authorize_an_unapproved_network_or_properties(self):
        valid={'version':1,'enabled':False,'restore':self.profile['devices']['eth0']}
        for value in ([],None,True,{**valid,'enabled':'false'},{**valid,'version':True},
                      {**valid,'restore':{**valid['restore'],'source':'/host'}},
                      {**valid,'restore':{**valid['restore'],'network':'other'}}):
            self.item['config'][KEY]=json.dumps(value);self.item['devices']['eth0']=MASK.copy()
            self.item['expanded_devices'].pop('eth0',None)
            with self.assertRaises(Error):self.policy.audit(self.item)
        self.api.write.assert_not_called()

    def test_post_write_replacement_is_not_a_success(self):
        def write(*args,**kw):self.item['config']['volatile.uuid']='replacement'
        self.api.write.side_effect=write
        with self.assertRaises(Error):self.network.set('fixture',False)
        self.manager._completed.assert_not_called()

    def test_network_menu_remains_without_gpu_and_reuses_standard_backend(self):
        for language in ('zh_cn','en_us'):
            view,manager=Mock(),Mock()
            manager.hardware.side_effect=[{'available':False,'enabled':False},{'enabled':True}, {'enabled':False}]
            view.choose.side_effect=['network',False,None,None]
            with patch('mas.config.language',return_value=language),contextlib.redirect_stdout(io.StringIO()):
                UI(view,manager).hardware('fixture')
            choices=view.choose.call_args_list[0].args[1]
            self.assertEqual([value for value,label in choices],['network',None])
            manager.hardware.assert_any_call('fixture',False,item='network')
            self.assertFalse(view.choose.call_args_list[1].kwargs['default'] is False)
