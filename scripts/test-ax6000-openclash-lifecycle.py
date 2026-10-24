#!/usr/bin/env python3
"""Exercise native DNS bootstrap repair and unexpected-core-exit capture."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'configs/ax6000/files/usr/share/openclash/ax6000-core-run.sh'


def check_bootstrap(converter):
    text = converter.read_text()
    start = text.index('local_exclude =')
    end = re.search(r'^\s*rescue Exception => e', text[start:], re.MULTILINE).start() + start
    block = text[start:end]
    # The host has no OpenWrt interfaces; retain the production matching logic.
    block = re.sub(r'%x\{.*?\}\.each_line\.map\(&:strip\)', "['eth0', 'br-lan']", block)
    ruby = "require 'json'; module YAML; def self.LOG_TIP(*); end; end; Value=JSON.parse(STDIN.read); respect_rules=false;\n" + block + "\nputs JSON.generate(Value)"
    direct = ['https://223.5.5.5/dns-query#DIRECT&h3=true',
              'https://223.6.6.6/dns-query#DIRECT&h3=true', '119.29.29.29#DIRECT']
    foreign = ['https://1.1.1.1/dns-query#proxy', 'https://8.8.8.8/dns-query#proxy']
    base = {'dns': {'nameserver': foreign, 'default-nameserver': ['223.5.5.5', '119.29.29.29'],
                    'proxy-server-nameserver': direct}}
    def transform(value):
        return json.loads(subprocess.check_output(['ruby', '-e', ruby], input=json.dumps(value).encode()))
    assert transform(base) == base, 'Explicit DIRECT bootstrap must survive generation unchanged'
    empty = copy.deepcopy(base)
    empty['dns']['proxy-server-nameserver'] = []
    assert transform(empty)['dns']['proxy-server-nameserver'] == ['223.5.5.5', '119.29.29.29']
    unsafe = copy.deepcopy(base)
    unsafe['dns']['proxy-server-nameserver'] = foreign.copy()
    added = transform(unsafe)['dns']['proxy-server-nameserver'][len(foreign):]
    assert added == ['223.5.5.5', '119.29.29.29'], 'Automatic bootstrap must never append proxied DoH'
    assert transform(transform(base)) == base


def check_exit_capture():
    with tempfile.TemporaryDirectory(prefix='ax6000-core-exit-') as tmp:
        directory = Path(tmp)
        logger = directory / 'logger'
        logger.write_text('#!/bin/sh\nexit 0\n')
        logger.chmod(0o755)
        log = directory / 'core.log'
        record = directory / 'exit.log'
        env = dict(os.environ, PATH=str(directory) + ':' + os.environ['PATH'],
                   AX6000_CORE_LOG=str(log), AX6000_CORE_EXIT_LOG=str(record))
        p = subprocess.run(['sh', str(RUNNER), 'sh', '-c', 'echo "panic: fixture"; exit 23'], env=env, timeout=5)
        assert p.returncode == 23
        assert 'status=23' in record.read_text() and 'panic: fixture' in record.read_text()
        assert record.stat().st_mode & 0o777 == 0o600
        retained = record.read_bytes()
        log.write_text('')
        assert record.read_bytes() == retained, 'Live log cleanup must not erase the exit record'
        started = directory / 'started'
        core = directory / 'core.sh'
        core.write_text('#!/bin/sh\ntrap "exit 0" TERM\n: > "$1"\nwhile :; do sleep 0.1; done\n')
        core.chmod(0o755)
        p = subprocess.Popen(['sh', str(RUNNER), str(core), str(started)], env=env)
        try:
            deadline = time.monotonic() + 3
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert started.exists()
            p.terminate()
            p.wait(timeout=3)
            assert record.read_bytes() == retained, 'Planned service stop must preserve the last unexpected exit'
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--converter', type=Path, required=True)
    args = parser.parse_args()
    check_bootstrap(args.converter)
    check_exit_capture()
    print('PASS: DIRECT bootstrap, safe automatic DNS completion, exit status capture, log retention and planned shutdown.')


if __name__ == '__main__':
    main()
