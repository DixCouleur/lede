#!/usr/bin/env python3
"""Check incomplete subscriptions against the actual guard and updater functions."""
import argparse
import copy
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'configs/ax6000/files/usr/share/openclash/ax6000-subscription-check.rb'


def shell_function(text, name):
    start = text.index(name + '()')
    return text[start:text.index('\n}', start) + 2]


def full_subscription(count=55):
    nodes = [{'name': f'node-{i}', 'type': 'ss', 'server': 'example.com',
              'port': 443, 'cipher': 'aes-128-gcm', 'password': 'private-fixture-secret'}
             for i in range(count)]
    groups = [{'name': f'region-{i}', 'type': 'url-test',
               'proxies': [node['name'] for index, node in enumerate(nodes) if index % 18 == i]}
              for i in range(18)]
    groups.append({'name': 'fallback', 'type': 'fallback',
                   'proxies': [group['name'] for group in groups]})
    return {'proxies': nodes, 'proxy-groups': groups}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--updater', type=Path, required=True)
    args = parser.parse_args()
    updater = args.updater.read_text()
    with tempfile.TemporaryDirectory(prefix='ax6000-subscription-integrity-') as tmp:
        directory = Path(tmp)
        current, candidate = directory / 'current.yaml', directory / 'candidate.yaml'
        full = full_subscription()
        damaged = copy.deepcopy(full)
        damaged['proxies'] = damaged['proxies'][:1]
        for group in damaged['proxy-groups']:
            group['proxies'] = ['DIRECT']
        damaged['proxy-groups'][0]['proxies'] = ['node-0']

        def write(path, value):
            path.write_text(json.dumps(value))

        def check(value, baseline=full, expected=True):
            write(candidate, value)
            if baseline is None:
                current.unlink(missing_ok=True)
            else:
                write(current, baseline)
            result = subprocess.run(['ruby', str(GUARD), str(candidate), str(current)],
                                    capture_output=True, text=True, timeout=5)
            assert (result.returncode == 0) == expected, result.stderr
            assert 'private-fixture-secret' not in result.stdout + result.stderr

        check(full)
        check(full_subscription(54))
        check(damaged, expected=False)
        check({'proxies': [], 'proxy-groups': []}, baseline=None, expected=False)
        check(full, baseline=None)
        # A legitimate small subscription can be installed without a large baseline.
        check(damaged, baseline=None)
        collapsed = copy.deepcopy(full)
        for group in collapsed['proxy-groups']:
            group['proxies'] = ['DIRECT']
        check(collapsed, expected=False)
        # Migration to provider-backed groups must not look like missing inline nodes.
        providers = copy.deepcopy(full)
        providers['proxies'] = []
        providers['proxy-providers'] = {'subscription': {'type': 'http',
            'url': 'https://example.com/provider.yaml', 'path': './provider.yaml'}}
        for group in providers['proxy-groups'][:-1]:
            group.pop('proxies')
            group['use'] = ['subscription']
        check(providers)
        # Changing templates and group names is allowed when the nodes are complete.
        renamed = copy.deepcopy(full)
        for group in renamed['proxy-groups']:
            group['name'] = 'renamed-' + group['name']
        renamed['proxy-groups'][-1]['proxies'] = [g['name'] for g in renamed['proxy-groups'][:-1]]
        check(renamed)
        current.write_text('unreadable old config')
        write(candidate, full)
        assert subprocess.run(['ruby', str(GUARD), str(candidate), str(current)],
                              capture_output=True, timeout=5).returncode == 0
        candidate.write_text('proxies: [private-fixture-secret\n')
        result = subprocess.run(['ruby', str(GUARD), str(candidate), str(current)],
                                capture_output=True, text=True, timeout=5)
        assert result.returncode != 0 and 'private-fixture-secret' not in result.stderr

        # Exercise the production functions: bad replies must never call the core
        # validator, and post-download filters must not commit a collapsed result.
        core_check = directory / 'core-check'
        core_check.write_text('#!/bin/sh\necho validation >> "$FIXTURE_DIR/events"\n')
        core_check.chmod(0o755)
        functions = '\n'.join(shell_function(updater, name) for name in
            ['config_integrity_check', 'config_test', 'config_su_check', 'config_error'])
        functions = functions.replace('/usr/share/openclash/ax6000-subscription-check.rb',
                                      shlex.quote(str(GUARD)))
        functions = functions.replace('/usr/share/openclash/ax6000-core-check.sh',
                                      shlex.quote(str(core_check)))
        functions = functions.replace('/tmp/openclash.change', str(directory / 'cache'))
        env = dict(os.environ, FIXTURE_DIR=tmp)
        base = '''
LOG_OUT() { :; }
LOG_ERROR() { :; }
config_cus_up() { :; }
CLASH="$FIXTURE_DIR/core-check"
CLASH_CONFIG="$FIXTURE_DIR"
CFG_FILE="$FIXTURE_DIR/candidate.yaml"
CONFIG_FILE="$FIXTURE_DIR/current.yaml"
CONFIG_PATH="$CONFIG_FILE"
LOG_FILE="$FIXTURE_DIR/log"
only_download=0
restart=0
norestart=0
name=fixture
SECRET_KEY=
''' + functions + '\n'
        for valid in (True, False):
            write(current, full)
            write(candidate, full if valid else damaged)
            events = directory / 'events'
            events.unlink(missing_ok=True)
            run = subprocess.run(['bash', '-c', base + 'config_test'], env=env,
                                 capture_output=True, text=True, timeout=5)
            assert run.returncode == (0 if valid else 2), run.stderr
            assert events.exists() == valid, 'Rejected reply interrupted production validation'
            assert json.loads(current.read_text()) == full
        for valid in (True, False):
            write(current, full)
            write(candidate, full_subscription(54))
            cache = directory / 'cache'
            cache.write_text('cached')
            write(directory / 'filtered.yaml', damaged)
            filter_step = '' if valid else 'config_cus_up() { cp "$FIXTURE_DIR/filtered.yaml" "$CFG_FILE"; }\n'
            driver = base + filter_step + '''config_su_check
result=$?
echo "$restart" > "$FIXTURE_DIR/restart"
exit "$result"
'''
            run = subprocess.run(['bash', '-c', driver], env=env,
                                 capture_output=True, text=True, timeout=5)
            assert run.returncode == (0 if valid else 1), run.stderr
            assert json.loads(current.read_text()) == (full_subscription(54) if valid else full)
            assert cache.exists() != valid
            assert (directory / 'restart').read_text().strip() == ('1' if valid else '0')
        if 'norestart=0' in updater:
            write(current, full)
            write(candidate, full_subscription(54))
            cache.write_text('cached')
            driver = base + 'norestart=1\nconfig_su_check\necho "$restart" > "$FIXTURE_DIR/restart"\n'
            run = subprocess.run(['bash', '-c', driver], env=env,
                                 capture_output=True, text=True, timeout=5)
            assert run.returncode == 0, run.stderr
            assert json.loads(current.read_text()) == full_subscription(54)
            assert not cache.exists(), 'Deferred restart must invalidate stale runtime cache'
            assert (directory / 'restart').read_text().strip() == '0'
        print('PASS: incomplete replies, empty subscriptions, group collapse, provider migration, '
              'normal changes, private error output, pre-core rejection and post-filter commit protection.')


if __name__ == '__main__':
    main()
