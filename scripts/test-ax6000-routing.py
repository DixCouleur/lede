#!/usr/bin/env python3
"""Check selective routing behavior against native fw3 rule fixtures.

Command shims isolate the production hook from the host and router firewalls.
"""
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SHIM = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
p = pathlib.Path(os.environ['ROUTING_STATE'])
s = json.loads(p.read_text()); a = sys.argv[1:]
name = pathlib.Path(sys.argv[0]).name
if name == 'uci':
    value = s['config'].get(a[-1])
    if value is None: sys.exit(1)
    print(value); sys.exit(0)
if name == 'ipset':
    if 'flush' in a: s['proxy_ips'] = []
    if 'add' in a: s['proxy_ips'].append(a[-1])
else:
    table = a[a.index('-t')+1]; action = a[2]; chain = a[3]
    key = table + '/' + chain
    if key not in s['rules']: sys.exit(1)
    rules = s['rules'][key]
    if action == '-S':
        print('-N ' + chain)
        for rule in rules: print('-A ' + chain + ' ' + ' '.join(rule))
        sys.exit(0)
    if action == '-L':
        for n, rule in enumerate(rules, 1): print(str(n) + ' ' + ' '.join(rule))
        sys.exit(0)
    if action == '-C': sys.exit(0 if a[4:] in rules else 1)
    if action == '-I': rules.insert(int(a[4])-1, a[5:])
    else: raise RuntimeError(a)
p.write_text(json.dumps(s))
'''


def fixture(mode):
    rules = {}
    local = '-m set --match-set localnetwork dst -j RETURN'
    reply = '-m conntrack --ctdir REPLY -j RETURN'
    owner = '-m owner --gid-owner 65534 -j RETURN'
    china = '-m set --match-set china_ip_route dst -m set ! --match-set china_ip_route_pass dst -j RETURN'
    for chain in ('openclash', 'openclash_output'):
        exemptions = [local, reply] if chain == 'openclash' else [owner, local, reply]
        mark = '-j MARK --set-xmark 0x162/0xffffffff'
        if mode != 'fake-ip-tun':
            redirect = '-p tcp -j REDIRECT --to-ports 7892'
            ordered = exemptions + ['-d 198.18.0.0/16 ' + redirect, china, redirect]
            if chain == 'openclash_output':
                ordered = [owner, '-d 198.18.0.0/16 ' + redirect, local, reply, china, redirect]
            rules['nat/' + chain] = [x.split() for x in ordered]
        proto = '' if mode == 'fake-ip-tun' else '-p udp '
        action = mark if mode != 'fake-ip' or chain == 'openclash_output' else (
            '-j TPROXY --on-port 7895 --on-ip 0.0.0.0 --tproxy-mark 0x162/0xffffffff')
        rules['mangle/' + chain] = [x.split() for x in exemptions + [
            '-d 198.18.0.0/16 ' + proto + action, china, proto + action]]
    return dict(config={'mosdns.config.ax6000_split': '1', 'openclash.config.en_mode': mode},
                rules=rules, proxy_ips=[])


def route(rules, destination, protocol, proxy_ips, owner=False, reply=False):
    ip = ipaddress.ip_address(destination)
    sets = {'localnetwork': ['192.168.0.0/16'],
            'china_ip_route': ['111.0.0.0/8', '149.154.160.0/20'],
            'china_ip_route_pass': [], 'ax6000_proxy_ip': proxy_ips}
    for rule in rules:
        matches, invert, n = True, False, 0
        while n < len(rule):
            token = rule[n]
            if token == '!': invert = True; n += 1; continue
            if token == '-m': n += 2; continue
            if token == '-j':
                if matches: return rule[n+1]
                break
            if token == '-d': matched = ip in ipaddress.ip_network(rule[n+1]); n += 2
            elif token == '-p': matched = protocol == rule[n+1]; n += 2
            elif token == '--gid-owner': matched = owner; n += 2
            elif token == '--ctdir': matched = reply if rule[n+1] == 'REPLY' else not reply; n += 2
            elif token == '--match-set':
                matched = any(ip in ipaddress.ip_network(x) for x in sets[rule[n+1]])
                n += 3
            else: raise AssertionError(('Unsupported fixture matcher', rule, token))
            matches &= not matched if invert else matched
            invert = False
    return 'RETURN'


def main():
    with tempfile.TemporaryDirectory(prefix='ax6000-routing-') as tmp:
        temp = Path(tmp)
        shim = temp/'shim'; shim.write_text(SHIM); shim.chmod(0o755)
        for name in ('uci', 'ipset', 'iptables'): (temp/name).symlink_to(shim)
        proxy = temp/'proxy.txt'; proxy.write_text('149.154.160.0/20\n')
        custom = temp/'custom.txt'; custom.write_text('203.0.113.0/24\n')
        source = (ROOT/'configs/ax6000/files/etc/openclash/custom/openclash_custom_firewall_rules.sh').read_text()
        source = source.replace('. /usr/share/openclash/log.sh', 'LOG_OUT() { :; }')
        source = source.replace('/etc/mosdns/data/proxy-ip.txt', str(proxy))
        source = source.replace('/etc/openclash/custom/openclash_custom_chnroute_pass.list', str(custom))
        hook = temp/'hook.sh'; hook.write_text(source)
        state_file = temp/'state.json'
        env = dict(os.environ, PATH=str(temp)+os.pathsep+os.environ['PATH'], ROUTING_STATE=str(state_file))
        for mode in ('fake-ip', 'fake-ip-mix', 'fake-ip-tun'):
            original = fixture(mode); state_file.write_text(json.dumps(original))
            subprocess.run(['sh', str(hook)], env=env, check=True)
            changed = json.loads(state_file.read_text())
            assert sorted(changed['proxy_ips']) == ['149.154.160.0/20', '203.0.113.0/24']
            for key, rules in changed['rules'].items():
                # Native rules remain in order, preserving ports, marks and exemptions.
                old = original['rules'][key]; position = 0
                for rule in rules:
                    if position < len(old) and rule == old[position]: position += 1
                assert position == len(old), key
                protocol = 'tcp' if key.startswith('nat') or mode == 'fake-ip-tun' else 'udp'
                fake_action = route(rules, '198.18.0.42', protocol, changed['proxy_ips'])
                assert fake_action in ('REDIRECT', 'TPROXY', 'MARK'), (key, fake_action)
                for ip in ('149.154.160.42', '203.0.113.42'):
                    assert route(rules, ip, protocol, changed['proxy_ips']) == fake_action, (key, ip)
                for ip in ('111.30.0.1', '8.8.8.8', '192.168.199.1'):
                    assert route(rules, ip, protocol, changed['proxy_ips']) == 'RETURN', (key, ip)
                if key.endswith('openclash_output'):
                    assert route(rules, '198.18.0.42', protocol, changed['proxy_ips'], owner=True) == 'RETURN'
                assert route(rules, '149.154.160.42', protocol, changed['proxy_ips'], reply=True) == 'RETURN'
            subprocess.run(['sh', str(hook)], env=env, check=True)
            assert json.loads(state_file.read_text()) == changed, 'Repeated hook duplicated rules'
            print(f'PASS: {mode} keeps native exemptions/ports/marks; Fake-IP and proxy CIDRs route through core, real IPs bypass; repeated execution is idempotent.')
        for config, code in (({'mosdns.config.ax6000_split': '0'}, 0),
                             ({'openclash.config.en_mode': 'redir-host'}, 1)):
            state = fixture('fake-ip'); state['config'].update(config)
            state_file.write_text(json.dumps(state))
            assert subprocess.run(['sh', str(hook)], env=env).returncode == code
            assert json.loads(state_file.read_text()) == state
        state = fixture('fake-ip'); state['rules'] = {}; state_file.write_text(json.dumps(state))
        assert subprocess.run(['sh', str(hook)], env=env).returncode == 1
        print('PASS: disabled split DNS and unsupported modes leave native routing unchanged; missing native Fake-IP rules report failure.')


if __name__ == '__main__':
    main()
