#!/bin/sh
# Querying an UPX core with -v consumes memory too; prefer API and cache.
set -eu
core=/etc/openclash/core/clash_meta
cache=/tmp/openclash-core-meta-version
[ -x "$core" ] || { echo 0; exit; }
# This firmware's BusyBox does not include stat; inode/size/mtime identify it.
stamp=$(ls -lin "$core" | awk '{print $1 ":" $6 ":" $7 ":" $8 ":" $9}')
cached() {
    [ -f "$cache" ] && [ "$(head -n1 "$cache")" = "$stamp" ] || return 1
    tail -n1 "$cache"
}
save() {
    printf '%s\n%s\n' "$stamp" "$1" > "$cache.$$"
    mv "$cache.$$" "$cache"
    printf '%s\n' "$1"
}
port=$(uci -q get openclash.config.cn_port || true)
secret=$(uci -q get openclash.config.dashboard_password || true)
response=$(curl --noproxy '*' -fsS --connect-timeout 1 --max-time 2 \
    -H "Authorization: Bearer $secret" "http://127.0.0.1:${port:-9090}/version" 2>/dev/null || true)
version=$(printf '%s' "$response" | jsonfilter -e '@.version' 2>/dev/null || true)
if [ -n "$version" ]; then save "$version"; exit; fi
if cached; then exit; fi
# A starting/validating core must not be joined by a version-only process.
if pidof clash >/dev/null; then echo 0; exit; fi
mkdir -p /tmp/lock
exec 887>/tmp/lock/openclash-core-operation.lock
if ! flock -n 887; then echo 0; exit; fi
if pidof clash >/dev/null; then echo 0; exit; fi
version=$(timeout 10 "$core" -v 2>/dev/null | awk 'NR==1 {print $3}' || true)
if [ -n "$version" ]; then save "$version"; else echo 0; fi
