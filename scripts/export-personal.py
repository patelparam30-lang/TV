"""Export an unsigned public-font widget using an owner's SDK-generated TV identity.

No signing profiles, passwords or devices are read. The checked-in manifest and
self-filter stay unchanged; only the generated archive receives the new identity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as XML
import zipfile

from font_assets import ROOT, write_widget_archive

WIDGET = 'http://www.w3.org/ns/widgets'
TIZEN = 'http://tizen.org/ns/widgets'
XML.register_namespace('', WIDGET)
XML.register_namespace('tizen', TIZEN)


def version(value):
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', value or ''):
        raise ValueError('Expected a numeric platform version, such as 9.0.')
    return tuple((list(map(int, value.split('.'))) + [0, 0])[:3])


def export(identity_path, output, target_platform, force=False):
    if identity_path.stat().st_size > 1024 * 1024:
        raise ValueError('The identity must be an SDK config.xml, not a package or certificate.')
    owner = XML.parse(identity_path).getroot()
    manifest = XML.parse(ROOT / 'app/config.xml').getroot()
    identity = owner.find('{' + TIZEN + '}application')
    profile = owner.find('{' + TIZEN + '}profile')
    base = manifest.find('{' + TIZEN + '}application')
    name = owner.findtext('{' + WIDGET + '}name', '').strip()
    if owner.tag != '{' + WIDGET + '}widget' or identity is None or profile is None or profile.get('name') not in ['tv', 'tv-samsung']:
        raise ValueError('Use config.xml from an SDK-generated Samsung TV Web Application.')
    package_id, app_id = identity.get('package', ''), identity.get('id', '')
    if not re.fullmatch(r'[A-Za-z0-9]{10}', package_id) or not re.fullmatch(re.escape(package_id) + r'\.[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}', app_id):
        raise ValueError('Invalid SDK package/application identity.')
    if package_id == base.get('package') or app_id == base.get('id'):
        raise ValueError('Create your own SDK identity; the reference owner’s identity is not a personal installation identity.')
    template_required = identity.get('required_version', '')
    # The Samsung 9.0 Empty template can still declare tv/2.3. Its identity is
    # usable, but the actual launcher assets must retain their own minimum.
    required = max([base.get('required_version'), template_required], key=version)
    if version(required) > version(target_platform):
        raise ValueError('The launcher requires ' + required + ', newer than the connected TV’s ' + target_platform + '.')
    widget_id = owner.get('id', '')
    if not name or len(name) > 80 or not widget_id or len(widget_id) > 1024:
        raise ValueError('The SDK project must include a display name and widget ID.')
    report_path = output.with_suffix('.json')
    if output.resolve() == report_path.resolve() or output.suffix.lower() != '.wgt':
        raise ValueError('Choose an output filename ending in .wgt.')
    if any(p.exists() for p in [output, report_path]) and not force:
        raise FileExistsError('Output already exists. Preserve it or explicitly use --force to replace it.')

    base.set('package', package_id)
    base.set('id', app_id)
    base.set('required_version', required)
    manifest.set('id', widget_id)
    manifest.find('{' + WIDGET + '}name').text = name
    manifest_bytes = XML.tostring(manifest, encoding='utf-8', xml_declaration=True)
    source = (ROOT / 'app/device.js').read_text()
    adapter, count = re.subn(r"(?m)^(\s*var SELF = )(['\"])[^'\"]+\2(;[ \t]*)$",
                             lambda match: match[1] + json.dumps(app_id) + match[3], source)
    if count != 1:
        raise ValueError('Could not locate the single application self-filter; refusing an inconsistent build.')

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='personal-export-', dir=output.parent) as folder:
        public = Path(folder) / 'base.wgt'
        widget = Path(folder) / 'personal.wgt'
        write_widget_archive(public, include_private=False)
        with zipfile.ZipFile(public) as original, zipfile.ZipFile(widget, 'w', zipfile.ZIP_DEFLATED, allowZip64=False) as result:
            for item in original.infolist():
                if item.filename in ['author-signature.xml', 'signature1.xml']:
                    raise ValueError('Unexpected signing files in source assets.')
                content = manifest_bytes if item.filename == 'config.xml' else adapter.encode() if item.filename == 'device.js' else original.read(item)
                result.writestr(item, content)
            for notice in ['LICENSE', 'THIRD_PARTY_NOTICES.md']:
                result.write(ROOT / notice, notice)
        with zipfile.ZipFile(widget) as result:
            if result.testzip() is not None:
                raise ValueError('Export integrity check failed.')
            actual = XML.fromstring(result.read('config.xml')).find('{' + TIZEN + '}application')
            if actual.get('id') != app_id or actual.get('package') != package_id:
                raise ValueError('Packaged manifest does not match the chosen identity.')
            if 'var SELF = ' + json.dumps(app_id) + ';' not in result.read('device.js').decode():
                raise ValueError('Packaged self-filter does not match the chosen identity.')
        widget.replace(output)
    report = {'file': output.name, 'name': name, 'package_id': package_id, 'app_id': app_id,
              'required_version': required, 'sdk_template_required_version': template_required, 'target_platform': target_platform,
              'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'signed': False, 'private_fonts': False,
              'scope': 'Personal identity and archive consistency only. Sign locally with your own Samsung profile; no TV contacted.'}
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', type=Path, required=True, help='config.xml from your SDK-generated TV Web Application')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/ParamHome-unsigned.wgt')
    parser.add_argument('--target-platform', default='9.0', help='Platform version reported by the connected TV')
    parser.add_argument('--force', action='store_true', help='Explicitly replace an existing output and its report')
    args = parser.parse_args()
    try:
        result = export(args.identity, args.output, args.target_platform, args.force)
    except (ValueError, OSError, XML.ParseError) as error:
        parser.exit(1, str(error) + '\n')
    print('Created unsigned widget: ' + str(args.output))
    print('Application: ' + result['app_id'] + ' (' + result['name'] + ')')
    print('Public fonts only. Sign on your Mac with your own Samsung profile. No TV contacted.')
