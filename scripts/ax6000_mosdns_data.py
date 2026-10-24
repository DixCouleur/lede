#!/usr/bin/env python3
"""Export selected pinned GeoSite rules and existing CN routes for MosDNS."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
from ax6000_geosite import fields, entries, check_geosite


def domains(raw, attribute=None):
    envelope = list(fields(raw))
    payload = envelope[0][2]
    prefixes = {0: 'keyword:', 1: 'regexp:', 2: 'domain:', 3: 'full:'}
    for number, wire, data, _ in fields(payload):
        if (number, wire) != (2, 2):
            continue
        kind, name, attrs = 0, None, set()
        for n, w, value, _ in fields(data):
            if (n, w) == (1, 0):
                kind = value
            elif (n, w) == (2, 2):
                name = value.decode('utf-8')
            elif (n, w) == (3, 2):
                key = next((v.decode('utf-8') for a, b, v, _ in fields(value)
                            if (a, b) == (1, 2)), None)
                if key:
                    attrs.add(key)
        if attribute and attribute not in attrs:
            continue
        if name is None or kind not in prefixes or '\n' in name:
            raise ValueError('Unsupported GeoSite domain')
        yield prefixes[kind] + name


def export(source, routes, output):
    selected = check_geosite(source.read_bytes())
    direct = {'domain:lan', 'domain:local', 'domain:arpa'}
    for category in ('cn', 'apple-cn', 'google-cn', 'private'):
        direct.update(domains(selected[category]))
    direct.update(domains(selected['category-games'], 'cn'))
    proxy = set()
    for category in ('geolocation-!cn', 'gfw'):
        proxy.update(domains(selected[category]))
    cidrs = {'10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8'}
    for line in routes.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == 'add':
            cidrs.add(str(ipaddress.ip_network(parts[2])))
        elif len(parts) == 1 and not parts[0].startswith('#'):
            cidrs.add(str(ipaddress.ip_network(parts[0])))
    if len(cidrs) < 1000:
        raise ValueError('CN routing data is unexpectedly small')
    output.mkdir(parents=True, exist_ok=True)
    report = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'files': {}}
    for name, values in [('direct.txt', direct), ('proxy.txt', proxy), ('cn-ip.txt', cidrs)]:
        data = ('\n'.join(sorted(values)) + '\n').encode()
        (output / name).write_bytes(data)
        report['files'][name] = {'rules': len(values), 'bytes': len(data),
                                 'sha256': hashlib.sha256(data).hexdigest()}
    (output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('geosite', type=Path)
    parser.add_argument('routes', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    export(args.geosite, args.routes, args.output)
