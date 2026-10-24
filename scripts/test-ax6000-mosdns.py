#!/usr/bin/env python3
"""Run real AdGuardHome and patched MosDNS against counted loopback DNS peers."""
import collections
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path):
    return json.loads(subprocess.check_output([
        'ruby', '-ryaml', '-rjson', '-e', 'puts JSON.generate(YAML.load_file(ARGV[0]))', str(path)]))


class Peer:
    def __init__(self, port, fake=False):
        self.fake, self.enabled = fake, True
        self.count = collections.Counter()
        self.delays, self.answers, self.rcodes = {}, {}, {}
        self.ttls = {}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', port))
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while True:
            try:
                data, peer = self.sock.recvfrom(4096)
                offset, labels = 12, []
                while data[offset]:
                    n = data[offset]; offset += 1
                    labels.append(data[offset:offset+n].decode()); offset += n
                name = '.'.join(labels)
                end = offset + 5
                self.count[name] += 1
                if not self.enabled:
                    continue
                time.sleep(self.delays.get(name, 0))
                rcode = self.rcodes.get(name, 3 if name == 'unknown-nxdomain.test' and not self.fake else None)
                if rcode is not None:
                    reply = data[:2] + struct.pack('!5H', 0x8180 | rcode, 1, 0, 0, 0) + data[12:end]
                    self.sock.sendto(reply, peer)
                    continue
                answer = ('198.18.0.' + str(self.count[name] + 10)) if self.fake else (
                    '1.0.0.1' if name in ('direct.test', 'unknown-cn.test') else '8.8.8.8')
                answer = self.answers.get(name, answer)
                reply = data[:2] + struct.pack('!5H', 0x8180, 1, 1, 0, 0) + data[12:end]
                reply += b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, self.ttls.get(name, 60), 4) + socket.inet_aton(answer)
                self.sock.sendto(reply, peer)
            except OSError:
                break


def lookup(name, qtype=1, tcp=False, port=15353, expected_rcode=0):
    labels = b''.join(bytes([len(x)]) + x.encode() for x in name.split('.'))
    query = struct.pack('!6H', 12345, 0x100, 1, 0, 0, 0) + labels + b'\0' + struct.pack('!HH', qtype, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as s:
        s.settimeout(8)
        if tcp:
            s.connect(('127.0.0.1', port)); s.sendall(struct.pack('!H', len(query)) + query)
            size = struct.unpack('!H', s.recv(2))[0]
            reply = b''
            while len(reply) < size:
                reply += s.recv(size-len(reply))
        else:
            s.sendto(query, ('127.0.0.1', port)); reply = s.recv(4096)
    assert struct.unpack_from('!H', reply)[0] == 12345
    assert struct.unpack_from('!H', reply, 2)[0] & 15 == expected_rcode, (name, reply)
    count = struct.unpack_from('!H', reply, 6)[0]
    return socket.inet_ntoa(reply[-4:]) if count else None


def main(mosdns, adguard):
    local, backup, third, fake = Peer(15354), Peer(15355), Peer(15356), Peer(15357, True)
    real_peers = (local, backup, third)

    def assert_counts(name, real, fake_count=0):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and any(p.count[name] < real for p in real_peers):
            time.sleep(.01)
        assert [p.count[name] for p in real_peers] == [real] * 3, (name, [p.count for p in real_peers])
        if fake_count is not None:
            assert fake.count[name] == fake_count, (name, fake.count)

    with tempfile.TemporaryDirectory(prefix='ax6000-mosdns-') as temp:
        directory = Path(temp)
        files = ROOT / 'configs/ax6000/files'
        config = load_yaml(files / 'etc/mosdns/config_custom.yaml')
        config['log']['file'] = str(directory / 'mosdns.log')
        config['api']['http'] = '127.0.0.1:19091'
        for plugin in config['plugins']:
            args = plugin.setdefault('args', {})
            if 'files' in args:
                path = directory / (plugin['tag'] + '.txt')
                content = {'geosite_cn': 'domain:direct.test\ndomain:race-third.test\ndomain:only-third-working.test\ndomain:all-upstreams-recovered.test\ndomain:all-upstreams-dead.test\nfull:local.adguard.org\n',
                           'geosite_proxy': 'domain:proxy.test\ndomain:proxy-core-servfail.test\ndomain:proxy-core-refused.test\ndomain:proxy-core-nxdomain.test\ndomain:proxy-core-empty.test\ndomain:adguard.org\n',
                           'whitelist': (files / 'etc/mosdns/rule/whitelist.txt').read_text(),
                           'geoip_cn': '1.0.0.0/24\n',
                           'local_ptr': 'full:1.199.168.192.in-addr.arpa\n'}.get(plugin['tag'], '')
                path.write_text(content); args['files'] = [str(path)]
            if plugin['tag'] == 'forward_local':
                assert args['concurrent'] == 3 and len(args['upstreams']) == 3, args
                args['upstreams'] = [{'tag': 'test_' + str(port), 'addr': '127.0.0.1:' + str(port)}
                                     for port in (15354, 15355, 15356)]
            if plugin['tag'] == 'forward_fakeip':
                args['upstreams'] = [{'addr': '127.0.0.1:15357'}]
            if plugin['type'] in ('udp_server', 'tcp_server'):
                args['listen'] = '127.0.0.1:15335'
        path = directory / 'mosdns.json'; path.write_text(json.dumps(config))
        agh = load_yaml(files / 'etc/adguardhome/adguardhome.yaml')
        agh['http']['address'] = '127.0.0.1:13000'
        agh['dns'].update(bind_hosts=['127.0.0.1'], port=15353, upstream_dns=['127.0.0.1:15335'])
        agh['dhcp']['enabled'] = False
        agh['filters'] = []
        agh['user_rules'] = ['||blocked.test^']
        for section in ('querylog', 'statistics'):
            agh[section]['dir_path'] = str(directory / section)
            (directory / section).mkdir()
        aghpath = directory / 'adguard.json'; aghpath.write_text(json.dumps(agh))
        (directory / 'work').mkdir()
        env = dict(os.environ, GOGC='50', GOMEMLIMIT='33554432')
        logs = [open(directory / 'mosdns-console.log', 'w'), open(directory / 'adguard-console.log', 'w')]
        processes = [subprocess.Popen([str(Path(mosdns).resolve()), 'start', '-c', str(path)], env=env, stdout=logs[0], stderr=subprocess.STDOUT),
                     subprocess.Popen([str(Path(adguard).resolve()), '-c', str(aghpath), '-w', str(directory / 'work'), '--no-check-update'], stdout=logs[1], stderr=subprocess.STDOUT)]
        try:
            for _ in range(50):
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError((directory/'mosdns-console.log').read_text() + (directory/'adguard-console.log').read_text())
                try:
                    urllib.request.urlopen('http://127.0.0.1:13000/control/status', timeout=1).read()
                    urllib.request.urlopen('http://127.0.0.1:19091/plugins/stats_collector/api/v1/stats', timeout=1).read()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError('Services did not become ready')
            assert lookup('direct.test') == '1.0.0.1'
            assert lookup('direct.test', tcp=True) == '1.0.0.1'
            assert_counts('direct.test', 1)
            # Explicit refusal must win over direct/parent-proxy classification
            # and the generic IPv4-only policy, without consulting any upstream.
            for qtype in (1, 28, 64, 65):
                for tcp in (False, True):
                    assert lookup('local.adguard.org', qtype=qtype, tcp=tcp,
                                  port=15335, expected_rcode=5) is None
                    # AGH handles AAAA locally before MosDNS in IPv4-only mode.
                    assert lookup('local.adguard.org', qtype=qtype, tcp=tcp,
                                  expected_rcode=0 if qtype == 28 else 5) is None
            assert_counts('local.adguard.org', 0, 0)
            for name in ('injections.adguard.org', 'child.local.adguard.org'):
                assert lookup(name).startswith('198.18.')
                assert lookup(name, tcp=True).startswith('198.18.')
                assert_counts(name, 0, 2)
            first = lookup('proxy.test'); second = lookup('proxy.test')
            assert first != second and second.startswith('198.18.')
            assert_counts('proxy.test', 0, 2)
            assert lookup('unknown-cn.test') == '1.0.0.1'
            assert lookup('unknown-cn.test') == '1.0.0.1'
            assert_counts('unknown-cn.test', 1)
            first = lookup('unknown-foreign.test'); second = lookup('unknown-foreign.test')
            assert first != second and second.startswith('198.18.')
            assert_counts('unknown-foreign.test', 1, 2)
            assert lookup('unknown-nxdomain.test').startswith('198.18.')
            assert lookup('unknown-nxdomain.test').startswith('198.18.')
            assert_counts('unknown-nxdomain.test', 1, 2)
            # Cache the real classification answer, not the resulting Fake-IP.
            # After its original TTL expires, serve the stale classification once
            # while refreshing it, then classify using the updated real answer.
            transition = 'unknown-transition.test'
            for peer in real_peers:
                peer.ttls[transition] = 1
                peer.answers[transition] = '8.8.8.8'
            assert lookup(transition).startswith('198.18.')
            for peer in real_peers:
                peer.answers[transition] = '1.0.0.1'
            assert lookup(transition).startswith('198.18.')
            assert_counts(transition, 1, 2)
            time.sleep(1.15)
            assert lookup(transition).startswith('198.18.')
            assert_counts(transition, 2, 3)
            time.sleep(.1)
            assert lookup(transition) == '1.0.0.1'
            assert_counts(transition, 2, 3)
            for peer in real_peers:
                peer.answers[transition] = '8.8.8.8'
            assert lookup(transition) == '1.0.0.1'
            assert_counts(transition, 2, 3)
            time.sleep(1.15)
            assert lookup(transition) == '1.0.0.1'
            assert_counts(transition, 3, 3)
            time.sleep(.1)
            assert lookup(transition).startswith('198.18.')
            assert_counts(transition, 3, 4)
            assert lookup('blocked.test') in ('0.0.0.0', None)
            assert_counts('blocked.test', 0)
            assert lookup('proxy.test', qtype=28) is None
            assert lookup('proxy.test', qtype=65) is None
            fake.enabled = False
            started = time.monotonic()
            assert lookup('proxy.test') == '8.8.8.8'
            elapsed = time.monotonic() - started
            assert .4 <= elapsed < 1.0, ('Silent Fake-IP upstream did not fall back at 500 ms', elapsed)
            fake.enabled = True
            assert lookup('proxy.test').startswith('198.18.')
            assert_counts('proxy.test', 1, None)
            fake.rcodes['proxy-core-servfail.test'] = 2
            started = time.monotonic()
            assert lookup('proxy-core-servfail.test') == '8.8.8.8'
            assert time.monotonic() - started < .3, 'SERVFAIL fallback waited for the 500 ms threshold'
            assert_counts('proxy-core-servfail.test', 1, 1)
            del fake.rcodes['proxy-core-servfail.test']
            assert lookup('proxy-core-servfail.test').startswith('198.18.')
            assert_counts('proxy-core-servfail.test', 1, 2)
            for name, rcode in [('proxy-core-refused.test', 5), ('proxy-core-nxdomain.test', 3), ('proxy-core-empty.test', 0)]:
                fake.rcodes[name] = rcode
                assert lookup(name, expected_rcode=rcode) is None
                assert_counts(name, 0, 1)
            assert lookup('mos-unfiltered.test', port=15335).startswith('198.18.')
            assert_counts('mos-unfiltered.test', 1, 1)
            assert lookup('1.199.168.192.in-addr.arpa', qtype=12, port=15335, expected_rcode=3) is None
            assert_counts('1.199.168.192.in-addr.arpa', 0)
            local.delays['race-third.test'] = .6
            backup.delays['race-third.test'] = .4
            third.answers['race-third.test'] = '4.0.0.1'
            started = time.monotonic()
            assert lookup('race-third.test', port=15335) == '4.0.0.1'
            assert time.monotonic() - started < .3, 'Race waited for slower upstreams'
            assert_counts('race-third.test', 1)
            time.sleep(.65)
            local.enabled = backup.enabled = False
            assert lookup('only-third-working.test', port=15335) == '8.8.8.8'
            assert_counts('only-third-working.test', 1)
            local.enabled = backup.enabled = True
            assert lookup('all-upstreams-recovered.test', port=15335) == '8.8.8.8'
            assert_counts('all-upstreams-recovered.test', 1)
            local.enabled = backup.enabled = third.enabled = False
            stats_url = 'http://127.0.0.1:19091/plugins/stats_collector/api/v1/'
            blocked_before = json.load(urllib.request.urlopen(stats_url + 'stats'))['blocked_queries']
            assert lookup('all-upstreams-dead.test', port=15335, expected_rcode=2) is None
            logs_data = json.load(urllib.request.urlopen(stats_url + 'logs?limit=100'))['items']
            failure = next(row for row in logs_data if row['domain'] == 'all-upstreams-dead.test.')
            assert failure['status'] == 'SERVFAIL' and failure['is_blocked'] is False, failure
            blocked = next(row for row in logs_data if row['domain'] == '1.199.168.192.in-addr.arpa.')
            assert blocked['is_blocked'] is True, blocked
            assert json.load(urllib.request.urlopen(stats_url + 'stats'))['blocked_queries'] == blocked_before
            stats = json.load(urllib.request.urlopen('http://127.0.0.1:19091/plugins/stats_collector/api/v1/stats'))
            assert stats, stats
            urllib.request.urlopen('http://127.0.0.1:19091/plugins/lazy_cache/flush').read()
            print('PASS: real AdGuardHome filters before real MosDNS; blocked queries reach no upstream.')
            print('PASS: domestic UDP/TCP DNS queries all three upstreams on cache miss; cache hits send no additional queries.')
            print('PASS: known proxy DNS uses local Fake-IP only, with no public upstream queries.')
            print('PASS: unknown response-IP classification; Fake-IP is not cached at either frontend.')
            print('PASS: two unknown-foreign queries use one real query per public upstream and two local Fake-IP queries; cached negative real answers are also reused.')
            print('PASS: expired real answers serve a stale classification while refreshing; refreshed answers switch foreign/domestic classification without caching Fake-IP.')
            print(f'PASS: silent Mihomo DNS falls back after {elapsed:.3f}s (500-ms threshold); recovery immediately returns Fake-IP.')
            print('PASS: Mihomo SERVFAIL immediately falls back to public DNS; recovery bypasses cached real answers and returns Fake-IP.')
            print('PASS: Mihomo REFUSED/NXDOMAIN and empty NOERROR remain unchanged and query no public upstream.')
            print('PASS: AAAA/HTTPS handling, stock MosDNS stats API and cache-flush API.')
            print('PASS: fastest third upstream wins without waiting; two failed upstreams do not prevent answers; recovery works.')
            print('PASS: MosDNS has no advertising filter; private PTR rejection is retained without reaching upstreams.')
            print('PASS: MosDNS refuses exact local.adguard.org for UDP/TCP A/AAAA/SVCB/HTTPS without upstream queries; AGH retains local empty AAAA handling; injections and child domains retain normal Fake-IP routing.')
            print('PASS: all-upstream failure is SERVFAIL, not blocked; private PTR rejection stays blocked.')
        except Exception:
            for log in logs:
                log.flush()
            print((directory/'mosdns-console.log').read_text())
            print((directory/'mosdns.log').read_text() if (directory/'mosdns.log').exists() else '')
            print((directory/'adguard-console.log').read_text())
            raise
        finally:
            for p in processes:
                p.terminate()
                p.wait(timeout=10)
            for log in logs:
                log.close()
            local.sock.close(); backup.sock.close(); third.sock.close(); fake.sock.close()


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
