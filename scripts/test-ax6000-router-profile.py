#!/usr/bin/env python3
"""Check the public router profile and the policy-neutral OpenClash adapter."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / 'configs/ax6000/files'
PROFILES = FILES / 'usr/share/openclash/profiles'


def load(path):
    return json.loads(subprocess.check_output([
        'ruby', '-ryaml', '-rjson', '-e',
        'puts JSON.generate(YAML.load_file(ARGV[0]))', str(path)]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mihomo', help='Optional native Mihomo executable')
    parser.add_argument('--geosite', type=Path, default=ROOT / 'artifacts/ax6000/image-files/etc/openclash/GeoSite.dat')
    args = parser.parse_args()
    base = load(PROFILES / 'AX6000_Base.yaml')
    ini = (PROFILES / 'AX6000_Router.ini').read_text()
    assert 'AX6000_Base.yaml' in ini
    assert 'ruleset=REJECT,[]DOMAIN,local.adguard.org' in ini
    assert '[]DOMAIN-SUFFIX,adguard.org' not in ini
    assert 'local.adguard.com' not in ini
    assert 'injections.adguard.org' not in ini
    tests = [line for line in ini.splitlines() if '`url-test`' in line]
    assert len(tests) == 18 and all(line.endswith('`600,5,100') for line in tests)
    assert base['find-process-mode'] == 'off'
    assert base['geo-auto-update'] is False and base['log-level'] == 'warning'
    dns = base['dns']
    upstreams = ['https://223.5.5.5/dns-query#DIRECT&h3=true',
                 'https://223.6.6.6/dns-query#DIRECT&h3=true', '119.29.29.29#DIRECT']
    assert dns['prefer-h3'] is True and dns['enhanced-mode'] == 'fake-ip'
    assert dns['respect-rules'] is False
    assert dns['nameserver'] == ['https://1.1.1.1/dns-query#🚀 节点选择',
                                  'https://8.8.8.8/dns-query#🚀 节点选择']
    assert dns['nameserver-policy'] == {'geosite:cn,private': upstreams}
    for key in ['proxy-server-nameserver', 'direct-nameserver']:
        assert dns[key] == upstreams
    hook = FILES / 'etc/openclash/custom/openclash_custom_overwrite.sh'
    env = dict(os.environ, AX6000_DNS_HELPER=str(
        FILES / 'usr/share/openclash/ax6000-dns-overwrite.rb'))
    with tempfile.TemporaryDirectory(prefix='ax6000-router-profile-') as directory:
        directory = Path(directory)
        path = directory / 'profile.yaml'
        # Simulate a later subscription edit: the adapter must not restore old policy.
        altered = copy.deepcopy(base)
        altered.update({'find-process-mode': 'always', 'geo-auto-update': True,
                        'log-level': 'info', 'rules': ['MATCH,DIRECT'],
                        'proxies': [{'name': 'kept', 'type': 'direct'}],
                        'proxy-groups': [{'name': 'automatic', 'type': 'url-test',
                            'proxies': ['kept'], 'interval': 30, 'lazy': False,
                            'tolerance': 5, 'url': 'https://example.com/'}]})
        altered['dns'].update({'listen': '0.0.0.0:7874', 'prefer-h3': False,
                              'nameserver': ['192.0.2.53'], 'enhanced-mode': 'redir-host'})
        altered['tun'] = {'enable': True, 'stack': 'system', 'dns-hijack': ['any:53']}
        path.write_text(json.dumps(altered, ensure_ascii=False))
        expected = copy.deepcopy(altered)
        expected['dns']['listen'] = '127.0.0.1:7874'
        expected['tun']['dns-hijack'] = []
        subprocess.run(['sh', str(hook), str(path)], env=env, check=True)
        assert load(path) == expected
        first = path.read_bytes()
        subprocess.run(['sh', str(hook), str(path)], env=env, check=True)
        assert path.read_bytes() == first
        # Converter emits YAML 1.2 string "off" without quotes; Ruby must retain it.
        path.write_text('find-process-mode: off\ndns:\n  enable: false\n  listen: 192.0.2.1:53\n')
        subprocess.run(['sh', str(hook), str(path)], env=env, check=True)
        assert load(path) == {'find-process-mode': 'off',
                             'dns': {'enable': False, 'listen': '192.0.2.1:53'}}
        # OpenClash's own YAML round trip can turn that string into false first.
        path.write_text('find-process-mode: false\ngeo-auto-update: false\n')
        subprocess.run(['sh', str(hook), str(path)], env=env, check=True)
        assert load(path) == {'find-process-mode': 'off', 'geo-auto-update': False}
        if args.mihomo:
            import shutil
            shutil.copyfile(args.geosite, directory / 'GeoSite.dat')
            effective = copy.deepcopy(base)
            effective['proxies'] = [{'name': 'kept', 'type': 'direct'}]
            effective['proxy-groups'] = [{'name': '🚀 节点选择', 'type': 'select', 'proxies': ['kept']}]
            effective['rules'] = ['DOMAIN,local.adguard.org,REJECT',
                                  'DOMAIN-SUFFIX,adguard.org,🚀 节点选择', 'MATCH,DIRECT']
            path.write_text(json.dumps(effective, ensure_ascii=False))
            subprocess.run([args.mihomo, '-t', '-d', str(directory), '-f', str(path)], check=True)
    print('PASS: public profile settings, 18 regional groups, policy preservation, YAML compatibility and idempotence.')


if __name__ == '__main__':
    main()
