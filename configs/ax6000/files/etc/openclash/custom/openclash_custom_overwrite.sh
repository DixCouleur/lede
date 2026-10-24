#!/bin/sh
# Router subscription owns DNS, rules and performance policy.
# Only retain OpenClash's local DNS/TUN integration adapter.
helper=${AX6000_DNS_HELPER:-/usr/share/openclash/ax6000-dns-overwrite.rb}
exec ruby -ryaml -E UTF-8 "$helper" "$1"
