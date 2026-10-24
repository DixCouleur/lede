#!/usr/bin/env bash
# Build a pinned source snapshot; never update the user's checkout or feeds.
set -euo pipefail
umask 022

repo=$(cd "$(dirname "$0")/.." && pwd)
cache=${AX6000_CACHE_DIR:-"$repo/.build-ax6000"}
mountpoint="$cache/mount"
image="$cache/build.sparsebundle"
lock="$repo/configs/redmi-ax6000-build.lock.json"
seed="$repo/configs/redmi-ax6000-minimal-openclash.config"
build_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("build_id", ""))' "$lock")
[[ "$build_id" =~ ^[a-zA-Z0-9_-]*$ ]] || { echo 'Invalid build identifier.'; exit 1; }
tree="$mountpoint/lede${build_id:+-$build_id}"
out="$repo/artifacts/ax6000${build_id:+/releases/$build_id}"
jobs=${AX6000_JOBS:-4}
[[ "$jobs" =~ ^[1-8]$ ]] || { echo 'AX6000_JOBS must be 1 through 8.'; exit 1; }
phase=${1:-all}
case "$phase" in prepare|download|packages|build|index|verify|all|menuconfig) ;; *) echo "Usage: $0 [prepare|download|packages|build|index|verify|all|menuconfig [feed-package...]]" >&2; exit 2 ;; esac
case "$(uname -s)/$(uname -m)" in
  Darwin/arm64) host_platform=darwin_arm64 ;;
  Linux/x86_64) host_platform=linux_amd64 ;;
  *) echo 'Supported build hosts: macOS ARM64 and Linux x86_64.' >&2; exit 1 ;;
esac
[[ "$repo" != *' '* && "$cache" != *' '* ]] || { echo 'OpenWrt build paths must not contain spaces.' >&2; exit 1; }

mkdir -p "$cache" "$mountpoint" "$out/logs"
if [[ "$host_platform" == darwin_arm64 ]]; then
  if [[ ! -d "$image" ]]; then
    hdiutil create -size 64g -type SPARSEBUNDLE -fs 'Case-sensitive APFS' -volname LEDE-AX6000 -nospotlight "$image"
  fi
  if ! mount | grep -Fq " on $mountpoint ("; then
    hdiutil attach -nobrowse -mountpoint "$mountpoint" "$image"
  fi
  export PATH="/opt/homebrew/opt/coreutils/libexec/gnubin:/opt/homebrew/opt/findutils/libexec/gnubin:/opt/homebrew/opt/gnu-tar/libexec/gnubin:/opt/homebrew/opt/gnu-sed/libexec/gnubin:/opt/homebrew/opt/grep/libexec/gnubin:/opt/homebrew/opt/gnu-getopt/bin:/opt/homebrew/opt/make/libexec/gnubin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
fi

make_bin=$(command -v gmake || command -v make)
patch_bin=$(command -v gpatch || command -v patch)
for tool in git curl rsync shasum xz; do
  command -v "$tool" >/dev/null || { echo "Missing build dependency: $tool" >&2; exit 1; }
done
python_boot=$(command -v python3)
mkdir -p "$mountpoint/host-bin"
if [[ "$host_platform" == darwin_arm64 ]] && command -v uv >/dev/null; then
  python_host=$(uv python find --no-project --no-python-downloads 3.11)
else
  python_host=$(command -v python3.11)
fi
"$python_host" -c 'from distutils import util'
ln -sf "$python_host" "$mountpoint/host-bin/python3.11"
ln -sf "$python_host" "$mountpoint/host-bin/python3"
ln -sf "$python_host" "$mountpoint/host-bin/python"
export PATH="$mountpoint/host-bin:$PATH"
export LC_ALL=C LANG=C
# XZ >= 5.6 defaults to multi-threaded streams, changing OpenWrt source hashes.
export XZ_OPT=-T1
unset GREP_OPTIONS C_INCLUDE_PATH CPLUS_INCLUDE_PATH LIBRARY_PATH CPATH

# Use the same pinned Go version on both supported build hosts.
go_version=$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["go_bootstrap"]["version"])' "$lock")
[[ "$go_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Invalid Go bootstrap version.' >&2; exit 1; }
go_archive="$cache/go${go_version}.${host_platform/_/-}.tar.gz"
go_sha=$("$python_boot" -c 'import json,sys; g=json.load(open(sys.argv[1]))["go_bootstrap"]; print(g.get("platforms", {}).get(sys.argv[2], g)["sha256"])' "$lock" "$host_platform")
if [[ ! -f "$go_archive" ]]; then
  go_url=$("$python_boot" -c 'import json,sys; g=json.load(open(sys.argv[1]))["go_bootstrap"]; print(g.get("platforms", {}).get(sys.argv[2], g)["url"])' "$lock" "$host_platform")
  curl -fL --retry 3 --connect-timeout 20 "$go_url" -o "$go_archive.part"
  printf '%s  %s\n' "$go_sha" "$go_archive.part" | shasum -a 256 -c -
  mv "$go_archive.part" "$go_archive"
fi
printf '%s  %s\n' "$go_sha" "$go_archive" | shasum -a 256 -c -
if [[ ! -x "$mountpoint/host-go/go/bin/go" ]] || \
   [[ "$(GOTOOLCHAIN=local "$mountpoint/host-go/go/bin/go" env GOVERSION)" != "go$go_version" ]]; then
  mkdir -p "$mountpoint/host-go"
  go_tmp=$(mktemp -d "$mountpoint/.go-bootstrap.XXXXXXXX")
  tar -xzf "$go_archive" -C "$go_tmp"
  [[ "$(GOTOOLCHAIN=local "$go_tmp/go/bin/go" env GOVERSION)" == "go$go_version" ]] || { echo 'Go bootstrap binary version mismatch.' >&2; exit 1; }
  if [[ -e "$mountpoint/host-go/go" ]]; then
    mv "$mountpoint/host-go/go" "$go_tmp/previous-go"
  fi
  mv "$go_tmp/go" "$mountpoint/host-go/go"
  rm -rf "$go_tmp"
fi
export PATH="$mountpoint/host-go/go/bin:$PATH"
export GOTOOLCHAIN=local

snapshot() {
  local original=$1 revision=$2 dest=$3 source_name=$4 source_url
  # A fresh Actions checkout has no local feeds or historical pinned objects.
  # Fetch commits without changing existing working trees or branch refs.
  if ! git -C "$original" cat-file -e "$revision^{commit}" 2>/dev/null; then
    source_url=$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_repositories"][sys.argv[2]])' "$lock" "$source_name")
    if [[ ! -e "$original/.git" ]]; then
      [[ ! -d "$original" || -z "$(ls -A "$original")" ]] || { echo "Refusing to replace non-repository source directory: $original" >&2; exit 1; }
      git init -q "$original"
      git -C "$original" fetch --depth 1 --no-tags "$source_url" "$revision"
    else
      git -C "$original" fetch --no-tags "$source_url" "$revision"
    fi
  fi
  git -C "$original" cat-file -e "$revision^{commit}"
  if [[ -f "$dest/.ax6000-snapshot" ]]; then
    [[ "$(cat "$dest/.ax6000-snapshot")" == "$revision" ]] || { echo "Snapshot revision mismatch: $dest" >&2; exit 1; }
    return
  fi
  mkdir -p "$dest"
  git -C "$original" archive "$revision" | tar -x -C "$dest"
  # Copy Git metadata for package version generation, without touching the original.
  local gitdir
  gitdir=$(git -C "$original" rev-parse --absolute-git-dir)
  /usr/bin/rsync -a "$gitdir/" "$dest/.git/"
  git --git-dir="$dest/.git" update-ref --no-deref HEAD "$revision"
  printf '%s\n' "$revision" > "$dest/.ax6000-snapshot"
}
revision=$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["lede"])' "$lock")
snapshot "$repo" "$revision" "$tree" lede
while IFS=$'\t' read -r name revision; do
  snapshot "$repo/feeds/$name" "$revision" "$tree/feeds/$name" "$name"
done < <("$python_boot" -c 'import json,sys; [print(k+"\t"+v) for k,v in json.load(open(sys.argv[1]))["feeds"].items()]' "$lock")
platform_marker="$tree/.ax6000-build-platform"
if [[ -f "$platform_marker" ]]; then
  [[ "$(cat "$platform_marker")" == "$host_platform" ]] || { echo 'Build host changed; use a separate AX6000_CACHE_DIR.' >&2; exit 1; }
fi
printf '%s\n' "$host_platform" > "$platform_marker"
cp "$lock" "$tree/.ax6000-build-lock.json"
mkdir -p "$tree/.ax6000-applied-patches"
for build_patch in "$repo/configs/patches/"*.patch; do
  [[ -f "$build_patch" ]] || continue
  patch_sha=$(shasum -a 256 "$build_patch" | cut -d ' ' -f1)
  if [[ "$host_platform" == linux_amd64 ]]; then
    case "$(basename "$build_patch")" in
      001-*|002-*|003-*|004-*|007-*|021-*)
        mkdir -p "$tree/.ax6000-skipped-patches"
        printf '%s\n' "$patch_sha" > "$tree/.ax6000-skipped-patches/$(basename "$build_patch").sha256"
        continue ;;
    esac
  fi
  patch_record="$tree/.ax6000-applied-patches/$(basename "$build_patch").sha256"
  if [[ -f "$patch_record" ]]; then
    [[ "$(cat "$patch_record")" == "$patch_sha" ]] || { echo "Applied patch changed: $build_patch" >&2; exit 1; }
  else
    (cd "$tree" && "$patch_bin" -p1 --forward --batch --no-backup-if-mismatch < "$build_patch")
    printf '%s\n' "$patch_sha" > "$patch_record"
  fi
done

# Overlay the verified upstream Argon release onto the pinned LEDE LuCI recipe.
# Packaging stays LEDE-native; Argon 3 owns its settings and translations.
argon_version=$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["argon"]["version"])' "$lock")
argon_url=$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["argon"]["url"])' "$lock")
argon_sha=$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["argon"]["sha256"])' "$lock")
argon_patch="$repo/configs/ax6000/argon.patch"
argon_patch_sha=$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["argon"].get("source_patch_sha256", "none"))' "$lock")
if [[ "$argon_patch_sha" != none ]]; then
  printf '%s  %s\n' "$argon_patch_sha" "$argon_patch" | shasum -a 256 -c -
fi
argon_archive="$cache/argon-v${argon_version}.tar.gz"
if [[ ! -f "$argon_archive" ]]; then
  curl -fL --retry 3 --connect-timeout 20 "$argon_url" -o "$argon_archive.part"
  printf '%s  %s\n' "$argon_sha" "$argon_archive.part" | shasum -a 256 -c -
  mv "$argon_archive.part" "$argon_archive"
fi
printf '%s  %s\n' "$argon_sha" "$argon_archive" | shasum -a 256 -c -
argon_marker="$tree/feeds/luci/themes/luci-theme-argon/.ax6000-upstream-source-sha256"
if [[ -f "$argon_marker" ]]; then
  [[ "$(cat "$argon_marker")" == "$argon_sha $argon_patch_sha" ]] || { echo 'Argon source/patch marker mismatch.' >&2; exit 1; }
else
  argon_tmp=$(mktemp -d "$mountpoint/.argon.XXXXXXXX")
  tar -xzf "$argon_archive" -C "$argon_tmp"
  argon_source="$argon_tmp/luci-theme-argon-$argon_version"
  [[ -f "$argon_source/Makefile" ]] || { echo 'Argon source layout mismatch.' >&2; exit 1; }
  if [[ "$argon_patch_sha" != none ]]; then
    (cd "$argon_source" && "$patch_bin" -p1 --forward --batch --no-backup-if-mismatch < "$argon_patch")
  fi
  for argon_dir in htdocs less root ucode po; do
    if [[ -d "$argon_source/$argon_dir" ]]; then
      /usr/bin/rsync -a --delete "$argon_source/$argon_dir/" "$tree/feeds/luci/themes/luci-theme-argon/$argon_dir/"
    fi
  done
  if [[ -d "$argon_source/compat/luci-app-argon-config" ]]; then
    /usr/bin/rsync -a --delete "$argon_source/compat/luci-app-argon-config/" "$tree/feeds/luci/applications/luci-app-argon-config/"
    "$python_boot" - "$lock" "$tree/feeds/luci/applications/luci-app-argon-config/Makefile" <<'PY'
import json,re,sys
from pathlib import Path
version = json.load(open(sys.argv[1]))['argon']
recipe = Path(sys.argv[2])
text = recipe.read_text()
for key, value in [('PKG_VERSION', version['version']), ('PKG_RELEASE', version['release'])]:
    text, count = re.subn(r'^' + key + r':=.*$', key + ':=' + value, text, flags=re.M)
    assert count == 1, key
recipe.write_text(text)
PY
  fi
  printf '%s\n' "$argon_sha $argon_patch_sha" > "$argon_marker"
  rm -rf "$argon_tmp"
fi
if [[ "$argon_patch_sha" != none ]]; then
  mkdir -p "$tree/.ax6000-source-patches"
  cp "$argon_patch" "$tree/.ax6000-source-patches/argon.patch"
fi

# Replace the feed's minimal AdGuard UI with the user's pinned upstream plugin.
agh_ui_revision=$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["luci_adguardhome"]["revision"])' "$lock")
agh_ui_sha=$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["luci_adguardhome"]["sha256"])' "$lock")
agh_ui_archive="$cache/luci-app-adguardhome-${agh_ui_revision:0:8}.tar.gz"
if [[ ! -f "$agh_ui_archive" ]]; then
  agh_ui_url=$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["luci_adguardhome"]["url"])' "$lock")
  curl -fL --retry 3 --connect-timeout 20 "$agh_ui_url" -o "$agh_ui_archive.part"
  printf '%s  %s\n' "$agh_ui_sha" "$agh_ui_archive.part" | shasum -a 256 -c -
  mv "$agh_ui_archive.part" "$agh_ui_archive"
fi
printf '%s  %s\n' "$agh_ui_sha" "$agh_ui_archive" | shasum -a 256 -c -
agh_ui_patch="$repo/configs/ax6000/luci-adguardhome.patch"
agh_ui_patch_sha=$(shasum -a 256 "$agh_ui_patch" | cut -d ' ' -f1)
agh_ui_marker="$tree/feeds/luci/applications/luci-app-adguardhome/.ax6000-upstream-source"
if [[ ! -f "$agh_ui_marker" ]] || [[ "$(cat "$agh_ui_marker")" != "$agh_ui_sha $agh_ui_patch_sha" ]]; then
  agh_ui_tmp=$(mktemp -d "$mountpoint/.adguardhome-ui.XXXXXXXX")
  tar -xzf "$agh_ui_archive" -C "$agh_ui_tmp"
  agh_ui_source="$agh_ui_tmp/luci-app-adguardhome-$agh_ui_revision"
  (cd "$agh_ui_source" && "$patch_bin" -p1 --forward --batch --no-backup-if-mismatch < "$agh_ui_patch")
  "$python_boot" - "$lock" "$agh_ui_source/root/usr/share/AdGuardHome/ax6000-source.json" <<'PY'
import json,sys
from pathlib import Path
Path(sys.argv[2]).write_text(json.dumps(json.load(open(sys.argv[1]))['luci_adguardhome'], indent=2) + '\n')
PY
  /usr/bin/rsync -a --delete "$agh_ui_source/" "$tree/feeds/luci/applications/luci-app-adguardhome/"
  printf '%s\n' "$agh_ui_sha $agh_ui_patch_sha" > "$agh_ui_marker"
  rm -rf "$agh_ui_tmp"
  touch "$tree/feeds/luci/applications/luci-app-adguardhome/Makefile"
  if [[ -f "$tree/.config" ]]; then
    (cd "$tree" && "$make_bin" package/feeds/luci/luci-app-adguardhome/clean V=s) > "$out/logs/adguardhome-ui-clean.log" 2>&1
  fi
fi

# Pin downloaded dashboard and network data independently of the LuCI snapshot.
while IFS=$'\t' read -r asset_name asset_file asset_url asset_sha; do
  asset_path="$cache/$asset_file"
  if [[ ! -f "$asset_path" ]]; then
    bundled_asset="$repo/configs/ax6000/data-snapshots/$asset_file"
    if [[ -f "$bundled_asset" ]]; then
      cp "$bundled_asset" "$asset_path.part"
    else
      curl -fL --retry 3 --connect-timeout 20 "$asset_url" -o "$asset_path.part"
    fi
    printf '%s  %s\n' "$asset_sha" "$asset_path.part" | shasum -a 256 -c -
    mv "$asset_path.part" "$asset_path"
  fi
  printf '%s  %s\n' "$asset_sha" "$asset_path" | shasum -a 256 -c -
done < <("$python_boot" -c 'import json,sys; [print(k+"\t"+v["filename"]+"\t"+v["url"]+"\t"+v["sha256"]) for k,v in json.load(open(sys.argv[1])).get("assets", {}).items()]' "$lock")

zashboard_archive="$cache/$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["assets"]["zashboard"]["filename"])' "$lock")"
dashboard_dir="$tree/feeds/luci/applications/luci-app-openclash/root/usr/share/openclash/ui/zashboard"
"$python_boot" - "$zashboard_archive" "$dashboard_dir" "$lock" <<'PY'
import json,sys,zipfile,shutil,tempfile
from pathlib import Path
source, target, lock = Path(sys.argv[1]), Path(sys.argv[2]), json.load(open(sys.argv[3]))
metadata = lock['assets']['zashboard']
marker = target / 'ax6000-source.json'
if not marker.exists() or json.loads(marker.read_text()) != metadata:
    with zipfile.ZipFile(source) as archive, tempfile.TemporaryDirectory(prefix='ax6000-dashboard-') as tmp:
        for name in archive.namelist():
            if Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('Unsafe dashboard archive entry')
        archive.extractall(tmp)
        indexes = list(Path(tmp).rglob('index.html'))
        if len(indexes) != 1:
            raise ValueError('Unexpected dashboard layout')
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(indexes[0].parent, target)
    marker.write_text(json.dumps(metadata, indent=2) + '\n')
PY

run_make() {
  local logname=$1
  shift
  if [[ -f "$out/logs/$logname.log" ]]; then
    mv "$out/logs/$logname.log" "$out/logs/$logname-$(date -u +%Y%m%dT%H%M%SZ).log"
  fi
  (cd "$tree" && "$make_bin" "$@") 2>&1 | tee "$out/logs/$logname.log"
}

write_image_defaults() {
  /usr/bin/rsync -a "$repo/configs/ax6000/files/" "$tree/files/"
  local geosite_source
  geosite_source="$cache/$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["assets"]["geosite"]["filename"])' "$lock")"
  "$python_boot" - "$lock" "$cache" "$tree/files" <<'PY'
import json,sys,shutil,ipaddress
from pathlib import Path
assets, cache, files = json.load(open(sys.argv[1]))['assets'], Path(sys.argv[2]), Path(sys.argv[3])
for key, destination in [('country_mmdb', 'Country.mmdb'), ('cn_ipv4', 'china_ip_route.ipset'), ('cn_ipv6', 'china_ip6_route.ipset')]:
    target = files / 'etc/openclash' / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cache / assets[key]['filename'], target)
networks = [str(ipaddress.ip_network(line)) for line in (cache / assets['telegram']['filename']).read_text().splitlines() if line.strip() and ipaddress.ip_network(line).version == 4]
(files / 'etc/mosdns/data/proxy-ip.txt').write_text('\n'.join(networks) + '\n')
PY
  "$python_boot" "$repo/scripts/ax6000_geosite.py" trim \
    "$geosite_source" \
    "$tree/files/etc/openclash/GeoSite.dat" --manifest "$out/geosite-manifest.json"
  "$python_boot" "$repo/scripts/ax6000_mosdns_data.py" \
    "$tree/files/etc/openclash/GeoSite.dat" \
    "$tree/files/etc/openclash/china_ip_route.ipset" \
    "$tree/files/etc/mosdns/data"
  chmod 0755 "$tree/files/etc/openclash/custom/openclash_custom_firewall_rules.sh"
  chmod 0600 "$tree/files/etc/adguardhome/adguardhome.yaml"
  chmod 0755 "$tree/files/etc/openclash/custom/openclash_custom_overwrite.sh"
  chmod 0755 "$tree/files/usr/share/adguardhome/ax6000-prepare.sh"
  chmod 0755 "$tree/files/usr/share/openclash/adguardhome_dns.rb"
  chmod 0755 "$tree/files/usr/share/openclash/ax6000-core-check.sh"
  chmod 0755 "$tree/files/usr/share/openclash/ax6000-core-run.sh"
  chmod 0755 "$tree/files/usr/share/openclash/ax6000-dns-overwrite.rb"
  chmod 0755 "$tree/files/usr/share/openclash/ax6000-core-version.sh"
  chmod 0755 "$tree/files/usr/share/turboacc/ax6000-wed.sh"
  mkdir -p "$tree/files/bin" "$tree/files/etc/uci-defaults"
  sed 's/192\.168\.1\.1/192.168.199.1/' \
    "$tree/package/base-files/files/bin/config_generate" > "$tree/files/bin/config_generate"
  chmod 0755 "$tree/files/bin/config_generate"
  cat > "$tree/files/etc/uci-defaults/99-ax6000-minimal" <<'EOF'
#!/bin/sh
uci -q set system.@system[0].timezone='CST-8'
uci -q set system.@system[0].zonename='Asia/Shanghai'
uci -q set luci.main.lang='zh_cn'
uci -q set luci.main.mediaurlbase='/luci-static/argon'
wifi config
. /lib/functions.sh
config_load wireless
enable_radio() { uci -q set "wireless.$1.disabled=0"; }
config_foreach enable_radio wifi-device
uci -q set openclash.config.enable='0'
uci -q set openclash.config.core_type='Meta'
uci -q set openclash.config.core_version='linux-arm64'
uci -q set openclash.config.en_mode='fake-ip'
uci -q set openclash.config.operation_mode='fake-ip'
uci -q set openclash.config.enable_redirect_dns='0'
uci -q set openclash.config.adguardhome_dns='1'
uci -q set openclash.config.dns_port='7874'
uci -q set openclash.config.enable_custom_dns='0'
uci -q set openclash.config.enable_respect_rules='0'
uci -q set openclash.config.append_wan_dns='0'
uci -q set openclash.config.china_ip_route='1'
# OpenClash exposes these defaults in LuCI and reapplies them when importing.
uci -q set openclash.config.enable_tcp_concurrent='1'
uci -q set openclash.config.enable_unified_delay='1'
uci -q set openclash.config.log_level='warning'
uci -q set openclash.config.geodata_loader='memconservative'
uci -q set openclash.config.enable_meta_sniffer='1'
uci -q set openclash.config.enable_meta_sniffer_pure_ip='0'
uci -q set openclash.config.default_dashboard='zashboard'
uci -q set openclash.config.geosite_auto_update='0'
# Netifd's regular packet steering distributes RX/TX work without forcing every CPU.
uci -q set network.globals.packet_steering='1'
# Keep client DNS at AdGuardHome; visible in LuCI's port-forwarding table.
uci -q set firewall.ax6000_dns=redirect
uci -q set firewall.ax6000_dns.name='LAN DNS to AdGuardHome'
uci -q set firewall.ax6000_dns.src='lan'
uci -q set firewall.ax6000_dns.dest='lan'
uci -q set firewall.ax6000_dns.src_dport='53'
uci -q set firewall.ax6000_dns.dest_ip='192.168.199.1'
uci -q set firewall.ax6000_dns.dest_port='53'
uci -q set firewall.ax6000_dns.proto='tcp udp'
uci -q set firewall.ax6000_dns.target='DNAT'
uci -q set firewall.ax6000_dns.reflection='0'
# AdGuard Home provides DHCPv4; IPv6 addressing and advertisements are disabled.
uci -q delete dhcp.@dnsmasq[0]
uci -q set dhcp.odhcpd.maindhcp='0'
uci -q set dhcp.lan.dhcpv4='disabled'
uci -q set dhcp.lan.dhcpv6='disabled'
uci -q set dhcp.lan.ra='disabled'
uci -q set dhcp.lan.ndp='disabled'
uci -q set dhcp.lan.ra_slaac='0'
uci -q set dhcp.lan.ignore='0'
uci -q set AdGuardHome.AdGuardHome.enabled='1'
uci -q set AdGuardHome.AdGuardHome.httpport='3000'
uci -q set AdGuardHome.AdGuardHome.httpbind='0.0.0.0'
uci -q set AdGuardHome.AdGuardHome.configpath='/etc/adguardhome/adguardhome.yaml'
uci -q set AdGuardHome.AdGuardHome.workdir='/etc/adguardhome/runtime'
uci -q set AdGuardHome.AdGuardHome.binpath='/usr/bin/AdGuardHome'
uci -q set AdGuardHome.AdGuardHome.logfile='syslog'
uci -q set AdGuardHome.AdGuardHome.redirect='none'
uci -q set AdGuardHome.AdGuardHome.waitonboot='0'
uci -q set AdGuardHome.AdGuardHome.crontab=''
uci -q set AdGuardHome.AdGuardHome.ucitracktest='1'
uci -q set AdGuardHome.AdGuardHome.upprotect='$configpath'
mkdir -p /etc/crontabs
touch /etc/crontabs/root
rm -f /etc/rc.d/S19adguardhome /etc/rc.d/K89adguardhome
/etc/init.d/AdGuardHome enable
/etc/init.d/mosdns enable
/etc/init.d/turboacc enable
uci commit
exit 0
EOF
  chmod 0755 "$tree/files/etc/uci-defaults/99-ax6000-minimal"
}

prepare() {
  # New translation directories require invalidating cached package metadata.
  touch "$tree/feeds/luci/applications/luci-app-adguardhome/Makefile" "$tree/feeds/luci/applications/luci-app-openclash/Makefile" "$tree/feeds/luci/applications/luci-app-turboacc/Makefile"
  echo "Indexing and installing pinned feeds; log: $out/logs/feeds.log"
  if ! (cd "$tree" && ./scripts/feeds update -i packages luci && ./scripts/feeds uninstall -a &&
      ./scripts/feeds install -p luci luci-light luci-compat luci-app-openclash luci-theme-argon luci-app-argon-config luci-app-adguardhome luci-app-turboacc luci-app-mosdns &&
      ./scripts/feeds install -p packages ruby ruby-yaml ruby-json bash curl unzip mosdns geo2txt) > "$out/logs/feeds.log" 2>&1; then
    tail -n 60 "$out/logs/feeds.log" >&2
    return 1
  fi
  cp "$seed" "$tree/.config"
  if [[ "$host_platform" == linux_amd64 ]]; then
    mkdir -p "$cache/downloads"
    if [[ ! -e "$tree/dl" ]]; then ln -s "$cache/downloads" "$tree/dl"; fi
  fi
  if [[ "${AX6000_CCACHE:-0}" == 1 ]]; then
    printf 'CONFIG_CCACHE=y\nCONFIG_CCACHE_DIR="%s"\n' "$cache/ccache" >> "$tree/.config"
  fi
  printf 'CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT="%s"\n' "$mountpoint/host-go/go" >> "$tree/.config"
  run_make defconfig defconfig
  "$python_boot" "$repo/scripts/verify-redmi-ax6000.py" config "$tree"
  run_make prereq prereq
  local url sha archive
  url=$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["mihomo"]["url"])' "$lock")
  sha=$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["mihomo"]["sha256"])' "$lock")
  archive="$cache/mihomo-linux-arm64-v$("$python_boot" -c 'import json,sys; print(json.load(open(sys.argv[1]))["mihomo"]["version"])' "$lock").gz"
  if [[ ! -f "$archive" ]]; then
    curl -fL --retry 3 --connect-timeout 20 "$url" -o "$archive.part"
    printf '%s  %s\n' "$sha" "$archive.part" | shasum -a 256 -c -
    mv "$archive.part" "$archive"
  fi
  printf '%s  %s\n' "$sha" "$archive" | shasum -a 256 -c -
  mkdir -p "$tree/files/etc/openclash/core" "$tree/files/etc/uci-defaults"
  gzip -dc "$archive" > "$tree/files/etc/openclash/core/clash_meta"
  chmod 0755 "$tree/files/etc/openclash/core/clash_meta"
  write_image_defaults
  "$python_boot" "$repo/scripts/verify-redmi-ax6000.py" core "$tree/files/etc/openclash/core/clash_meta"
}

verify() {
  "$python_boot" "$repo/scripts/verify-redmi-ax6000.py" image "$tree" | tee "$out/verification.txt"
  local firmware
  firmware=$(find "$tree/bin/targets/mediatek/filogic" -maxdepth 1 -name '*xiaomi_redmi-router-ax6000-squashfs-sysupgrade.bin')
  [[ -f "$firmware" ]] || { echo 'AX6000 firmware was not generated.' >&2; exit 1; }
  cp "$firmware" "$out/lede-redmi-ax6000-minimal-openclash-sysupgrade.bin"
  cp "$tree/.config" "$out/full.config"
  cp "$seed" "$out/config.seed"
  mkdir -p "$out/image-files"
  /usr/bin/rsync -a "$repo/configs/ax6000/files/" "$out/image-files/"
  (cd "$tree" && ./scripts/diffconfig.sh) > "$out/diffconfig.config"
  cp "$lock" "$out/build.lock.json"
  cp "$repo/configs/ax6000/geosite-keep.json" "$out/geosite-keep.json"
  cp "$repo/scripts/ax6000_geosite.py" "$out/ax6000_geosite.py"
  cp "$repo/scripts/ax6000_mosdns_data.py" "$out/ax6000_mosdns_data.py"
  /usr/bin/rsync -a "$tree/files/etc/mosdns/" "$out/image-files/etc/mosdns/"
  cp "$tree/files/etc/openclash/GeoSite.dat" "$out/image-files/etc/openclash/GeoSite.dat"
  for resource in Country.mmdb china_ip_route.ipset china_ip6_route.ipset; do
    cp "$tree/files/etc/openclash/$resource" "$out/image-files/etc/openclash/$resource"
  done
  mkdir -p "$out/source-archives"
  cp "$argon_archive" "$out/source-archives/"
  cp "$agh_ui_archive" "$out/source-archives/"
  "$python_boot" - "$lock" "$cache" "$out/source-archives" <<'PY'
import json,sys,shutil
from pathlib import Path
lock, cache, destination = json.load(open(sys.argv[1])), Path(sys.argv[2]), Path(sys.argv[3])
for asset in lock['assets'].values():
    shutil.copyfile(cache / asset['filename'], destination / asset['filename'])
shutil.copyfile(cache / ('mihomo-linux-arm64-v' + lock['mihomo']['version'] + '.gz'), destination / ('mihomo-linux-arm64-v' + lock['mihomo']['version'] + '.gz'))
PY
  cp "$agh_ui_patch" "$out/luci-adguardhome.patch"
  mkdir -p "$out/build-patches"
  cp "$repo/configs/patches/"*.patch "$out/build-patches/"
  cp "$repo/configs/patches/README.md" "$out/build-patches/README.md"
  "$python_boot" - "$tree" "$out/build-patches/receipt.json" <<'PYRECEIPT'
import json, sys
from pathlib import Path
source, destination = map(Path, sys.argv[1:])
receipt = {"platform": (source / ".ax6000-build-platform").read_text().strip()}
for state in ["applied", "skipped"]:
    receipt[state] = {p.name.removesuffix(".sha256"): p.read_text().strip()
                      for p in sorted((source / (".ax6000-" + state + "-patches")).glob("*.sha256"))}
destination.write_text(json.dumps(receipt, indent=2) + "\n")
PYRECEIPT
  if [[ "$argon_patch_sha" != none ]]; then
    cp "$argon_patch" "$out/build-patches/argon-source.patch"
  fi
  (cd "$tree/dl" && find . -maxdepth 1 -type f -exec shasum -a 256 '{}' \;) > "$out/source-SHA256SUMS"
  cp "$tree/bin/targets/mediatek/filogic/"*.manifest "$out/"
  cp "$tree/bin/targets/mediatek/filogic/"*.buildinfo "$out/"
  cp "$tree/bin/targets/mediatek/filogic/profiles.json" "$out/"
  mkdir -p "$out/packages"
  find "$tree/bin" -type f -name '*.ipk' -exec cp '{}' "$out/packages/" \;
  # Preserve signed indexes so opkg can resolve dependencies from a matching feed.
  mkdir -p "$out/opkg-repository/targets/mediatek/filogic" "$out/opkg-repository/packages"
  /usr/bin/rsync -a "$tree/bin/targets/mediatek/filogic/packages/" "$out/opkg-repository/targets/mediatek/filogic/packages/"
  /usr/bin/rsync -a "$tree/bin/packages/" "$out/opkg-repository/packages/"
  cp "$tree/key-build.pub" "$out/opkg-repository/key-build.pub"
  cp "$repo/docs/redmi-ax6000-minimal-openclash.md" "$out/README.md"
  (cd "$out" && shasum -a 256 lede-redmi-ax6000-minimal-openclash-sysupgrade.bin > SHA256SUMS)
  echo "Firmware exported to $out"
}

case "$phase" in
  menuconfig)
    [[ -f "$tree/.config" ]] || { echo 'Run prepare before menuconfig.' >&2; exit 1; }
    shift
    for feed_package in "$@"; do
      [[ "$feed_package" =~ ^[a-zA-Z0-9][a-zA-Z0-9+_.-]*$ ]] || { echo "Invalid package name: $feed_package" >&2; exit 2; }
    done
    if [[ $# -gt 0 ]]; then (cd "$tree" && ./scripts/feeds install "$@"); fi
    (cd "$tree" && "$make_bin" menuconfig)
    ;;
  prepare) prepare ;;
  packages) run_make mosdns-packages package/feeds/packages/mosdns/compile package/feeds/packages/geo2txt/compile package/feeds/luci/luci-app-mosdns/compile package/feeds/luci/luci-app-adguardhome/compile -j2 V=s ;;
  download) run_make download download -j8 V=s ;;
  build) write_image_defaults; run_make build -j"$jobs" V=s; verify ;;
  index) run_make package-index package/index V=s; verify ;;
  verify) verify ;;
  all) prepare; run_make download download -j8 V=s; run_make build -j"$jobs" V=s; verify ;;
esac
