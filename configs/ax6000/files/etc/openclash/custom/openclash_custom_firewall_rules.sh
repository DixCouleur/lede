#!/bin/sh
# Selective Fake-IP on native fw3 REDIRECT/TPROXY, mixed and TUN paths.
. /usr/share/openclash/log.sh
[ "$(uci -q get mosdns.config.ax6000_split)" = 1 ] || exit 0
case "$(uci -q get openclash.config.en_mode)" in
  fake-ip|fake-ip-mix|fake-ip-tun) ;;
  *) LOG_OUT "MosDNS selective routing requires a Fake-IP mode."; exit 1 ;;
esac
ipset -exist create ax6000_proxy_ip hash:net family inet || exit 1
ipset flush ax6000_proxy_ip || exit 1
# This list is maintained in the stock OpenClash custom routing/IP editor.
for source in /etc/mosdns/data/proxy-ip.txt /etc/openclash/custom/openclash_custom_chnroute_pass.list; do
  [ -f "$source" ] || continue
  awk '!/^#/ && NF {print $1}' "$source" | while IFS= read -r cidr; do
    ipset -exist add ax6000_proxy_ip "$cidr" 2>/dev/null
  done
done
# -S emits the native protocol, port and mark for each mode. Reuse them for
# explicit proxy CIDRs instead of assuming TUN marks also work for TPROXY.
# Disable pathname expansion when splitting these trusted numeric rule tokens.
set -f
managed_chains=0
for table in nat mangle; do
  for chain in openclash openclash_output; do
    fake_rule=$(iptables -t "$table" -S "$chain" 2>/dev/null | awk '$1 == "-A" && /-d 198\.18\.0\.0\/16 / && /-j (REDIRECT|TPROXY|MARK) / {print; exit}')
    [ -n "$fake_rule" ] || continue
    managed_chains=$((managed_chains + 1))
    # Native OUTPUT NAT places some exemptions after its Fake-IP rule. Protect
    # reply and local traffic explicitly when adding real-IP proxy exceptions.
    proxy_rule=$(printf '%s\n' "$fake_rule" | sed 's/-d 198\.18\.0\.0\/16/-m set --match-set ax6000_proxy_ip dst/; s/ -j / -m conntrack --ctdir ORIGINAL -m set ! --match-set localnetwork dst -j /')
    set -- $proxy_rule
    shift 2
    if ! iptables -t "$table" -C "$chain" "$@" 2>/dev/null; then
      position=$(iptables -t "$table" -L "$chain" -n --line-numbers | awk '/198\.18\.0\.0\/16/ {print $1; exit}')
      [ -n "$position" ] || exit 1
      iptables -t "$table" -I "$chain" "$position" "$@" || exit 1
    fi
    # Keep native rules and exemptions intact. Stop real-IP traffic before
    # China's bypass and the final catch-all redirect/TPROXY/TUN mark.
    if ! iptables -t "$table" -C "$chain" ! -d 198.18.0.0/16 -m set ! --match-set ax6000_proxy_ip dst -j RETURN 2>/dev/null; then
      position=$(iptables -t "$table" -L "$chain" -n --line-numbers | awk '/198\.18\.0\.0\/16/ {print $1; exit}')
      [ -n "$position" ] || exit 1
      iptables -t "$table" -I "$chain" "$position" ! -d 198.18.0.0/16 -m set ! --match-set ax6000_proxy_ip dst -j RETURN || exit 1
    fi
  done
done
[ "$managed_chains" -gt 0 ] || { LOG_OUT "MosDNS routing: no native Fake-IP rules found."; exit 1; }
LOG_OUT "MosDNS routing: Fake-IP and explicit proxy CIDRs enter Mihomo; other real IPs bypass."
exit 0
