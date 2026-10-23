"""Offline guard, callback, and recovery tests. Never contacts a TV."""
import base64
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parent / 'native-home'
spec = importlib.util.spec_from_file_location('personal_home', SOURCE / 'personal-home.py')
home = importlib.util.module_from_spec(spec)
spec.loader.exec_module(home)
DEVICE = {'AppId': 'Abcdef1234.Launcher', 'Model': 'T-TEST-0090', 'Firmware': 'T-TEST-0090-1000.0'}
PREFERENCES = {key: 'example.original.home' for key in home.STRINGS}
INSPECTION = ('PARAMHOME_INSPECT_BEGIN\nuid=901(sdk) gid=901(sdk)\narmv7l\n'
              'Model=' + DEVICE['Model'] + ';\nVersion=' + DEVICE['Firmware'] + ';\n'
              '/usr/share/dotnet/shared/Microsoft.NETCore.App/6.0.9\n'
              + ''.join(key + ', value = ' + value + ' (String)\n' for key, value in PREFERENCES.items())
              + home.AUTO + ', value = 1 (Int32)\nPARAMHOME_INSPECT_END\n')
SNAPSHOT = {'Device': DEVICE, 'Home': 'example.original.home', 'Strings': PREFERENCES,
            'Uid': 901, 'Autostart': 1, 'BootSupported': 1}


class Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'recovery'
        self.root.mkdir()
        self.owner = {'Host': '127.0.0.1', 'Sdb': '/fake/sdb', 'Device': DEVICE,
                      'ExpectedStrings': PREFERENCES, 'ExpectedAutostart': 1}
        for name in home.OUTPUTS:
            target = self.root / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(b'offline fixture, not a binary')

    def test_typed_inspection(self):
        self.assertEqual(home.parse_inspection(INSPECTION, DEVICE['AppId']), (DEVICE, PREFERENCES, 1))

    def test_reject_incomplete_wrong_user_and_changed_types(self):
        for text in (INSPECTION.replace('PARAMHOME_INSPECT_END', ''),
                     INSPECTION.replace('uid=901(sdk)', 'uid=0(root)'),
                     INSPECTION.replace('(Int32)', '(String)'),
                     INSPECTION.replace('(String)', '(Int32)'),
                     INSPECTION.replace('6.0.9', '8.0.0')):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                home.parse_inspection(text, DEVICE['AppId'])

    def test_reject_applied_baseline(self):
        with self.assertRaises(RuntimeError):
            home.parse_inspection(INSPECTION.replace('example.original.home', DEVICE['AppId']), DEVICE['AppId'])

    def test_baseline_is_never_overwritten(self):
        original = self.root / 'original.json'
        home.save_new(original, SNAPSHOT)
        with self.assertRaises(FileExistsError):
            home.save_new(original, {'Home': 'wrong'})
        self.assertEqual(json.loads(original.read_text()), SNAPSHOT)

    def make_bundle(self):
        for name in home.FILES:
            (self.root / name).write_bytes((SOURCE / name).read_bytes())
        home.save_new(self.root / 'owner.json', self.owner)
        home.save_new(self.root / 'original.json', SNAPSHOT)
        home.save_new(self.root / 'integrity.json', {
            name: home.digest(self.root / name) for name in
            home.FILES + home.OUTPUTS + ('owner.json', 'original.json')})

    def test_bundle_detects_source_binary_and_original_tampering(self):
        self.make_bundle()
        home.verify_bundle(self.root)
        for name in ('personal-home.py', 'out/ParamHomeControl.dll', 'original.json', 'owner.json'):
            target = self.root / name
            before = target.read_bytes()
            target.write_bytes(before + b'changed')
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                home.verify_bundle(self.root)
            target.write_bytes(before)

    def test_bundle_rejects_omitted_integrity_entries(self):
        self.make_bundle()
        (self.root / 'integrity.json').write_text('{}')
        with self.assertRaises(RuntimeError):
            home.verify_bundle(self.root)

    def callback(self, result, status=0, incomplete=False, capability='9.0'):
        scripts = {}
        workers = []
        pushed = []

        def fake_run(command, **kwargs):
            if command[-1] == 'capability':
                output = 'vendor_name:Samsung\nplatform_version:' + capability + '\ncpu_arch:armv7\n'
            elif command[-1] == 'applist':
                output = "'Launcher' '" + DEVICE['AppId'] + "'\n"
            else:
                output = 'connected'
            if 'push' in command:
                pushed.append(command[-1])
                if command[-1].endswith('.sh'):
                    scripts[command[-1]] = Path(command[-2]).read_text()
            return subprocess.CompletedProcess(command, 0, output, '')

        class Process:
            def poll(self): return 0
            def wait(self, **kwargs): return 0

        def fake_popen(command, **kwargs):
            encoded = re.search(r'%s\$\{IFS\}([^|]+)\|base64', command[-1]).group(1)
            shell = base64.b64decode(encoded).decode()
            address, port = re.search(r'/dev/tcp/([^/]+)/([0-9]+)', shell).groups()
            remote = re.search(r';cat ([^|]+)\|bash', shell).group(1)
            script = scripts[remote]
            start = re.search(r'PARAMHOME_CONTROL_BEGIN_[a-f0-9]+', script).group(0)
            finish = re.search(r'PARAMHOME_CONTROL_END_[a-f0-9]+', script).group(0)
            action = re.search(r'\.dll (query|apply|restore) ', script).group(1)
            marker = {'query': 'QUERY', 'apply': 'APPLIED', 'restore': 'RESTORED'}[action]
            output = start + '\nPARAMHOME_' + marker + '=' + json.dumps(result) + '\n'
            if not incomplete:
                output += finish + ':' + str(status) + '\n'

            def send():
                with socket.create_connection((address, int(port)), timeout=2) as connection:
                    connection.sendall(output.encode())
            worker = threading.Thread(target=send)
            worker.start()
            workers.append(worker)
            return Process()

        with mock.patch.object(home.subprocess, 'run', side_effect=fake_run), \
                mock.patch.object(home.subprocess, 'Popen', side_effect=fake_popen):
            try:
                value = home.execute(self.root, self.owner, 'query')
            finally:
                for worker in workers:
                    worker.join(timeout=3)
        return value, pushed

    def test_bounded_query_transport_and_exact_runtime_names(self):
        result, pushed = self.callback(SNAPSHOT)
        self.assertEqual(result, SNAPSHOT)
        self.assertEqual(len(pushed), 5)
        for suffix in ('.dll', '.runtimeconfig.json', '.deps.json', '-device.json', '.sh'):
            self.assertTrue(any(name.endswith(suffix) for name in pushed))

    def test_failed_native_status_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, 'failed or result is incomplete'):
            self.callback(SNAPSHOT, status=1)

    def test_incomplete_callback_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, 'failed or result is incomplete'):
            self.callback(SNAPSHOT, incomplete=True)

    def test_native_result_identity_is_checked(self):
        changed = copy.deepcopy(SNAPSHOT)
        changed['Device']['AppId'] = 'Other12345.Launcher'
        with self.assertRaisesRegex(RuntimeError, 'identity differs'):
            self.callback(changed)

    def test_changed_capability_stops_before_staging(self):
        with self.assertRaisesRegex(RuntimeError, 'nothing staged'):
            self.callback(SNAPSHOT, capability='10.0')

    def prepare_args(self):
        inspection = self.root / 'inspection.txt'
        inspection.write_text(INSPECTION)
        sdb = self.root / 'fake-sdb'
        sdb.touch()
        return ['personal-home.py', 'prepare', '--host', '127.0.0.1', '--app-id', DEVICE['AppId'],
                '--inspection', str(inspection), '--sdb', str(sdb), '--recovery-dir', str(self.root)]

    def fake_build(self, root, download_sdk):
        for name in home.FILES:
            (root / name).write_bytes((SOURCE / name).read_bytes())

    def test_prepare_creates_complete_independent_backup_and_keeps_original(self):
        arguments = self.prepare_args()
        with mock.patch('sys.argv', arguments), mock.patch.object(home, 'build', side_effect=self.fake_build), \
                mock.patch.object(home, 'execute', return_value=copy.deepcopy(SNAPSHOT)) as execute:
            home.main()
            home.verify_bundle(self.root)
            backup = next(self.root.parent.glob('ParamHome-recovery-backup-*'))
            home.verify_bundle(backup)
            original = (self.root / 'original.json').read_bytes()
            home.main()
            self.assertEqual(execute.call_count, 1)
            self.assertEqual((self.root / 'original.json').read_bytes(), original)

    def test_ineligible_target_cannot_create_baseline(self):
        arguments = self.prepare_args()
        result = copy.deepcopy(SNAPSHOT)
        result['BootSupported'] = 0
        with mock.patch('sys.argv', arguments), mock.patch.object(home, 'build', side_effect=self.fake_build), \
                mock.patch.object(home, 'execute', return_value=result), self.assertRaisesRegex(RuntimeError, 'not eligible'):
            home.main()
        self.assertFalse((self.root / 'original.json').exists())

    def test_changed_preferences_cannot_create_baseline(self):
        arguments = self.prepare_args()
        result = copy.deepcopy(SNAPSHOT)
        result['Autostart'] = 0
        with mock.patch('sys.argv', arguments), mock.patch.object(home, 'build', side_effect=self.fake_build), \
                mock.patch.object(home, 'execute', return_value=result), self.assertRaisesRegex(RuntimeError, 'changed since inspection'):
            home.main()
        self.assertFalse((self.root / 'original.json').exists())


if __name__ == '__main__':
    # Callback fixtures use loopback sockets only; keep their protocol text quiet.
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main()
