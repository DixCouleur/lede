#!/usr/bin/env python3
"""Test startup waiting with isolated loopback DNS responders; never stop services."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'configs/ax6000/files/usr/share/adguardhome/ax6000-wait-dns.lua'
PREPARE = ROOT / 'configs/ax6000/files/usr/share/adguardhome/ax6000-prepare.sh'

RESPONDER = r'''
local n = require "nixio"
local port, mode = tonumber(arg[1]), arg[2]
local function now()
    local f = assert(io.open('/proc/uptime'))
    local v = f:read('*n'); f:close(); return v
end
local started = now()
local udp = assert(n.socket('inet', 'dgram'))
local tcp = assert(n.socket('inet', 'stream'))
assert(udp:bind('127.0.0.1', port))
assert(tcp:setopt('socket', 'reuseaddr', 1))
assert(tcp:bind('127.0.0.1', port)); assert(tcp:listen(5))
udp:setblocking(false); tcp:setblocking(false)
io.stdout:write('LISTENING\n'); io.stdout:flush()
local function answer(data, protocol)
    if mode == 'silent' or (mode == 'delayed' and now() - started < 0.9)
        or (mode == 'udp-only' and protocol == 'tcp')
        or (mode == 'tcp-only' and protocol == 'udp') then return nil end
    if mode == 'echo' then return data end
    local rcode = mode == 'servfail' and 2 or 0
    local reply = data:sub(1, 2) .. string.char(129, 128 + rcode, 0, 1, 0, 0, 0, 0, 0, 0) .. data:sub(13)
    if mode == 'wrong-id' then
        reply = string.char((data:byte(1) + 1) % 256) .. reply:sub(2)
    elseif mode == 'wrong-question' then
        reply = reply:sub(1, 13) .. 'z' .. reply:sub(15)
    end
    return reply
end
local function read_exact(c, length)
    local value = ''
    while #value < length do
        local part = c:recv(length - #value)
        if not part or #part == 0 then return nil end
        value = value .. part
    end
    return value
end
while now() - started < 6 do
    local fds = {{fd=udp, events=n.poll_flags('in')}, {fd=tcp, events=n.poll_flags('in')}}
    n.poll(fds, 50)
    if fds[1].revents and fds[1].revents ~= 0 then
        local data, address, peer = udp:recvfrom(4096)
        if data then
            local reply = answer(data, 'udp')
            if reply then udp:sendto(reply, address, peer) end
        end
    end
    if fds[2].revents and fds[2].revents ~= 0 then
        local c = tcp:accept()
        if c then
            c:setblocking(true); c:setopt('socket', 'rcvtimeo', 1)
            local prefix = read_exact(c, 2)
            if prefix then
                local length = prefix:byte(1) * 256 + prefix:byte(2)
                local data = length <= 512 and read_exact(c, length)
                local reply = data and answer(data, 'tcp')
                if reply then
                    local wire = string.char(math.floor(#reply / 256), #reply % 256) .. reply
                    if mode == 'fragmented' then
                        c:send(wire:sub(1, 1)); n.poll({}, 20)
                        c:send(wire:sub(2, 9)); n.poll({}, 20)
                        c:send(wire:sub(10))
                    else c:send(wire) end
                end
            end
            c:close()
        end
    end
end
udp:close(); tcp:close()
'''


def hook_tests():
    # Exercise the actual gate and its continuation without touching AGH paths.
    prefix = PREPARE.read_text().split('# Only leases/settings persist;', 1)[0]
    with tempfile.TemporaryDirectory(prefix='ax6000-ready-hook-') as directory:
        d = Path(directory)
        wrappers = {
            'uci': '#!/bin/sh\ncase "$*:$TEST_CASE" in *ax6000_split:unsplit|*enabled:disabled) echo 0;; *) echo 1;; esac\n',
            'timeout': '#!/bin/sh\necho probe >>"$TEST_EVENTS"\nif [ "$TEST_CASE" = timeout ]; then echo not-ready; exit 1; fi\necho ready\n',
            'logger': '#!/bin/sh\necho "logger $*" >>"$TEST_EVENTS"\n',
        }
        for name, value in wrappers.items():
            path = d / name; path.write_text(value); path.chmod(0o755)
        import os
        for case in ['ready', 'timeout', 'disabled', 'unsplit']:
            events = d / 'events'; events.write_text('')
            env = dict(os.environ, PATH=f'{d}:{os.environ["PATH"]}', TEST_CASE=case,
                       TEST_EVENTS=str(events))
            script = prefix + '\necho downstream-preparation >>"$TEST_EVENTS"\n'
            subprocess.run(['sh', '-s', '--', 'config', 'work', 'user', 'group'],
                           input=script, text=True, env=env, check=True)
            log = events.read_text()
            assert log.endswith('downstream-preparation\n'), (case, log)
            assert ('probe\n' in log) == (case in ['ready', 'timeout']), (case, log)
            if case == 'timeout':
                assert 'daemon.warn' in log and 'keep DHCP and Web available' in log, log
            print(f'PASS hook: {case}')


def router_tests(router):
    assert re.fullmatch(r'(?:[A-Za-z0-9_.-]+@)?[A-Za-z0-9_.-]+', router), router
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', router]
    stage = '/tmp/ax6000-dns-ready-test-' + uuid.uuid4().hex[:10]
    def run(command, **kwargs):
        return subprocess.run(ssh + [command], capture_output=True, text=True,
                              timeout=25, **kwargs)
    try:
        result = run(f'umask 077; mkdir {shlex.quote(stage)}'); result.check_returncode()
        for name, data in [('probe.lua', HELPER.read_text()), ('responder.lua', RESPONDER)]:
            result = run(f'cat > {shlex.quote(stage + "/" + name)}', input=data)
            result.check_returncode()
        result = run("lua -e " + shlex.quote(f'assert(loadfile("{stage}/probe.lua"))'))
        result.check_returncode()
        results = []
        for index, mode in enumerate(['ready', 'delayed', 'fragmented', 'udp-only',
                                      'tcp-only', 'silent', 'echo', 'wrong-id',
                                      'wrong-question', 'servfail', 'closed']):
            port = 25400 + index
            budget = 2.5 if mode == 'delayed' else 0.8
            shell = f'''set -u
trap 'test -z "${{mock_pid:-}}" || kill "$mock_pid" 2>/dev/null || true' EXIT
'''
            if mode != 'closed':
                shell += f'''lua {stage}/responder.lua {port} {mode} >{stage}/server.log 2>&1 &
mock_pid=$!
for i in 1 2 3 4 5 6 7 8 9 10; do
    grep -q LISTENING {stage}/server.log && break
    sleep 0.05
done
grep -q LISTENING {stage}/server.log || {{ cat {stage}/server.log; exit 2; }}
'''
            shell += f'timeout -k 1 5 lua {stage}/probe.lua 127.0.0.1 {port} {budget}\n'
            start = time.monotonic(); result = run('sh -s', input=shell)
            elapsed = time.monotonic() - start
            expected = 0 if mode in ['ready', 'delayed', 'fragmented'] else 1
            assert result.returncode == expected, (mode, result.stdout, result.stderr)
            match = re.search(r'(?:UDP/TCP, |after )(\d+\.\d+)s', result.stdout + result.stderr)
            assert match, (mode, result.stdout, result.stderr)
            wait = float(match[1])
            assert wait < budget + 0.15, (mode, wait, budget)
            if mode == 'delayed': assert wait >= 0.7, wait
            if expected == 1: assert wait >= budget - 0.05, (mode, wait)
            results.append({'mode': mode, 'exit': result.returncode,
                            'probe_seconds': wait, 'ssh_seconds': round(elapsed, 3)})
            print(f'PASS DNS responder: {mode}, wait={wait:.2f}s')
        result = run(f'timeout -k 1 16 lua {stage}/probe.lua 127.0.0.1 5335 15')
        result.check_returncode()
        print('PASS production MosDNS:', result.stdout.strip())
        return results
    finally:
        result = run('rm -rf ' + shlex.quote(stage))
        result.check_returncode()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True, help='Authorized SSH target')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    hook_tests()
    results = router_tests(args.router)
    if args.output:
        args.output.write_text(json.dumps(results, indent=2) + '\n')
