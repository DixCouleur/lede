#!/bin/sh
# Subscription validation must not load a second core on a 512 MiB router.
set -eu
mode=config
if [ "$1" = --version ]; then mode=version; shift; fi
core=$1
core_dir=${2:-}
candidate=${3:-}
age_secret=${4:-}
service=${AX6000_CORE_SERVICE:-/etc/init.d/openclash}
lock=${AX6000_CORE_LOCK:-/tmp/lock/openclash-core-operation.lock}
start_pid_file="${lock}.start.$$"
resume=0
checking=0
test_pid=
mkdir -p "${lock%/*}"
exec 886>"$lock"
flock -x 886

finish() {
    result=$?
    trap - EXIT HUP INT TERM
    if [ "$checking" = 1 ]; then
        [ -z "$test_pid" ] || kill -TERM "$test_pid" 2>/dev/null || true
        tries=0
        while [ -n "$test_pid" ] && kill -0 "$test_pid" 2>/dev/null; do
            tries=$((tries + 1))
            if [ "$tries" -ge 20 ]; then resume=0; result=1; break; fi
            sleep 1
        done
    fi
    if [ "$resume" = 1 ] && [ "$(uci -q get openclash.config.enable)" = 1 ]; then
        if ! AX6000_CORE_CHECK=1 AX6000_CORE_START_PID_FILE="$start_pid_file" "$service" start >&2; then
            result=1
        else
            # rc.common commits procd only after start_service returns. Await its
            # background status/cache writer here, outside service registration.
            start_pid=
            [ ! -s "$start_pid_file" ] || read -r start_pid < "$start_pid_file"
            case "$start_pid" in
                ''|*[!0-9]*) result=1 ;;
                *)
                    tries=0
                    while kill -0 "$start_pid" 2>/dev/null; do
                        tries=$((tries + 1))
                        [ "$tries" -lt 45 ] || { result=1; break; }
                        sleep 1
                    done
                    ;;
            esac
            port=$(uci -q get openclash.config.cn_port || true)
            secret=$(uci -q get openclash.config.dashboard_password || true)
            tries=0
            until curl --noproxy '*' -fsS --connect-timeout 1 --max-time 2 \
                -H "Authorization: Bearer $secret" "http://127.0.0.1:${port:-9090}/version" >/dev/null 2>&1; do
                tries=$((tries + 1))
                [ "$tries" -lt 45 ] || { result=1; break; }
                sleep 1
            done
        fi
    fi
    rm -f "$start_pid_file"
    flock -u 886
    exit "$result"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM

if pidof clash >/dev/null; then
    resume=1
    AX6000_CORE_CHECK=1 "$service" stop >&2
fi
tries=0
while pidof clash >/dev/null; do
    tries=$((tries + 1))
    [ "$tries" -lt 20 ] || { echo 'Core check refused: previous core is still running.' >&2; exit 1; }
    sleep 1
done
checking=1
if [ "$mode" = version ]; then
    SAFE_PATHS=/usr/share/openclash:/etc/ssl GOGC=50 GOMEMLIMIT=134217728 \
        timeout 10 "$core" -v &
else
    SAFE_PATHS=/usr/share/openclash:/etc/ssl GOGC=50 GOMEMLIMIT=134217728 \
        timeout 90 "$core" -t -d "$core_dir" -f "$candidate" -age-secret-key "$age_secret" &
fi
test_pid=$!
wait "$test_pid"
checking=0
