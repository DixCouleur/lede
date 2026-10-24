#!/usr/bin/env python3
"""Exercise the shipped AdGuard config on a native same-version release.

Loopback high ports stand in for public upstreams and Mihomo. No router is contacted.
"""
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def query(name):
    labels = b"".join(bytes([len(p)]) + p.encode() for p in name.split("."))
    return struct.pack("!6H", 0x1234, 0x100, 1, 0, 0, 0) + labels + b"\0\0\1\0\1"


def address(data):
    assert data[:2] == b"\x12\x34", data.hex()
    assert struct.unpack_from("!H", data, 6)[0] == 1, data.hex()
    return socket.inet_ntoa(data[-4:])


class Backend:
    def __init__(self, port=15354, answer="1.1.1.10"):
        self.answer = answer
        self.count = 0
        self.last_reply = b""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while True:
            try:
                data, peer = self.sock.recvfrom(4096)
                self.count += 1
                if self.answer is None:
                    continue
                # Copy only the question; AdGuard sends an EDNS OPT record in
                # the additional section, which must not precede our answer.
                question_end = data.index(b"\0", 12) + 5
                reply = data[:2] + struct.pack("!5H", 0x8180, 1, 1, 0, 0) + data[12:question_end]
                reply += b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4)
                reply += socket.inet_aton(self.answer)
                self.last_reply = reply
                self.sock.sendto(reply, peer)
            except OSError:
                return


def lookup(name, tcp=False, ipv6=False):
    data = query(name)
    with socket.socket(socket.AF_INET6 if ipv6 else socket.AF_INET,
                       socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as s:
        s.settimeout(20)
        if tcp:
            s.connect(("::1" if ipv6 else "127.0.0.1", 15353))
            s.sendall(struct.pack("!H", len(data)) + data)
            length = struct.unpack("!H", s.recv(2))[0]
            reply = b""
            while len(reply) < length:
                reply += s.recv(length - len(reply))
        else:
            s.sendto(data, ("::1" if ipv6 else "127.0.0.1", 15353))
            reply = s.recv(4096)
    return address(reply)


def main(binary, mihomo_binary=None, geosite=None):
    # Ruby/YAML is also the firmware's OpenClash configuration editor.
    seed = ROOT / "configs/ax6000/files/etc/adguardhome/adguardhome.yaml"
    config = json.loads(subprocess.check_output(
        ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_file(ARGV[0]))", str(seed)]))
    config["http"]["address"] = "127.0.0.1:13000"
    config["dns"].update(bind_hosts=["0.0.0.0"], port=15353,
                         upstream_dns=["127.0.0.1:15354"], fallback_dns=["127.0.0.1:15355"],
                         local_ptr_upstreams=["127.0.0.1:15354"], upstream_timeout="1s", cache_enabled=True)
    config["dhcp"]["enabled"] = False  # Never provide DHCP on the host LAN.
    config["filters"] = []
    config["user_rules"] = ["||blocked.test^"]
    backend = Backend()
    fallback = Backend(15355, "1.1.1.30")
    mihomo = Backend(7874, "1.1.1.20")
    with tempfile.TemporaryDirectory(prefix="ax6000-dns-") as directory:
        directory = Path(directory)
        for section in ["querylog", "statistics"]:
            (directory / section).mkdir()
            config[section]["dir_path"] = str(directory / section)
        path = directory / "AdGuardHome.yaml"
        path.write_text(json.dumps(config))  # JSON is a YAML subset.
        state = directory / "upstreams.json"
        env = dict(os.environ, AX6000_AGH_STATE=str(state), AX6000_AGH_LOCK=str(directory / "switch.lock"),
                   AX6000_AGH_URL="http://127.0.0.1:13000", AX6000_LAN_IPV6="fd12:3456:789a::1/64")
        switch = ROOT / "configs/ax6000/files/usr/share/openclash/adguardhome_dns.rb"
        subprocess.run(["ruby", str(switch), "prepare", str(path)], env=env, check=True)
        prepared = json.loads(subprocess.check_output(
            ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_file(ARGV[0]))", str(path)]))
        assert prepared["dhcp"]["dhcpv6"]["range_start"] == "fd12:3456:789a:0::100"
        assert prepared["dhcp"]["dhcpv4"]["range_start"] == "192.168.199.100"
        imported = {"proxies": [{"name": "kept", "type": "direct"},
                                {"name": "hy2-kept", "type": "hysteria2", "server": "192.0.2.1",
                                 "port": 443, "password": "host-fixture", "up": "30 Mbps", "down": "200 Mbps",
                                 "max-stream-receive-window": 8388608}],
                    "proxy-groups": [
                        {"name": "manual", "type": "select", "proxies": ["kept", "hy2-kept"]},
                        {"name": "automatic", "type": "url-test", "proxies": ["kept", "hy2-kept"],
                         "url": "https://www.gstatic.com/generate_204", "interval": 60,
                         "lazy": False, "tolerance": 0, "timeout": 5000},
                        {"name": "failover", "type": "fallback", "proxies": ["hy2-kept", "kept"],
                         "url": "https://www.gstatic.com/generate_204", "interval": 300},
                        {"name": "balanced", "type": "load-balance", "proxies": ["kept", "hy2-kept"],
                         "url": "https://www.gstatic.com/generate_204", "interval": 300, "strategy": "round-robin"}],
                    "rules": ["DOMAIN-SUFFIX,local.adguard.org,DIRECT",
                              "DOMAIN-SUFFIX,local.adguard.com,DIRECT",
                              "DOMAIN-SUFFIX,injections.adguard.org,DIRECT",
                              "DOMAIN-SUFFIX,adguard.org,manual", "MATCH,DIRECT"],
                    "find-process-mode": "always",
                    "geo-auto-update": True,
                    "dns": {"enable": True, "nameserver": ["192.168.199.1"],
                            "nameserver-policy": {"+.test": ["127.0.0.1:5353"]},
                            "enhanced-mode": "fake-ip"}}
        clash_path = directory / "clash.yaml"
        clash_path.write_text(json.dumps(imported))
        hook = ROOT / "configs/ax6000/files/etc/openclash/custom/openclash_custom_overwrite.sh"
        hook_env = dict(os.environ, AX6000_DNS_HELPER=str(ROOT / "configs/ax6000/files/usr/share/openclash/ax6000-dns-overwrite.rb"))
        subprocess.run(["sh", str(hook), str(clash_path)], env=hook_env, check=True)
        changed = json.loads(subprocess.check_output(
            ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_file(ARGV[0]))", str(clash_path)]))
        assert changed["proxies"] == imported["proxies"]
        expected = json.loads(json.dumps(imported))
        expected["dns"]["listen"] = "127.0.0.1:7874"
        assert changed == expected
        first_render = clash_path.read_bytes()
        subprocess.run(["sh", str(hook), str(clash_path)], env=hook_env, check=True)
        assert clash_path.read_bytes() == first_render
        print("PASS: local adapter preserves subscribed DNS, rules, performance and node fields; only DNS listen changes; rendering is idempotent.")
        if mihomo_binary:
            version = subprocess.check_output([mihomo_binary, "-v"], text=True)
            expected_version = json.loads((ROOT / 'configs/redmi-ax6000-build.lock.json').read_text())['mihomo']['version']
            assert expected_version in version, version
            defaults = dict(re.findall(r"uci -q set openclash\.config\.([a-z_]+)='([^']+)'",
                                       (ROOT / "scripts/build-redmi-ax6000.sh").read_text()))
            effective = dict(changed)
            effective.update({"tcp-concurrent": defaults["enable_tcp_concurrent"] == "1",
                              "unified-delay": defaults["enable_unified_delay"] == "1",
                              "log-level": defaults["log_level"],
                              "geodata-loader": defaults["geodata_loader"]})
            native_config = directory / "mihomo-effective.yaml"
            import shutil
            shutil.copyfile(geosite or ROOT / "artifacts/ax6000/image-files/etc/openclash/GeoSite.dat", directory / "GeoSite.dat")
            native_config.write_text(json.dumps(effective, ensure_ascii=False))
            subprocess.run([mihomo_binary, "-t", "-d", str(directory), "-f", str(native_config)], check=True)
            print(f"PASS: official native Mihomo {expected_version} accepts the hook result with shipped LuCI TCP/unified-delay/log/GEO defaults.")
        command = [binary, "-c", str(path), "-w", str(directory), "--no-check-update"]
        subprocess.run(command + ["--check-config"], check=True)
        with (directory / "run.log").open("w+") as log:
            proc = subprocess.Popen(command, stdout=log, stderr=log)
            try:
                startup_error = None
                for _ in range(100):
                    if proc.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    try:
                        if lookup("ready.test") == backend.answer:
                            break
                    except (OSError, AssertionError) as error:
                        startup_error = error
                        time.sleep(0.1)
                else:
                    log.seek(0)
                    raise RuntimeError(f"AdGuard Home DNS not ready: {startup_error!r}; "
                                       f"upstream={backend.count}, fallback={fallback.count}, "
                                       f"last_reply={backend.last_reply.hex()}\n" + log.read())
                assert lookup("direct.test") == "1.1.1.10"
                assert lookup("tcp.test", tcp=True) == "1.1.1.10"
                assert lookup("ipv6.test", ipv6=True) == "1.1.1.10"
                before = backend.count
                assert lookup("switch-cache.test") == backend.answer
                assert lookup("switch-cache.test") == backend.answer
                assert backend.count == before + 1, "Direct DNS cache did not prevent an upstream query"
                before = backend.count
                assert lookup("blocked.test") == "0.0.0.0"
                assert backend.count == before, "Blocked query reached upstream"
                subprocess.run(["ruby", str(switch), "proxy"], env=env, check=True)
                subprocess.run(["ruby", str(switch), "proxy"], env=env, check=True)
                assert json.loads(state.read_text())["upstream_dns"] == ["127.0.0.1:15354"]
                assert json.loads(state.read_text())["cache_enabled"] is True
                assert json.loads(state.read_text())["fallback_dns"] == ["127.0.0.1:15355"]
                assert proc.poll() is None
                assert lookup("switch-cache.test") == "1.1.1.20", "Direct cache survived proxy switch"
                assert lookup("proxy.test") == "1.1.1.20"
                assert lookup("blocked.test") == "0.0.0.0"
                proxy_info = json.load(urllib.request.urlopen("http://127.0.0.1:13000/control/dns_info"))
                assert proxy_info["fallback_dns"] == []
                subprocess.run(["ruby", str(switch), "direct"], env=env, check=True)
                assert not state.exists()
                assert lookup("switch-cache.test") == "1.1.1.10", "Proxy cache survived direct switch"
                assert lookup("restored.test") == "1.1.1.10"
                backend.answer = None
                assert lookup("fallback.test") == "1.1.1.30"
                assert lookup("blocked.test") == "0.0.0.0"
                status = json.load(urllib.request.urlopen("http://127.0.0.1:13000/control/status"))
                assert status["version"] == "v0.107.79" and status["protection_enabled"]
                assert status["language"] == "zh-cn"
                dns_info = json.load(urllib.request.urlopen("http://127.0.0.1:13000/control/dns_info"))
                assert dns_info["cache_enabled"] is True
                assert dns_info["cache_size"] == 4194304
                assert dns_info["upstream_dns"] == ["127.0.0.1:15354"]
                subprocess.run(["ruby", str(switch), "proxy"], env=env, check=True)
                proc.terminate()
                proc.wait(timeout=10)
                subprocess.run(["ruby", str(switch), "prepare", str(path)], env=env, check=True)
                restored = json.loads(subprocess.check_output(
                    ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_file(ARGV[0]))", str(path)]))
                assert restored["dns"]["upstream_dns"] == ["127.0.0.1:15354"]
                assert restored["dns"]["cache_enabled"] is True
                assert restored["dns"]["cache_size"] == 4194304
                assert not state.exists()
                subprocess.run(command + ["--check-config"], check=True)
                print("PASS: interrupted proxy session recovers original DNS during next boot preparation.")
                print("PASS: official AdGuardHome 0.107.79 loads shipped config; IPv4/IPv6 UDP and TCP DNS;")
                print("PASS: filtering stays active across backend changes; blocked queries never reach upstream;")
                print("PASS: direct cache hits, proxy cache disabled, API switch clears stale answers and restores cache;")
                print("PASS: real upstream API switches/restores idempotently without restarting AdGuard; Chinese API responds.")
                print("PASS: backend failure uses fallback DNS and keeps ad blocking active.")
                print("Host integration only: router init/firewall/WAN/proxy hardware checks remain pending.")
            finally:
                proc.terminate()
                proc.wait(timeout=10)
                backend.sock.close()
                fallback.sock.close()
                mihomo.sock.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None,
         sys.argv[3] if len(sys.argv) > 3 else None)
