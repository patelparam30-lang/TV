"""Check identity isolation and public packaging without SDK credentials or a TV."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as XML
import zipfile

from font_assets import ROOT

spec = importlib.util.spec_from_file_location('personal_export', ROOT / 'scripts/export-personal.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PersonalExport(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='cleanframe-personal-test-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.identity = self.root / 'config.xml'
        self.output = self.root / 'personal.wgt'
        self.configure()

    def configure(self, package='pTestHome1', platform='9.0', profile='tv-samsung'):
        self.identity.write_text('''<widget xmlns="http://www.w3.org/ns/widgets" xmlns:tizen="http://tizen.org/ns/widgets" id="https://example.test/personal-home">
<name>Personal &amp; Home</name><tizen:application package="''' + package + '" id="' + package + '.PersonalHome" required_version="' + platform + '"/><tizen:profile name="' + profile + '"/></widget>')

    def test_manifest_self_filter_and_sources(self):
        before = {p: p.read_bytes() for p in [ROOT / 'app/config.xml', ROOT / 'app/device.js', ROOT / 'app/main.js']}
        report = module.export(self.identity, self.output, '9.0')
        with zipfile.ZipFile(self.output) as archive:
            manifest = XML.fromstring(archive.read('config.xml'))
            app = manifest.find('{http://tizen.org/ns/widgets}application')
            self.assertEqual(app.get('id'), 'pTestHome1.PersonalHome')
            self.assertEqual(app.get('package'), 'pTestHome1')
            self.assertEqual(app.get('required_version'), '9.0')
            self.assertEqual(manifest.get('id'), 'https://example.test/personal-home')
            self.assertEqual(manifest.findtext('{http://www.w3.org/ns/widgets}name'), 'Personal & Home')
            self.assertIn(b'var SELF = "pTestHome1.PersonalHome";', archive.read('device.js'))
            self.assertNotIn(b"var SELF = 'nClrkHome1.FrameHome';", archive.read('device.js'))
            self.assertEqual(archive.read('main.js'), before[ROOT / 'app/main.js'])
            self.assertIn(b'api.open-meteo.com', archive.read('config.xml'))
            self.assertIn('LICENSE', archive.namelist())
            self.assertIn('THIRD_PARTY_NOTICES.md', archive.namelist())
            self.assertNotIn('signature1.xml', archive.namelist())
            self.assertFalse(any(n.startswith('assets/private-fonts/') for n in archive.namelist()))
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertFalse(report['signed'])
        self.assertEqual(report['sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(json.loads(self.output.with_suffix('.json').read_text()), report)

    def test_rejects_reference_identity(self):
        with self.assertRaisesRegex(ValueError, 'own SDK identity'):
            module.export(ROOT / 'app/config.xml', self.output, '9.0')
        self.assertFalse(self.output.exists())

    def test_rejects_wrong_profile_and_platform(self):
        for profile, platform in [('mobile', '9.0'), ('tv-samsung', '10.0')]:
            with self.subTest(profile=profile, platform=platform):
                self.configure(profile=profile, platform=platform)
                with self.assertRaises(ValueError):
                    module.export(self.identity, self.output, '9.0')
                self.assertFalse(self.output.exists())

    def test_old_tv_template_preserves_launcher_minimum(self):
        self.configure(platform='2.3', profile='tv')
        report = module.export(self.identity, self.output, '9.0')
        self.assertEqual(report['required_version'], '6.5')
        self.assertEqual(report['sdk_template_required_version'], '2.3')
        with zipfile.ZipFile(self.output) as archive:
            manifest = XML.fromstring(archive.read('config.xml'))
            self.assertEqual(manifest.find('{http://tizen.org/ns/widgets}profile').get('name'), 'tv-samsung')
            self.assertEqual(manifest.find('{http://tizen.org/ns/widgets}application').get('required_version'), '6.5')
        with self.assertRaisesRegex(ValueError, 'newer than'):
            module.export(self.identity, self.root / 'unsupported.wgt', '5.0')

    def test_rejects_invalid_identity(self):
        self.configure(package='not a package')
        with self.assertRaisesRegex(ValueError, 'Invalid SDK'):
            module.export(self.identity, self.output, '9.0')
        self.assertFalse(self.output.exists())

    def test_preserves_existing_files_without_force(self):
        self.output.write_bytes(b'existing user package')
        with self.assertRaises(FileExistsError):
            module.export(self.identity, self.output, '9.0')
        self.assertEqual(self.output.read_bytes(), b'existing user package')
        module.export(self.identity, self.output, '9.0', force=True)
        with zipfile.ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())


if __name__ == '__main__':
    unittest.main(verbosity=2)
