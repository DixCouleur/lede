# Pinned build patches

`020-upnp-private-wan-luci-option.patch` connects the existing LuCI "Force
forwarding" checkbox to the pinned miniupnpd 2.3.9 backend's
`ext_allow_private_ipv4` option. It does not change the minimal firmware's package
selection; UPnP is built separately for optional installation on the running router.

Linux x86_64 builds skip the macOS host-tool fixes numbered 001–004, 007 and 021. The exported `build-patches/receipt.json` records applied and skipped patch hashes for the build host; target/runtime patches apply on both platforms.

`001-elfutils-darwin-portability.patch` ports the official OpenWrt host elfutils 0.192 recipe and patches from commit `8635eeedc38cbd49fe228442880097ebbdb2f01b`. It supplies missing GNU libc interfaces through gnulib and disables ELF-specific linker probes on Darwin. Target packages and kernel sources are unchanged.

Source: https://github.com/openwrt/openwrt/tree/8635eeedc38cbd49fe228442880097ebbdb2f01b/tools/elfutils

`002-elfutils-gnulib-generator.patch` links the libcpu code generator with the
complete gnulib archive. The pinned LEDE gnulib 202401 emits some replacement
objects without the newer `libgnu_la-` prefix, so the upstream object wildcard
does not supply `obstack_printf` for this host executable.

`003-elfutils-explicit-subdirs.patch` passes the selected build subdirectories
explicitly. This LEDE host-build framework does not yet consume `PKG_SUBDIRS`
from the newer upstream recipe; otherwise disabled debuginfod subdirectories
receive the executable override intended for `src`.

`004-coreutils-release-gnulib.patch` uses coreutils 9.5 release-bundled gnulib and private modules without regenerating them with the older shared gnulib. Regeneration otherwise introduces template substitutions and drops private modules such as fd-reopen, breaking the Darwin host tools. The source archive and its verified hash are unchanged.

`005-openclash-adguardhome-dns.patch` lets OpenClash switch dnsmasq upstreams while DNS firewall redirection remains disabled. The private `adguardhome_dns=1` option preserves AdGuard Home as the client-facing resolver; stock stop logic restores the saved direct upstreams.

`006-adguardhome-luci-zh-hans.patch` adds Simplified Chinese strings for the pinned LuCI AdGuard Home panel.

`007-golang-native-darwin-bootstrap.patch` bootstraps the pinned Go host compiler directly from a checked external native compiler on Darwin ARM64. This avoids the old Go 1.17 bootstrap whose Mach-O output lacks LC_UUID and cannot run on the current macOS. Other host paths retain the original bootstrap chain.

`008-adguardhome-dhcp-dns-owner.patch` supersedes the dnsmasq backend from patch 005: OpenClash changes AdGuard Home upstreams via its live API, restores the original upstreams on stop, prevents DNS firewall bypass, and depends on AdGuard Home instead of dnsmasq. The AdGuard init runs the pre-start helper for lease persistence and the current LAN ULA DHCPv6 pool. odhcpd only sends IPv6 RA; its DHCP services are disabled.

`009-argon-upstream-version.patch` sets the native LEDE LuCI recipe to Argon 3.1.0 local release 1, adds its ucode math and updater dependencies (`flock`, `coreutils`, `coreutils-timeout`) and moves the `argon-config` translation domain into the theme. The build wrapper overlays the official, SHA-256-pinned theme, including its settings, translations and configuration migration scripts. It replaces the old settings application with the upstream empty compatibility package so both packages do not own the same files. Custom branding and backgrounds are retained by the theme's sysupgrade keep list. The separately pinned `configs/ax6000/argon.patch` requires a full HEX-color match instead of accepting a prefix before a newline; it is applied after extracting the official source and replayed by image verification.

`010-turboacc-persist-wed-boot-option.patch` routes WED changes through the AX6000 helper, which saves the mt7915e module option in `/etc/modules.conf`. It leaves the live module unchanged; changing WED in Turbo ACC takes effect after reboot as stated by the panel.

`011-openclash-trim-assets.patch` excludes bundled MetaCubeXD assets, selects
Zashboard by default and uses its fallback in configuration conversion. Both the
OpenClash IPK and firmware contain the byte-preserving GeoSite subset generated
by `scripts/ax6000_geosite.py` from the pinned feed data. The generated file is a
package input dependency; its categories and hashes are locked in
`configs/ax6000/geosite-keep.json`. Build through the AX6000 wrapper so that this
file exists before packaging.

`012-adguardhome-single-service.patch` makes the packaged lower-case init script
a compatibility alias for the rufengsuixing plugin's `AdGuardHome` service. Only
one procd instance and boot entry run the core. The pinned upstream UI archive is
overlaid by the wrapper and adapted using `configs/ax6000/luci-adguardhome.patch`:
current YAML Web/password settings, preserved DNS/DHCP preparation, packaged core
paths, the existing unprivileged user/capabilities, and no dnsmasq redirect modes.
The native Web listener defaults to `0.0.0.0:3000`. The adapted procd service
uses ujail to retain ambient DNS/DHCP capabilities after changing user, and
keeps the existing `GOGC=50` / 128 MiB Go memory target.

`013-openclash-single-core-validation.patch` routes subscription checks through
`ax6000-core-check.sh`. The helper stops the running core, validates with a
90-second timeout, and restores the service after success or failure. Service
actions and validation share a lock; validation preserves subscription jobs.
The production and validation cores use `GOGC=50` and a 128 MiB Go memory target
(a soft target, not an RSS limit).

`014-openclash-cached-core-version.patch` replaces LuCI/debug `clash_meta -v`
forks with `ax6000-core-version.sh`. Running-core versions come from the local
authenticated API and a file-identity cache. Offline version queries share the
core-operation lock and cannot run alongside production or validation. This
also avoids concurrent UPX decompression when a preserved core is compressed.
The core updater uses the same version helper for its current version and the
serial checker (`--version`) for a downloaded candidate before replacement.

`015-mosdns-custom-profile-low-memory.patch` keeps the stock LuCI MosDNS panel
and MosDNS 5.3.4 while removing the full v2ray GeoIP/GeoSite package dependency.
The wrapper exports the pinned, trimmed rules as MosDNS text sets. The custom
profile skips automatic DAT exports; the service uses `GOGC=50` and a 32 MiB Go
memory target. `geo2txt` remains available for deliberate manual exports.

`016-mosdns-fw3-stop-compat.patch` guards nftables cleanup on this fw3 image.
`017-mosdns-custom-rule-description.patch` clarifies that the stock rule editors
also apply to custom profiles that reference their files.
`018-mosdns-optional-dnsmasq.patch` skips dnsmasq reload when it is absent.

`019-mosdns-stats-execution-errors.patch` adds package patch 227 and bumps MosDNS
to 5.3.4-15. The stats API reports sequence execution errors as SERVFAIL, matching
the DNS server's actual response, rather than counting them as intentional local
blocks. Existing blacklist/hosts blocking and upstream NXDOMAIN handling remain.

`021-cmake-darwin-uuid-type.patch` imports the Apple SDK UUID string type before
CPack includes CoreServices. The util-linux UUID header in the host staging
directory can shadow the SDK UUID header during parallel builds and omit
`uuid_string_t`. This patch affects the macOS build tool only; it has no router
payload. Related upstream report: https://github.com/openwrt/openwrt/issues/17683.

`022-openclash-subscription-start-order.patch` exposes the background startup
check PID to `ax6000-core-check.sh`. The external checker waits for that process
to finish firewall setup and cache writes after rc.common commits procd service
registration. Replacing the active subscription also invalidates the quick-start
cache. This prevents the old runtime YAML from being recorded against the new
subscription and lets the native update job request its restart. Starts retain
the upstream asynchronous behavior inside `start_service`.
For OpenClash 0.48.002 the cache is also invalidated when the upstream `norestart`
mode defers the restart, so a later start cannot reuse the replaced configuration.

`023-openclash-subscription-integrity.patch` runs the AX6000 Ruby subscription
guard before core validation and again after node filtering, before commit. It
rejects empty responses, a loss of more than 75 percent of inline nodes when the
old subscription has at least eight, or the loss of node reachability in at least
75 percent of four or more matching automatic groups. Provider-backed groups and
normal node changes remain supported. Rejected downloads retain the current YAML
and quick-start cache; the initial check does not stop the production core. Parser
errors expose only their class so credentials are not echoed to the service log.
The native update log and LuCI subscription operation report the refusal.
