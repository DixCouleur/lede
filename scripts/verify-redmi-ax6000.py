#!/usr/bin/env python3
"""Validate the chosen package set and the actual sysupgrade payload."""
import hashlib
import gzip
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from ax6000_geosite import check_geosite

PROFILE = "xiaomi_redmi-router-ax6000"
BOARD = "xiaomi,redmi-router-ax6000"
REQUIRED = {
    "base-files", "busybox", "dropbear", "netifd", "opkg", "firewall", "procd-ujail",
    "ruby-json", "ppp", "ppp-mod-pppoe", "odhcp6c", "odhcpd-ipv6only",
    "luci-light", "luci-theme-bootstrap", "luci-i18n-base-zh-cn",
    "luci-theme-argon", "luci-app-argon-config", "luci-i18n-argon-config-zh-cn",
    "adguardhome", "luci-app-adguardhome", "mosdns", "luci-app-mosdns", "luci-i18n-mosdns-zh-cn", "geo2txt",
    "luci-app-turboacc", "luci-i18n-turboacc-zh-cn", "kmod-ipt-offload", "kmod-nf-flow", "kmod-tcp-bbr",
    "luci-i18n-firewall-zh-cn", "luci-app-openclash", "luci-compat",
    "wpad-basic-openssl", "kmod-mt7915e", "kmod-mt7986-firmware",
    "mt7986-wo-firmware", "kmod-leds-ws2812b", "uboot-envtools",
    "bash", "curl", "ca-bundle", "ruby", "ruby-yaml", "unzip", "ip-full",
    "ipset", "iptables", "ip6tables", "iptables-mod-tproxy",
    "iptables-mod-extra", "kmod-tun", "kmod-inet-diag",
}
FORBIDDEN = {
    "firewall4", "nftables-json", "nftables-nojson", "libnftnl", "libnftnl11", "jansson", "jansson4",
    "kmod-nft-fullcone", "kmod-nft-nat", "kmod-sched-core", "kmod-sched-bpf", "kmod-veth", "kmod-xdp-sockets-diag",
    "dnsmasq", "dnsmasq-full", "wpad-openssl", "default-settings", "autocore-arm",
    "htop", "coremark", "block-mount", "miniupnpd", "miniupnpd-iptables",
    "vsftpd", "nlbwmon", "vlmcsd", "luci", "mihomo", "3proxy", "v2ray-geoip",
    "kmod-fast-classifier", "kmod-shortcut-fe-cm",
}


def check_packages(packages):
    missing = REQUIRED - packages
    unwanted = packages & FORBIDDEN
    unwanted |= {p for p in packages if p.startswith("ddns-scripts")}
    unwanted |= {p for p in packages if p.startswith("luci-app-")
                 and p not in {"luci-app-firewall", "luci-app-openclash", "luci-app-oui", "luci-app-argon-config", "luci-app-adguardhome", "luci-app-turboacc", "luci-app-mosdns"}}
    unwanted |= {p for p in packages if re.match(
        r"^(?:shadowsocks|shadowsocksr|xray|v2ray|sing-box|trojan|naiveproxy|hysteria)(?:-|$)", p)}
    if missing or unwanted:
        raise ValueError(f"missing={sorted(missing)}, unwanted={sorted(unwanted)}")
    print(f"Package allowlist/dependencies: PASS ({len(packages)} packages)")


def check_config(tree):
    config = (tree / ".config").read_text()
    packages = set(re.findall(r"^CONFIG_PACKAGE_(.+)=y$", config, re.M))
    known = set(re.findall(r"^Package: (.+)$", (tree / "tmp/.packageinfo").read_text(), re.M))
    packages &= known
    check_packages(packages)
    lock = json.loads((tree / ".ax6000-build-lock.json").read_text())
    if int(lock["argon"]["version"].split(".", 1)[0]) >= 3:
        assert "ucode-mod-math" in packages, "Argon 3 palette requires the ucode math module"
    if tuple(map(int, lock["argon"]["version"].split("."))) >= (3, 1, 0):
        assert {"flock", "coreutils", "coreutils-timeout"} <= packages, "Argon updater runtime dependencies missing"
    devices = re.findall(r"^CONFIG_TARGET_mediatek_filogic_DEVICE_(.+)=y$", config, re.M)
    assert devices == [PROFILE], devices
    assert "CONFIG_TESTING_KERNEL=y" not in config
    assert "CONFIG_TARGET_ROOTFS_INITRAMFS=y" not in config
    assert "CONFIG_TARGET_ROOTFS_SQUASHFS=y" in config
    assert "CONFIG_IPV6=y" in config
    assert "CONFIG_CLEAN_IPKG=y" not in config, "opkg installed-package metadata must be retained"
    assert "CONFIG_PACKAGE_TURBOACC_INCLUDE_FLOW_OFFLOADING=y" in config
    assert "CONFIG_PACKAGE_TURBOACC_INCLUDE_BBR_CCA=y" in config
    print("Single AX6000 profile, SquashFS, IPv6, stable kernel: PASS")


def check_core(data):
    assert data[:6] == b"\x7fELF\x02\x01", "Not a little-endian 64-bit ELF"
    assert struct.unpack_from("<H", data, 18)[0] == 183, "Not AArch64"
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, phnum = struct.unpack_from("<HH", data, 54)
    assert all(struct.unpack_from("<I", data, phoff + i * phsize)[0] != 3
               for i in range(phnum)), "Dynamic ELF interpreter would require extra libc"
    print("Mihomo core: static AArch64 ELF, SHA256=" + hashlib.sha256(data).hexdigest())


def check_image(tree):
    check_config(tree)
    lock = json.loads((tree / ".ax6000-build-lock.json").read_text())
    core_archive = tree.parent.parent / ("mihomo-linux-arm64-v" + lock["mihomo"]["version"] + ".gz")
    assert hashlib.sha256(core_archive.read_bytes()).hexdigest() == lock["mihomo"]["sha256"]
    print("Mihomo official release archive SHA256: PASS")
    directory = tree / "bin/targets/mediatek/filogic"
    profiles = json.loads((directory / "profiles.json").read_text())
    assert profiles["target"] == "mediatek/filogic"
    assert set(profiles["profiles"]) == {PROFILE}, profiles["profiles"].keys()
    profile = profiles["profiles"][PROFILE]
    assert BOARD in profile["supported_devices"]
    images = [i for i in profile["images"] if i["type"] == "sysupgrade"]
    assert len(images) == 1
    firmware = directory / images[0]["name"]
    sha = hashlib.sha256(firmware.read_bytes()).hexdigest()
    assert sha == images[0]["sha256"]
    assert firmware.stat().st_size < 0x6e00000, "Exceeds the 110 MiB UBI partition"
    fwtool = tree / "staging_dir/host/bin/fwtool"
    metadata = json.loads(subprocess.check_output([str(fwtool), "-i", "-", str(firmware)]))
    assert BOARD in metadata["supported_devices"], metadata
    manifests = list(directory.glob("*.manifest"))
    assert len(manifests) == 1, manifests
    manifest = dict(line.split(" - ", 1) for line in manifests[0].read_text().splitlines())
    check_packages(set(manifest))
    assert manifest["kernel"].startswith(lock["kernel"] + "-"), manifest["kernel"]
    assert manifest["luci-app-openclash"] == lock["openclash"]
    assert manifest["luci-theme-argon"].startswith(lock["argon"]["version"] + "-")
    assert manifest["adguardhome"].startswith(lock["adguardhome"]["version"])
    assert manifest["luci-app-adguardhome"].startswith(lock["luci_adguardhome"]["version"] + "-"), manifest["luci-app-adguardhome"]
    ui_archive = tree.parent.parent / ("luci-app-adguardhome-" + lock["luci_adguardhome"]["revision"][:8] + ".tar.gz")
    assert hashlib.sha256(ui_archive.read_bytes()).hexdigest() == lock["luci_adguardhome"]["sha256"]
    for filename, key in [(f"adguardhome-{lock['adguardhome']['version']}.tar.gz", "source_sha256"),
                          (f"adguardhome_frontend-{lock['adguardhome']['version']}.tar.gz", "frontend_sha256")]:
        assert hashlib.sha256((tree / "dl" / filename).read_bytes()).hexdigest() == lock["adguardhome"][key]
    print("AdGuardHome pinned source/frontend SHA256 and installed version: PASS")
    indexes = list((tree / "bin/packages").glob("*/*/Packages"))
    indexes.append(directory / "packages/Packages")
    repository_packages = set()
    usign = tree / "staging_dir/host/bin/usign"
    for index in indexes:
        data = index.read_bytes()
        assert gzip.decompress(index.with_suffix(".gz").read_bytes()) == data
        subprocess.check_output([str(usign), "-V", "-p", str(tree / "key-build.pub"),
                                 "-m", str(index), "-x", str(index.with_suffix(".sig"))])
        for record in data.decode().strip().split("\n\n"):
            fields = dict(re.findall(r"^([A-Za-z0-9-]+): (.*)$", record, re.M))
            if not fields:
                continue
            repository_packages.add(fields["Package"])
            ipk = index.parent / fields["Filename"]
            assert ipk.stat().st_size == int(fields["Size"]), ipk
            assert hashlib.sha256(ipk.read_bytes()).hexdigest() == fields["SHA256sum"]
            if fields["Package"].startswith("kmod-"):
                assert f"kernel (={manifest['kernel']})" in fields["Depends"], fields
    # The repository deliberately excludes kernel/libc from downloadable indexes.
    assert set(manifest) - {"kernel", "libc"} <= repository_packages, set(manifest) - repository_packages
    print(f"Matching opkg indexes, signatures, IPK hashes and kernel ABI: PASS ({len(repository_packages)} packages)")
    unsquashfs = tree / "staging_dir/host/bin/unsquashfs4"
    with tarfile.open(firmware) as archive, tempfile.TemporaryDirectory(prefix="ax6000-qa-") as tmp:
        members = archive.getmembers()
        assert {m.name.rsplit("/", 1)[-1] for m in members if m.isfile()} == {"CONTROL", "kernel", "root"}, "Unexpected sysupgrade payload"
        roots = [m for m in members if m.name.endswith("/root")]
        kernels = [m for m in members if m.name.endswith("/kernel")]
        assert len(roots) == len(kernels) == 1, [m.name for m in members]
        assert archive.extractfile(kernels[0]).read(4) == b"\xd0\x0d\xfe\xed", "Missing FIT kernel"
        peb_size, leb_size = 128 * 1024, 124 * 1024
        payload_pebs = sum((m.size + leb_size - 1) // leb_size for m in [roots[0], kernels[0]])
        raw_headroom = 0x6e00000 - payload_pebs * peb_size
        assert raw_headroom > 0
        print(f"UBI 110 MiB: kernel={kernels[0].size} bytes, SquashFS={roots[0].size} bytes")
        print(f"Remaining raw eraseblock space={raw_headroom / 1024**2:.2f} MiB "
              "before UBI/UBIFS metadata and bad-block reserve; actual free space requires df -h /overlay")
        root = Path(tmp) / "root.squashfs"
        root.write_bytes(archive.extractfile(roots[0]).read())

        def cat(path):
            return subprocess.check_output([str(unsquashfs), "-cat", str(root), path])

        listing = subprocess.check_output([str(unsquashfs), "-ls", str(root)], text=True)
        image_paths = [line.removeprefix("squashfs-root/") for line in listing.splitlines()
                       if line.startswith("squashfs-root/")]
        assert "etc/openclash/core/clash_meta" in image_paths, "Unexpected SquashFS listing format"
        orphaned = [path for path in image_paths if Path(path).name in {
            "nft", "nft_fullcone.ko", "nft_chain_nat.ko", "veth.ko", "xdp_diag.ko", "sch_bpf.ko", "cls_bpf.ko"}
            or Path(path).name.startswith(("libnftnl.so", "libjansson.so"))]
        assert not orphaned, orphaned
        print("No unselected nftables/BPF/virtual-interface files left in SquashFS: PASS")

        key_id = subprocess.check_output(
            [str(usign), "-F", "-p", str(tree / "key-build.pub")], text=True).strip()
        assert cat(f"etc/opkg/keys/{key_id}") == (tree / "key-build.pub").read_bytes()
        core = cat("etc/openclash/core/clash_meta")
        check_core(core)
        assert hashlib.sha256(core).hexdigest() == lock["mihomo"]["elf_sha256"]
        assert core == (tree / "files/etc/openclash/core/clash_meta").read_bytes()
        mode = subprocess.check_output(
            [str(unsquashfs), "-ll", str(root), "etc/openclash/core/clash_meta"], text=True)
        assert "-rwxr-xr-x" in mode, mode
        defaults = cat("etc/uci-defaults/99-ax6000-minimal").decode()
        assert "Asia/Shanghai" in defaults
        assert 'enable_radio() { uci -q set "wireless.$1.disabled=0"; }' in defaults
        assert "config_foreach enable_radio wifi-device" in defaults
        assert "disabled=1" not in defaults
        wireless_generator = cat("lib/wifi/mac80211.sh").decode()
        assert "set wireless.${section}.disabled='0'" in wireless_generator
        assert "set wireless.${iface}.disabled='0'" in wireless_generator
        print("Both Wi-Fi radios enabled by default; generated AP interfaces enabled: PASS")
        assert "luci.main.lang='zh_cn'" in defaults
        assert "luci.main.mediaurlbase='/luci-static/argon'" in defaults
        for path in ["www/luci-static/argon/css/cascade.css",
                     "www/luci-static/resources/view/argon-config.js",
                     "usr/share/ucode/luci/template/themes/argon/head_meta.ut",
                     "usr/lib/lua/luci/i18n/base.zh-cn.lmo",
                     "usr/lib/lua/luci/i18n/argon-config.zh-cn.lmo"]:
            assert len(cat(path)) > 0, path
        if int(lock["argon"]["version"].split(".", 1)[0]) >= 3:
            assert "ucode-mod-math" in manifest
            if tuple(map(int, lock["argon"]["version"].split("."))) >= (3, 1, 0):
                assert {"flock", "coreutils", "coreutils-timeout"} <= set(manifest)
                assert cat("usr/libexec/rpcd/luci.argon_update").strip()
                assert json.loads(cat("usr/share/argon/update-sources.json"))
            assert manifest["luci-app-argon-config"].startswith(lock["argon"]["version"] + "-")
            assert manifest["luci-i18n-argon-config-zh-cn"].startswith("v" + lock["argon"]["version"])
            argon_archive = tree.parent.parent / ("argon-v" + lock["argon"]["version"] + ".tar.gz")
            assert hashlib.sha256(argon_archive.read_bytes()).hexdigest() == lock["argon"]["sha256"]
            with tarfile.open(argon_archive) as source, tempfile.TemporaryDirectory(prefix="ax6000-argon-qa-") as argon_tmp:
                prefix = "luci-theme-argon-" + lock["argon"]["version"] + "/root/"
                source.extractall(argon_tmp, members=[member for member in source.getmembers()
                                                     if member.name.startswith(prefix)], filter="data")
                expected = Path(argon_tmp) / prefix.removesuffix("root/")
                if lock["argon"].get("source_patch_sha256"):
                    patch = tree / ".ax6000-source-patches/argon.patch"
                    assert hashlib.sha256(patch.read_bytes()).hexdigest() == lock["argon"]["source_patch_sha256"]
                    subprocess.run([shutil.which("gpatch") or "patch", "-p1", "--batch", "--forward", "--no-backup-if-mismatch"],
                                   input=patch.read_bytes(), cwd=expected, check=True, stdout=subprocess.DEVNULL)
                for path in (expected / "root").rglob("*"):
                    if path.is_file():
                        assert cat(str(path.relative_to(expected / "root"))) == path.read_bytes(), path
            assert cat("usr/share/argon/config-integrated").strip()
            assert cat("lib/upgrade/keep.d/luci-argon-branding").strip()
            print("Argon integrated settings, compatibility package, math runtime and pinned root files: PASS")
        print(f"Default Argon {lock['argon']['version']} theme and Simplified Chinese UI/settings catalogs: PASS")
        assert "openclash.config.enable='0'" in defaults
        assert "openclash.config.china_ip_route='1'" in defaults
        for setting in ["openclash.config.enable_tcp_concurrent='1'",
                        "openclash.config.enable_unified_delay='1'",
                        "openclash.config.log_level='warning'",
                        "openclash.config.geodata_loader='memconservative'",
                        "openclash.config.enable_meta_sniffer='1'",
                        "openclash.config.enable_meta_sniffer_pure_ip='0'"]:
            assert setting in defaults, setting
        assert "openclash.config.default_dashboard='zashboard'" in defaults
        assert "openclash.config.geosite_auto_update='0'" in defaults
        dashboard_listing = subprocess.check_output(
            [str(unsquashfs), "-ll", str(root), "usr/share/openclash/ui"], text=True)
        assert "/metacubexd" not in dashboard_listing
        assert len(cat("usr/share/openclash/ui/zashboard/index.html")) > 0
        dashboard = lock["assets"]["zashboard"]
        dashboard_archive = tree.parent.parent / dashboard["filename"]
        assert hashlib.sha256(dashboard_archive.read_bytes()).hexdigest() == dashboard["sha256"]
        assert json.loads(cat("usr/share/openclash/ui/zashboard/ax6000-source.json")) == dashboard
        with zipfile.ZipFile(dashboard_archive) as archive:
            index = [n for n in archive.namelist() if Path(n).name == "index.html"]
            assert len(index) == 1
            prefix = str(Path(index[0]).parent)
            for info in archive.infolist():
                if info.is_dir():
                    continue
                relative = str(Path(info.filename).relative_to(prefix))
                assert cat("usr/share/openclash/ui/zashboard/" + relative) == archive.read(info)
        print(f"Zashboard {dashboard['version']} official archive and every installed asset: PASS")
        assert b"option default_dashboard 'zashboard'" in cat("etc/config/openclash")
        print("Bundled MetaCubeXD removed; Zashboard present and selected by default: PASS")
        assert "network.globals.packet_steering='1'" in defaults
        network_defaults = cat("bin/config_generate").decode()
        assert 'lan) ipad=${ipaddr:-"192.168.199.1"}' in network_defaults
        assert '192.168.1.1' not in network_defaults
        print("Default LAN IPv4: 192.168.199.1/24: PASS")
        agh = cat("usr/bin/AdGuardHome")
        assert agh[:6] == b"\x7fELF\x02\x01"
        assert struct.unpack_from("<H", agh, 18)[0] == 183
        for path in ["usr/bin/AdGuardHome", "etc/openclash/custom/openclash_custom_overwrite.sh",
                     "usr/share/openclash/adguardhome_dns.rb", "usr/share/adguardhome/ax6000-prepare.sh",
                     "usr/share/adguardhome/ax6000-wait-dns.lua",
                     "usr/share/openclash/ax6000-core-check.sh", "usr/share/openclash/ax6000-core-version.sh",
                     "usr/share/openclash/ax6000-dns-overwrite.rb",
                     "usr/share/turboacc/ax6000-wed.sh"]:
            mode = subprocess.check_output([str(unsquashfs), "-ll", str(root), path], text=True)
            assert "-rwxr-xr-x" in mode, mode
        for path in ["usr/lib/lua/luci/controller/AdGuardHome.lua",
                     "usr/lib/lua/luci/model/cbi/AdGuardHome/base.lua",
                     "usr/lib/lua/luci/model/cbi/AdGuardHome/manual.lua",
                     "usr/lib/lua/luci/view/AdGuardHome/AdGuardHome_status.htm",
                     "usr/lib/lua/luci/i18n/AdGuardHome.zh-cn.lmo",
                     "www/luci-static/resources/codemirror/lib/codemirror.js"]:
            assert len(cat(path)) > 0, path
        assert json.loads(cat("usr/share/AdGuardHome/ax6000-source.json")) == lock["luci_adguardhome"]
        ui_listing = subprocess.check_output([str(unsquashfs), "-ll", str(root),
                                             "www/luci-static/resources/view", "usr/share/luci/menu.d"], text=True)
        assert "/adguardhome/config.js" not in ui_listing
        assert "/luci-app-adguardhome.json" not in ui_listing
        base_ui = cat("usr/lib/lua/luci/model/cbi/AdGuardHome/base.lua").decode()
        assert "window.location.hostname+':" in base_ui and '"httpbind"' in base_ui
        assert "2>nul" not in base_ui
        controller = cat("usr/lib/lua/luci/controller/AdGuardHome.lua")
        assert b'luci.sys.call("pidof "' in controller
        ui_config = cat("etc/config/AdGuardHome")
        for setting in ["option enabled '1'", "option httpport '3000'", "option httpbind '0.0.0.0'",
                        "option binpath '/usr/bin/AdGuardHome'", "option configpath '/etc/adguardhome/adguardhome.yaml'",
                        "option workdir '/etc/adguardhome/runtime'"]:
            assert setting.encode() in ui_config, setting
        print("Pinned rufengsuixing LuCI plugin, Chinese catalog, Web link and current-schema settings: PASS")
        agh_yaml = cat("etc/adguardhome/adguardhome.yaml")
        assert agh_yaml == (tree / "files/etc/adguardhome/adguardhome.yaml").read_bytes()
        assert "adguardhome:x:853:853:" in cat("etc/passwd").decode()
        capabilities = json.loads(cat("etc/capabilities/adguardhome.json"))
        for scope in ["bounding", "effective", "ambient", "permitted", "inheritable"]:
            assert {"CAP_NET_BIND_SERVICE", "CAP_NET_RAW"} <= set(capabilities[scope])
        assert b"/etc/adguardhome/" in cat("etc/sysupgrade.conf")
        for setting in ["http:\n  address: 0.0.0.0:3000", "port: 53",
                        "interface_name: br-lan", "range_start: 192.168.199.100",
                        "range_end: 192.168.199.249", "cache_enabled: false",
                        "cache_size: 4194304", "cache_optimistic: false",
                        "protection_enabled: true"]:
            assert setting.encode() in agh_yaml, setting
        for setting in ["openclash.config.enable_redirect_dns='0'",
                        "openclash.config.adguardhome_dns='1'",
                        "openclash.config.en_mode='fake-ip'",
                        "uci -q delete dhcp.@dnsmasq[0]", "dhcp.lan.dhcpv4='disabled'",
                        "dhcp.lan.dhcpv6='disabled'", "dhcp.lan.ra='disabled'",
                        "AdGuardHome.AdGuardHome.workdir='/etc/adguardhome/runtime'",
                        "AdGuardHome.AdGuardHome.httpbind='0.0.0.0'",
                        "AdGuardHome.AdGuardHome.httpport='3000'",
                        "/etc/init.d/AdGuardHome enable"]:
            assert setting in defaults, setting
        oc_init = cat("etc/init.d/openclash").decode()
        oc_converter = cat("usr/share/openclash/yml_change.sh").decode()
        assert "['DIRECT', 'utun'" in oc_converter
        assert "s.match?(non_domain_reg) || s.match?(proxied_server_reg)" in oc_converter
        assert 'procd_set_param command /usr/share/openclash/ax6000-core-run.sh' in oc_init
        core_run = cat("usr/share/openclash/ax6000-core-run.sh")
        assert b'wait "$core_pid"' in core_run and b'/tmp/openclash-last-exit.log' in core_run
        assert b'tail -c 262144' in core_run
        assert 'uci_get_config "default_dashboard" || echo "zashboard"' in oc_converter
        for option in ["enable_tcp_concurrent", "enable_unified_delay", "log_level", "geodata_loader"]:
            assert f'uci_get_config "{option}"' in oc_init, option
        for setting in ["Value['tcp-concurrent'] = true if tcp_concurrent",
                        "Value['unified-delay'] = true if unified_delay",
                        "Value['log-level'] = log_level if log_level != '0'",
                        "Value['geodata-loader'] = geodata_loader if geodata_loader != '0'"]:
            assert setting in oc_converter, setting
        assert '$(uci_get_config "adguardhome_dns")' in oc_init
        assert "ruby /usr/share/openclash/adguardhome_dns.rb proxy" in oc_init
        assert "ruby /usr/share/openclash/adguardhome_dns.rb direct" in oc_init
        assert "|| enable_redirect_dns=0" in oc_init
        assert 'exec 885>/tmp/lock/openclash-core-operation.lock' in oc_init
        assert 'procd_append_param env GOGC=50 GOMEMLIMIT=134217728' in oc_init
        assert '[ "${AX6000_CORE_CHECK:-0}" = 1 ] || rm -rf /tmp/openclash_jobs' in oc_init
        assert 'echo "$!" > "$AX6000_CORE_START_PID_FILE"' in oc_init
        updater = cat("usr/share/openclash/openclash.sh")
        assert b'/usr/share/openclash/ax6000-core-check.sh' in updater
        assert b'rm -f /tmp/openclash.change' in updater
        assert b'"$test_status" -ne 0' in updater
        assert b'ax6000-subscription-check.rb "$CFG_FILE" "$CONFIG_FILE"' in updater
        assert b'if [ "$test_status" -eq 2 ]; then' in updater
        assert updater.count(b'if ! config_integrity_check; then') == 2
        subscription_check = cat("usr/share/openclash/ax6000-subscription-check.rb")
        assert b'node count collapsed' in subscription_check
        assert b'populated automatic groups lost their nodes' in subscription_check
        core_check = cat("usr/share/openclash/ax6000-core-check.sh")
        assert b'timeout 90 "$core" -t' in core_check
        assert b'AX6000_CORE_CHECK=1 AX6000_CORE_START_PID_FILE="$start_pid_file" "$service" start' in core_check
        assert b'while kill -0 "$start_pid"' in core_check
        assert b'AX6000_CORE_CHECK=1 "$service" stop' in core_check
        version_helper = cat("usr/share/openclash/ax6000-core-version.sh")
        assert b'/version' in version_helper and b'if cached; then exit; fi' in version_helper
        assert b'if ! flock -n 887' in version_helper
        oc_controller = cat("usr/lib/lua/luci/controller/openclash.lua")
        oc_debug = cat("usr/share/openclash/openclash_debug.sh")
        assert b'ax6000-core-version.sh' in oc_controller and b'ax6000-core-version.sh' in oc_debug
        core_updater = cat("usr/share/openclash/openclash_core.sh")
        assert b'CORE_CV=$(/usr/share/openclash/ax6000-core-version.sh' in core_updater
        assert b'ax6000-core-check.sh --version "$TMP_FILE"' in core_updater
        agh_init = cat("etc/init.d/AdGuardHome")
        assert b"ax6000-prepare.sh" in agh_init
        assert b"ax6000-ui-prepare.rb" in agh_init
        assert b"procd_set_param user adguardhome" in agh_init
        assert b"procd_add_jail adguardhome log procfs" in agh_init
        assert b"procd_append_param env GOGC=50 GOMEMLIMIT=134217728" in agh_init
        assert b"--no-check-update" in agh_init
        assert b'exec /etc/init.d/AdGuardHome "$@"' in cat("etc/init.d/adguardhome")
        for path in ["usr/share/openclash/adguardhome_dns.rb", "usr/share/adguardhome/ax6000-prepare.sh",
                     "usr/share/adguardhome/ax6000-wait-dns.lua",
                     "usr/share/openclash/ax6000-core-check.sh", "usr/share/openclash/ax6000-core-version.sh",
                     "usr/share/openclash/ax6000-subscription-check.rb",
                     "usr/share/openclash/ax6000-dns-overwrite.rb",
                     "etc/adguardhome/resolv.conf"]:
            assert cat(path) == (tree / "files" / path).read_bytes()
        assert 'lua' in manifest and 'luci-lib-nixio' in manifest
        assert len(cat("usr/lib/lua/nixio.so")) > 0
        agh_prepare = cat("usr/share/adguardhome/ax6000-prepare.sh")
        assert b"ax6000-wait-dns.lua 127.0.0.1 5335 15" in agh_prepare
        assert b"continuing to keep DHCP and Web available" in agh_prepare
        timeout_listing = subprocess.check_output(
            [str(unsquashfs), "-ll", str(root), "usr/bin/timeout"], text=True)
        assert "timeout ->" in timeout_listing, timeout_listing
        print("AdGuard startup waits for local MosDNS UDP/TCP with bounded timeout: PASS")
        assert b"nameserver 127.0.0.1" in cat("etc/adguardhome/resolv.conf")
        resolver_link = subprocess.check_output([str(unsquashfs), "-ll", str(root), "etc/resolv.conf"], text=True)
        assert "-> adguardhome/resolv.conf" in resolver_link
        listing = subprocess.check_output([str(unsquashfs), "-ll", str(root), "usr/sbin"], text=True)
        assert "squashfs-root/usr/sbin/dnsmasq" not in listing
        assert b"ra_slaac_only: false" in agh_yaml and b"ra_allow_slaac: false" in agh_yaml
        assert b"upstream_dns:\n    - 127.0.0.1:5335" in agh_yaml
        assert b"range_start: ''" in agh_yaml and b"aaaa_disabled: true" in agh_yaml
        for path in ["etc/sysctl.d/99-ax6000-ipv4-only.conf",
                     "etc/hotplug.d/iface/99-ax6000-ipv4-only",
                     "etc/uci-defaults/zzz-ax6000-ipv4-only"]:
            assert cat(path) == (tree / "files" / path).read_bytes()
        print("AdGuard DHCPv4, IPv6 disabled, persistent leases/RAM caches, no dnsmasq executable: PASS")
        hook = cat("etc/openclash/custom/openclash_custom_overwrite.sh")
        assert hook == (tree / "files/etc/openclash/custom/openclash_custom_overwrite.sh").read_bytes()
        assert b'exec ruby -ryaml -E UTF-8 "$helper" "$1"' in hook
        assert b"find-process-mode" not in hook and b"group.merge!" not in hook
        for filename in ["AX6000_Router.ini", "AX6000_Base.yaml"]:
            profile_path = "usr/share/openclash/profiles/" + filename
            assert cat(profile_path) == (tree / "files" / profile_path).read_bytes()
        router_ini = cat("usr/share/openclash/profiles/AX6000_Router.ini")
        router_base = cat("usr/share/openclash/profiles/AX6000_Base.yaml")
        assert b"ruleset=REJECT,[]DOMAIN,local.adguard.org" in router_ini
        assert b"[]DOMAIN-SUFFIX,adguard.org" not in router_ini
        assert b"local.adguard.com" not in router_ini
        assert b"injections.adguard.org" not in router_ini
        assert b"clash_rule_base=" in router_ini and b"AX6000_Base.yaml" in router_ini
        assert b"`600,5,100" in router_ini
        assert b"find-process-mode: 'off'" in router_base and b"geo-auto-update: false" in router_base
        assert 'https://1.1.1.1/dns-query#🚀 节点选择'.encode() in router_base
        assert 'https://8.8.8.8/dns-query#🚀 节点选择'.encode() in router_base
        assert b"geosite:cn,private" in router_base and b"respect-rules: false" in router_base
        dns_switch = cat("usr/share/openclash/adguardhome_dns.rb")
        assert b"'cache_enabled' => false" in dns_switch
        assert b"'cache_clear', :empty_post" in dns_switch
        assert b"'cache_size' => current.fetch('cache_size')" in dns_switch
        assert b"'fallback_dns' => []" in dns_switch
        assert b"'upstream_mode' => 'load_balance'" in dns_switch
        dns_overwrite = cat("usr/share/openclash/ax6000-dns-overwrite.rb")
        assert b"dns['listen'] = '127.0.0.1:7874'" in dns_overwrite
        assert b"config['tun']['dns-hijack'] = []" in dns_overwrite
        assert b"config['find-process-mode'] = 'off' if config['find-process-mode'] == false" in dns_overwrite
        for setting in [b"nameserver-policy", b"prefer-h3", b"geo-auto-update"]:
            assert setting not in dns_overwrite
        for setting in [b'https://223.5.5.5/dns-query#DIRECT&h3=true',
                        b'https://223.6.6.6/dns-query#DIRECT&h3=true',
                        b'119.29.29.29#DIRECT', b'prefer-h3: true']:
            assert setting in router_base
        assert len(cat("etc/openclash/china_ip_route.ipset")) > 1000
        links = subprocess.check_output([str(unsquashfs), "-ll", str(root), "etc/rc.d"], text=True)
        assert "S95AdGuardHome" in links, "AdGuard Home is not enabled at boot"
        assert "S19adguardhome" not in links, "A second AdGuard Home service is enabled"
        print("AdGuard Web listens on 0.0.0.0:3000 and a single service owns startup: PASS")
        print("AdGuardHome AArch64 executable, Chinese LuCI, default DNS chain and OpenClash integration: PASS")
        assert manifest['mosdns'] == '5.3.4-15', 'MosDNS stats error-classification fix is missing'
        for path in ['www/luci-static/resources/view/mosdns/basic.js',
                     'www/luci-static/resources/view/mosdns/rules.js',
                     'www/luci-static/resources/view/mosdns/statistics.js',
                     'usr/share/rpcd/ucode/luci.mosdns',
                     'etc/mosdns/config_custom.yaml', 'etc/mosdns/data/direct.txt',
                     'etc/mosdns/data/proxy.txt', 'etc/mosdns/data/cn-ip.txt']:
            assert len(cat(path)) > 0, path
        assert b"option configfile '/etc/mosdns/config_custom.yaml'" in cat('etc/config/mosdns')
        special_domains = cat('etc/mosdns/rule/whitelist.txt')
        assert special_domains == (tree / 'files/etc/mosdns/rule/whitelist.txt').read_bytes()
        for domain in (b'local.adguard.org', b'injections.adguard.org'):
            assert domain not in special_domains
            assert domain not in cat('usr/share/openclash/ax6000-dns-overwrite.rb')
        mosdns_profile = cat('etc/mosdns/config_custom.yaml')
        local_reject = b'matches: qname full:local.adguard.org\n        exec: reject 5'
        assert local_reject in mosdns_profile
        assert mosdns_profile.index(local_reject) < mosdns_profile.index(b'matches: qtype 28 64 65')
        assert b'injections.adguard.org' not in mosdns_profile
        rule_overwrite = cat('etc/openclash/custom/openclash_custom_overwrite.sh')
        assert b'local.adguard.org' not in rule_overwrite
        assert b'injections.adguard.org' not in rule_overwrite
        assert b'addr: h3://223.5.5.5/dns-query' in mosdns_profile
        assert b'addr: h3://223.6.6.6/dns-query' in mosdns_profile
        assert b'addr: 119.29.29.29' in mosdns_profile
        assert b'concurrent: 3' in mosdns_profile
        assert b'adblock_set' not in mosdns_profile and b'$blocklist' not in mosdns_profile
        assert b'matches: rcode 2\n        exec: drop_resp' in mosdns_profile
        assert b'threshold: 500' in mosdns_profile and b'threshold: 2000' in mosdns_profile
        unknown_branch = mosdns_profile.split(b'  - tag: unknown_direct_sequence\n', 1)[1].split(b'  - tag: unknown_fallback\n', 1)[0]
        assert b'- exec: $direct_sequence' in unknown_branch
        assert b'\n      - exec: $lazy_cache' not in unknown_branch
        assert b"option adblock '0'" in cat('etc/config/mosdns')
        assert b'$local_fallback' not in mosdns_profile and b'forward_dnspod' not in mosdns_profile
        assert mosdns_profile == (tree / 'files/etc/mosdns/config_custom.yaml').read_bytes()
        assert b"option ax6000_split '1'" in cat('etc/config/mosdns')
        assert b"/etc/mosdns/" in cat('etc/sysupgrade.conf')
        assert "firewall.ax6000_dns.dest_port='53'" in defaults
        assert "firewall.ax6000_dns.dest_ip='192.168.199.1'" in defaults
        firewall_hook = cat('etc/openclash/custom/openclash_custom_firewall_rules.sh')
        assert firewall_hook == (tree / 'files/etc/openclash/custom/openclash_custom_firewall_rules.sh').read_bytes()
        assert b'ax6000_proxy_ip' in firewall_hook and br'/198\.18\.0\.0\/16/' in firewall_hook
        assert b'fake-ip|fake-ip-mix|fake-ip-tun)' in firewall_hook
        assert b'for table in nat mangle' in firewall_hook
        assert b'! -d 198.18.0.0/16 -m set ! --match-set ax6000_proxy_ip dst -j RETURN' in firewall_hook
        assert b"GOMEMLIMIT=33554432" in cat('etc/init.d/mosdns')
        assert 'S75mosdns' in links
        print('MosDNS 5.3.4-15, Mihomo SERVFAIL fallback, no advertising filter, three concurrent AliDNS H3/DNSPod UDP upstreams, corrected failure statistics, stock Chinese LuCI and trimmed rules: PASS')

        for path in ["www/luci-static/resources/view/turboacc.js",
                     "usr/lib/lua/luci/i18n/turboacc.zh-cn.lmo",
                     "usr/libexec/rpcd/luci.turboacc", "etc/init.d/turboacc",
                     f"lib/modules/{lock['kernel']}/xt_FLOWOFFLOAD.ko",
                     f"lib/modules/{lock['kernel']}/nf_flow_table.ko", f"lib/modules/{lock['kernel']}/tcp_bbr.ko"]:
            assert len(cat(path)) > 0, path
        assert cat("etc/config/turboacc") == (tree / "files/etc/config/turboacc").read_bytes()
        assert b"FLOWOFFLOAD" in cat("usr/lib/libiptext.so"), "FW3 offload userspace extension is missing"
        assert b"option fastpath 'flow_offloading'" in cat("etc/config/turboacc")
        assert b"option fastpath_fo_hw '1'" in cat("etc/config/turboacc")
        assert b"option fastpath_mh_eth_hnat_wed '1'" in cat("etc/config/turboacc")
        assert b"options mt7915e wed_enable=Y" in cat("etc/modules.conf")
        assert cat("usr/share/turboacc/ax6000-wed.sh") == (tree / "files/usr/share/turboacc/ax6000-wed.sh").read_bytes()
        assert b'/usr/share/turboacc/ax6000-wed.sh "$target_value"' in cat("etc/init.d/turboacc")
        assert len(cat(f"lib/modules/{lock['kernel']}/mt7915e.ko")) > 0
        kernel_configs = list(tree.glob(f"build_dir/target-*/linux-mediatek_filogic/linux-{lock['kernel']}/.config"))
        assert len(kernel_configs) == 1
        assert "CONFIG_NET_MEDIATEK_SOC_WED=y" in kernel_configs[0].read_text()
        assert b"option tcpcca 'bbr'" in cat("etc/config/turboacc")
        assert b"net.ipv4.tcp_congestion_control=bbr" in cat("etc/sysctl.d/12-tcp-bbr.conf")
        assert "S90turboacc" in links and "/etc/init.d/turboacc enable" in defaults
        print("Turbo ACC FW3 hardware flow offload/BBR, WED boot option/control and regular packet steering: PASS")
        print("OpenClash imported configuration forces find-process-mode off: PASS")
        print("Mihomo TCP concurrency/unified delay, warning logs, memory-conservative loader and URL-test defaults: PASS")
        status = cat("usr/lib/opkg/status").decode()
        installed = set(re.findall(r"^Package: (.+)$", status, re.M))
        check_packages(installed)
        installed_versions = {}
        for record in status.strip().split("\n\n"):
            fields = dict(re.findall(r"^([A-Za-z0-9-]+): (.*)$", record, re.M))
            if "Package" in fields:
                installed_versions[fields["Package"]] = fields["Version"]
        for builtin in ["kernel", "libc"]:
            assert installed_versions[builtin] == manifest[builtin]
        assert len(cat("etc/openclash/Country.mmdb")) > 0
        for key, path in [("country_mmdb", "Country.mmdb"), ("cn_ipv4", "china_ip_route.ipset"),
                          ("cn_ipv6", "china_ip6_route.ipset")]:
            assert hashlib.sha256(cat("etc/openclash/" + path)).hexdigest() == lock["assets"][key]["sha256"]
        print("Pinned current lite Country database and CN IPv4/IPv6 routing data: PASS")
        geosite = cat("etc/openclash/GeoSite.dat")
        selected = check_geosite(geosite)
        assert geosite == (tree / "files/etc/openclash/GeoSite.dat").read_bytes()
        oc_ipks = list((tree / "bin/packages").glob("*/*/luci-app-openclash_*.ipk"))
        assert len(oc_ipks) == 1
        with tarfile.open(oc_ipks[0]) as ipk:
            with tarfile.open(fileobj=ipk.extractfile("./data.tar.gz")) as payload:
                names = payload.getnames()
                assert not any("/ui/metacubexd" in name for name in names)
                assert payload.extractfile("./etc/openclash/GeoSite.dat").read() == geosite
        print(f"Firmware/IPK trimmed GeoSite SHA256 and {len(selected)} retained categories, GEO auto-update disabled: PASS")
        assert cat("etc/shadow").splitlines()[0].startswith(b"root::"), "Unexpected preset root password"
    print(f"Firmware payload, metadata, kernel, core permissions and defaults: PASS")
    print(f"Firmware: {firmware.name}, {firmware.stat().st_size} bytes, SHA256={sha}")
    print("Fresh-image hardware boot verification: NOT RUN (image not flashed)")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"config", "core", "image"}:
        raise SystemExit("Usage: verify-redmi-ax6000.py [config|core|image] PATH")
    mode, path = sys.argv[1], Path(sys.argv[2])
    if mode == "config":
        check_config(path)
    elif mode == "core":
        check_core(path.read_bytes())
    else:
        check_image(path)
