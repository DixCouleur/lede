#!/bin/sh
set -eu
config_file="$1"
work_dir="$2"
service_user="$3"
service_group="$4"
# Wait for the configured local DNS handler, not WAN or the later OpenClash.
if [ "$(uci -q get mosdns.config.ax6000_split 2>/dev/null || true)" = "1" ] &&
   [ "$(uci -q get mosdns.config.enabled 2>/dev/null || true)" = "1" ]; then
  if ready_result=$(timeout -k 1 16 lua /usr/share/adguardhome/ax6000-wait-dns.lua 127.0.0.1 5335 15 2>&1); then
    logger -t AdGuardHome -p daemon.notice "$ready_result"
  else
    logger -t AdGuardHome -p daemon.warn "${ready_result:-MosDNS readiness check failed}; continuing to keep DHCP and Web available"
  fi
fi
# Only leases/settings persist; filters, statistics and query logs stay in RAM.
mkdir -p "$work_dir/data" /var/lib/adguardhome/filters \
  /var/lib/adguardhome/statistics /var/lib/adguardhome/querylog
chmod 0700 "$work_dir" "$work_dir/data" /var/lib/adguardhome
if [ ! -e "$work_dir/data/filters" ] && [ ! -L "$work_dir/data/filters" ]; then
  ln -s /var/lib/adguardhome/filters "$work_dir/data/filters"
fi
chown -R "$service_user:$service_group" /var/lib/adguardhome
AX6000_LAN_IPV6=$(ip -6 -o addr show dev br-lan scope global | awk '$4 ~ /^f[cd]/ {print $4; exit}')
AX6000_CLASH_RUNNING=0
[ -z "$(pidof clash 2>/dev/null)" ] || AX6000_CLASH_RUNNING=1
export AX6000_LAN_IPV6 AX6000_CLASH_RUNNING
ruby /usr/share/openclash/adguardhome_dns.rb prepare "$config_file"
