from pathlib import Path
import json
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform == 'darwin', 'macOS integration')
class MacTests(unittest.TestCase):
    def test_crashed_companion_socket_is_reclaimed_without_displacing_live_server(self):
        from PySide6.QtWidgets import QApplication
        from lyxai.instance import InstanceServer
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', LYXAI_DATA_DIR=tmp):
            code = 'import os;from PySide6.QtCore import QCoreApplication;from lyxai.instance import InstanceServer;a=QCoreApplication([]);s=InstanceServer();assert s.listen();os._exit(0)'
            subprocess.run([sys.executable, '-c', code], check=True, timeout=5)
            receiver = InstanceServer(app)
            self.assertTrue(receiver.listen())
            contender = InstanceServer(app)
            self.assertFalse(contender.listen())
            receiver.server.close()
            receiver.lock.unlock()

    def test_missing_server_times_out_and_releases_handles(self):
        from lyxai.macos import MacLyXServer
        with tempfile.TemporaryDirectory() as tmp:
            server = MacLyXServer(str(Path(tmp)/'absent'), timeout=.04)
            with self.assertRaises(TimeoutError):
                server.command('query')
            self.assertFalse(server.handles)
            self.assertIsNone(server.lock)
            with self.assertRaises(ValueError):
                server.command('paste\ncommand')

    def test_bundle_launcher_preserves_spaces_unicode_and_flags(self):
        from lyxai.integration import menu_text
        app = '/tmp/中文 Name/LyXAI.app'
        command = [app+'/Contents/MacOS/LyXAI', '--lyx-user-dir', '/tmp/中文 user']
        text = menu_text('Menu "context-edit"\nEnd\n', command)
        encoded = re.findall(r'Item "[^"]*" "((?:\\.|[^"\\])*)"', text)
        for line, flags in zip(encoded, ([], ['--context-before'], ['--context-after'])):
            decoded = re.sub(r'\\(.)', r'\1', line)
            launch = decoded.split('vc-command U . "', 1)[1][:-1]
            values = shlex.split(launch)
            self.assertEqual(values[:5], ['/usr/bin/open', '-n', Path(app).as_uri().replace('.app', '%2Eapp'), '--args', '--encoded-args'])
            self.assertEqual(json.loads(bytes.fromhex(values[5]).decode()), command[1:]+['--from-lyx']+flags)
            self.assertNotIn("'", launch)
            self.assertNotIn('.app ', launch)

    def test_failed_config_commit_keeps_previous_keychain_credentials(self):
        from lyxai.core import Store
        entries = {}
        def keychain(account, raw=None, *, delete=False):
            if delete:
                entries.pop(account)
            elif raw is not None:
                entries[account] = raw
            else:
                return entries[account]
        with tempfile.TemporaryDirectory() as tmp, patch('lyxai.macos.keychain', keychain):
            store = Store(Path(tmp))
            config = store.load()
            config['profiles'][0]['api_key'] = 'first-placeholder'
            store.save(config)
            original = store.path.read_bytes()
            accounts = set(entries)
            config['profiles'][0]['api_key'] = 'second-placeholder'
            with patch('lyxai.core.atomic_write', side_effect=OSError('disk full')):
                with self.assertRaisesRegex(OSError, 'disk full'):
                    store.save(config)
            self.assertEqual(store.path.read_bytes(), original)
            self.assertEqual(set(entries), accounts)
            self.assertEqual(Store(Path(tmp)).load()['profiles'][0]['api_key'], 'first-placeholder')
            store.save(config)
            self.assertEqual(len(entries), 1)
            self.assertNotIn('second-placeholder', store.path.read_text())
            self.assertEqual(Store(Path(tmp)).load()['profiles'][0]['api_key'], 'second-placeholder')


if __name__ == '__main__':
    unittest.main()
