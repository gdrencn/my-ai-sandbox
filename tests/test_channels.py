"""Channel routing must bind stable tests to the exact released product."""
import contextlib
import hashlib
import io
import json
import sys
import unittest
from unittest.mock import patch
import bootstrap


class ChannelTests(unittest.TestCase):
    def test_stable_resolution_rejects_prerelease_and_wrong_pin(self):
        stable = dict(tag_name='stable/0.1.15', prerelease=False, draft=False)
        with patch.object(bootstrap, 'download', return_value=json.dumps(stable).encode()):
            self.assertEqual(bootstrap.release(channel='stable'), stable)
            with self.assertRaises(RuntimeError): bootstrap.release('0.2.6', channel='stable')
        with patch.object(bootstrap, 'download', return_value=json.dumps({**stable, 'prerelease': True}).encode()):
            with self.assertRaises(RuntimeError): bootstrap.release(channel='stable')

    def test_stable_install_and_test_bind_exact_assets(self):
        data = {'mas.pyz': b'product', 'mas-install.pyz': b'installer', 'mas-test.pyz': b'tester'}
        sums = {name: hashlib.sha256(value).hexdigest() for name, value in data.items()}
        def release(tag, prefix):
            return dict(tag_name=tag, assets=[dict(name=name,browser_download_url=prefix+name)
                        for name in (*data, 'SHA256SUMS')])
        stable, paired = release('stable/0.1.15','stable/'), release('v0.1.15','test/')
        for test in (False, True):
            for mismatch in (False, True):
                with self.subTest(test=test,mismatch=mismatch):
                    def fetch(url):
                        prefix, name = url.split('/')
                        if name=='SHA256SUMS':
                            checks = dict(sums)
                            if mismatch and prefix=='test': checks['mas.pyz']='0'*64
                            return ''.join(h+'  '+n+'\n' for n,h in checks.items()).encode()
                        return data[name]
                    with patch.object(sys,'argv',['bootstrap','--channel','stable','--language','zh_cn']+(['--test'] if test else [])), \
                         patch.object(bootstrap,'choose_language'), \
                         patch.object(bootstrap,'release',side_effect=[stable,paired] if test else [stable]) as resolve, \
                         patch.object(bootstrap,'download',side_effect=fetch) as downloads, \
                         patch.object(bootstrap.subprocess,'call',return_value=0) as call, \
                         contextlib.redirect_stdout(io.StringIO()):
                        if test and mismatch:
                            with self.assertRaises(RuntimeError): bootstrap.main()
                            call.assert_not_called()
                        else:
                            self.assertEqual(bootstrap.main(),0)
                            self.assertTrue(call.call_args.args[0][1].endswith('mas-test.pyz' if test else 'mas-install.pyz'))
                            urls = [item.args[0] for item in downloads.call_args_list]
                            self.assertIn('stable/mas.pyz', urls)
                            self.assertIn('stable/mas-install.pyz', urls)
                            self.assertNotIn('test/mas.pyz', urls)
                            self.assertNotIn('test/mas-install.pyz', urls)
                            self.assertEqual('test/mas-test.pyz' in urls, test)
                        if test: self.assertEqual(resolve.call_args.args, ('0.1.15',))

    def test_pinned_resolution_rejects_wrong_tag_and_draft(self):
        for result in (dict(tag_name='v0.2.23', draft=False), dict(tag_name='v0.2.24', draft=True)):
            with self.subTest(result=result), patch.object(bootstrap, 'download', return_value=json.dumps(result).encode()):
                with self.assertRaises(RuntimeError):
                    bootstrap.release('0.2.24')

    def test_stable_pair_failure_never_installs_or_falls_back(self):
        stable = dict(tag_name='stable/0.2.24', assets=[dict(name='SHA256SUMS', browser_download_url='sums'),
                      dict(name='mas.pyz', browser_download_url='product'),
                      dict(name='mas-install.pyz', browser_download_url='installer')])
        sums = b'0  mas.pyz\n0  mas-install.pyz\n'
        for paired in (RuntimeError('missing paired release'), dict(tag_name='v0.2.25', assets=[])):
            with self.subTest(paired=paired), patch.object(sys, 'argv', ['bootstrap', '--channel', 'stable', '--test', '--language', 'zh_cn']), \
                 patch.object(bootstrap, 'choose_language'), patch.object(bootstrap, 'release', side_effect=[stable, paired]) as resolve, \
                 patch.object(bootstrap, 'download', return_value=sums) as downloads, \
                 patch.object(bootstrap.subprocess, 'call') as call, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError): bootstrap.main()
                self.assertEqual(resolve.call_args.args, ('0.2.24',))
                self.assertEqual(downloads.call_count, 1)
                call.assert_not_called()

    def test_stable_requires_installer_without_legacy_fallback(self):
        stable = dict(tag_name='stable/0.2.24', assets=[dict(name='SHA256SUMS', browser_download_url='sums'),
                      dict(name='mas.pyz', browser_download_url='product')])
        with patch.object(sys, 'argv', ['bootstrap', '--channel', 'stable', '--language', 'zh_cn']), \
             patch.object(bootstrap, 'choose_language'), patch.object(bootstrap, 'release', return_value=stable), \
             patch.object(bootstrap, 'download', return_value=b'0  mas.pyz\n') as downloads, \
             patch.object(bootstrap.subprocess, 'call') as call, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError): bootstrap.main()
            self.assertEqual(downloads.call_count, 1)
            call.assert_not_called()

    def test_stable_corrupt_product_is_rejected_before_installation(self):
        stable = dict(tag_name='stable/0.2.24', assets=[dict(name=name, browser_download_url=name)
                      for name in ('SHA256SUMS', 'mas.pyz', 'mas-install.pyz')])
        def fetch(name):
            return b'0  mas.pyz\n0  mas-install.pyz\n' if name == 'SHA256SUMS' else b'corrupt'
        with patch.object(sys, 'argv', ['bootstrap', '--channel', 'stable', '--language', 'zh_cn']), \
             patch.object(bootstrap, 'choose_language'), patch.object(bootstrap, 'release', return_value=stable), \
             patch.object(bootstrap, 'download', side_effect=fetch), \
             patch.object(bootstrap.subprocess, 'call') as call, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError): bootstrap.main()
            call.assert_not_called()
