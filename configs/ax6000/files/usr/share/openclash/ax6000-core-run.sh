#!/bin/sh
# Keep the exit status and a bounded log when the production core exits itself.
log_file=${AX6000_CORE_LOG:-/tmp/openclash.log}
exit_file=${AX6000_CORE_EXIT_LOG:-/tmp/openclash-last-exit.log}
core_pid=
stopping=0
umask 077

terminate() {
    stopping=1
    [ -z "$core_pid" ] || kill -TERM "$core_pid" 2>/dev/null || true
}
trap terminate HUP INT TERM

"$@" >> "$log_file" 2>&1 &
core_pid=$!
while :; do
    wait "$core_pid"
    result=$?
    kill -0 "$core_pid" 2>/dev/null || break
done

if [ "$stopping" = 0 ]; then
    message="Mihomo exited unexpectedly: pid=$core_pid status=$result"
    {
        date -Iseconds
        printf '%s\n' "$message"
        tail -c 262144 "$log_file" 2>/dev/null
    } > "$exit_file.new.$$"
    mv -f "$exit_file.new.$$" "$exit_file"
    logger -t openclash -p daemon.err "$message" 2>/dev/null || true
fi
exit "$result"
