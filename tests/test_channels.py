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
                         patch.object(bootstrap,'download',side_effect=fetch), \
                         patch.object(bootstrap.subprocess,'call',return_value=0) as call, \
                         contextlib.redirect_stdout(io.StringIO()):
                        if test and mismatch:
                            with self.assertRaises(RuntimeError): bootstrap.main()
                            call.assert_not_called()
                        else:
                            self.assertEqual(bootstrap.main(),0)
                            self.assertTrue(call.call_args.args[0][1].endswith('mas-test.pyz' if test else 'mas-install.pyz'))
                        if test: self.assertEqual(resolve.call_args.args, ('0.1.15',))
