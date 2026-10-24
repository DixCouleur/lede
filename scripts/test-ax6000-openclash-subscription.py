#!/usr/bin/env python3
"""Reproduce subscription replacement racing the validator's restored service."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / 'configs/ax6000/files/usr/share/openclash/ax6000-core-check.sh'


def shell_function(text, name):
    start = text.index(name + '()')
    end = text.index('\n}', start) + 2
    return text[start:end]


def exercise(init, updater, process_helper, valid=True, changed=True, wait_for_start=True):
    start = init.index('      LOG_OUT "Step 6: Core Status Checking and Firewall Rules Setting..."')
    end = init.index('\n      if [ "$ipv6_enable"', start)
    start_block = init[start:end]
    with tempfile.TemporaryDirectory(prefix='ax6000-subscription-') as tmp:
        directory = Path(tmp)
        env = dict(os.environ, FIXTURE_DIR=tmp, PATH=tmp + ':' + os.environ['PATH'])
        # macOS /bin/sh does not support the router's high-numbered descriptors.
        # The fixture stubs flock; retain the lifecycle logic with a portable FD.
        checker_text = CHECKER.read_text().replace('886', '8')
        if not wait_for_start:
            begin = checker_text.index('            # rc.common commits procd')
            finish = checker_text.index('            port=', begin)
            checker_text = checker_text[:begin] + checker_text[finish:]
        checker = directory / 'checker.sh'
        checker.write_text(checker_text)
        def executable(name, text):
            path = directory / name
            path.write_text('#!/bin/bash\n' + text)
            path.chmod(0o755)
            return path

        raw, runtime = directory / 'raw.yaml', directory / 'runtime.yaml'
        candidate, cache = directory / 'candidate.yaml', directory / 'cache'
        raw.write_text('old-node\n')
        runtime.write_text('old-node\n')
        candidate.write_text(('new-node\n' if changed else 'old-node\n') if valid else 'invalid\n')
        cache.write_text('old-node\n')
        (directory / 'production').touch()
        executable('flock', 'exit 0\n')
        executable('pidof', '[ -f "$FIXTURE_DIR/production" ] && echo 123\n')
        executable('uci', 'case "$*" in *config.enable) echo 1;; *) echo 9090;; esac\n')
        executable('curl', 'exit 0\n')
        executable('timeout', 'shift\nexec "$@"\n')
        # Native normalization is unrelated to this race; fixture YAML has no tags.
        executable('sed', 'exit 0\n')
        core = executable('core', '''
[ ! -f "$FIXTURE_DIR/production" ] || exit 90
echo validate >> "$FIXTURE_DIR/events"
for arg in "$@"; do [ "$arg" != -f ] || want_path=1; if [ "${want_path:-0}" = 2 ]; then candidate=$arg; break; fi; [ "${want_path:-0}" != 1 ] || want_path=2; done
! grep -q invalid "$candidate"
''')
        service = executable('service', '''
LOG_OUT() { :; }
check_core_status() {
    # The real core is created only after start_service returns to rc.common.
    tries=0
    until [ -f "$FIXTURE_DIR/production" ]; do
        tries=$((tries+1))
        [ "$tries" -lt 100 ] || exit 1
        sleep 0.01
    done
    sleep 1
    cp "$FIXTURE_DIR/raw.yaml" "$FIXTURE_DIR/cache"
    echo ready >> "$FIXTURE_DIR/events"
}
case "$1" in
stop) rm -f "$FIXTURE_DIR/production"; echo stop >> "$FIXTURE_DIR/events";;
start)
''' + start_block + '''
    touch "$FIXTURE_DIR/production"
    ;;
restart)
    if [ ! -f "$FIXTURE_DIR/cache" ] || ! cmp -s "$FIXTURE_DIR/cache" "$FIXTURE_DIR/raw.yaml"; then
        cp "$FIXTURE_DIR/raw.yaml" "$FIXTURE_DIR/runtime.yaml"
    fi
    echo restart >> "$FIXTURE_DIR/events"
    ;;
esac
''')
        env.update(AX6000_CORE_SERVICE=str(service), AX6000_CORE_LOCK=str(directory / 'core.lock'))
        update_function = shell_function(updater, 'config_su_check').replace('/tmp/openclash.change', str(cache))
        counter_function = shell_function(process_helper, 'dec_job_counter_and_restart')
        counter_function = counter_function.replace('/tmp/lock/openclash_jobs.lock', str(directory / 'jobs.lock'))
        counter_function = counter_function.replace('/etc/init.d/openclash restart', '"$FIXTURE_DIR/service" restart')
        counter_function = counter_function.replace('999', '9')
        driver = '''
LOG_OUT() { :; }
config_cus_up() { :; }
config_integrity_check() { return 0; }
unify_ps_prevent() {
    # Native startup remains present until its cache/firewall completion.
    if grep -q ready "$FIXTURE_DIR/events"; then echo 0; else echo 1; fi
}
CONFIG_FILE="$FIXTURE_DIR/raw.yaml"
CONFIG_PATH="$CONFIG_FILE"
CFG_FILE="$FIXTURE_DIR/candidate.yaml"
only_download=0
restart=0
norestart=0
name=fixture
JOB_COUNTER_FILE="$FIXTURE_DIR/jobs"
echo '1 0' > "$JOB_COUNTER_FILE"
''' + update_function + '\n' + counter_function + '''
sh "$CHECKER" "$FIXTURE_DIR/core" "$FIXTURE_DIR" "$CFG_FILE" ''
result=$?
if [ "$result" = 0 ]; then config_su_check; fi
dec_job_counter_and_restart "$restart"
wait
exit "$result"
'''
        env['CHECKER'] = str(checker)
        try:
            result = subprocess.run(['bash', '-c', driver], env=env, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired as error:
            events = (directory / 'events').read_text() if (directory / 'events').exists() else 'no events'
            raise AssertionError(f'Lifecycle fixture timed out: {events}; stderr={error.stderr!r}') from None
        # Allow an intentionally broken asynchronous start to finish for the negative control.
        time.sleep(1.1)
        events = (directory / 'events').read_text().splitlines()
        assert (directory / 'production').exists(), 'Validation must restore production'
        assert events[:2] == ['stop', 'validate'], events
        if valid and changed:
            assert result.returncode == 0, result.stderr
            assert raw.read_text() == runtime.read_text() == 'new-node\n', (events, raw.read_text(), runtime.read_text())
            assert events == ['stop', 'validate', 'ready', 'restart'], events
            assert not (directory / 'jobs').exists(), 'Updated configuration must not leave a pending restart'
        else:
            assert (result.returncode == 0) == valid, result.stderr
            assert raw.read_text() == runtime.read_text() == 'old-node\n', events
            assert events == ['stop', 'validate', 'ready'], events
            assert (directory / 'jobs').read_text().strip() == '0 0'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--init', type=Path, required=True)
    parser.add_argument('--updater', type=Path, required=True)
    parser.add_argument('--process-helper', type=Path, required=True)
    args = parser.parse_args()
    init, updater, process_helper = (p.read_text() for p in (args.init, args.updater, args.process_helper))
    exercise(init, updater, process_helper)
    exercise(init, updater, process_helper, changed=False)
    exercise(init, updater, process_helper, valid=False)
    # The original asynchronous branch must reproduce the stale-runtime failure.
    try:
        exercise(init, updater, process_helper, wait_for_start=False)
    except AssertionError:
        pass
    else:
        raise AssertionError('Negative control failed to reproduce the original race')
    print('PASS: single-core validation, ready-before-replacement, new runtime reload, failed-candidate recovery, and original-race negative control.')


if __name__ == '__main__':
    main()
