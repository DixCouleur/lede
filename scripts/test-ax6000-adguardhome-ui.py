#!/usr/bin/env python3
"""Validate the LuCI settings adapter and a real wildcard Web listener.

Uses a native same-version AdGuard Home binary; DHCP is disabled for this test.
"""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(subprocess.check_output(
        ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_file(ARGV[0]))", str(path)]))


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main(binary, helper):
    seed = load(ROOT / "configs/ax6000/files/etc/adguardhome/adguardhome.yaml")
    with tempfile.TemporaryDirectory(prefix="ax6000-agh-ui-") as directory:
        directory = Path(directory)
        path = directory / "AdGuardHome.yaml"
        old = json.loads(json.dumps(seed))
        old["http"]["address"] = "127.0.0.1:3000"
        path.write_text(json.dumps(old))
        subprocess.run(["ruby", str(helper), str(path), "0.0.0.0", "3000", ""], check=True)
        migrated = load(path)
        assert migrated["http"]["address"] == "0.0.0.0:3000"
        for key in ["dns", "dhcp", "filters", "users", "querylog", "statistics"]:
            assert migrated[key] == old[key], key
        before = path.read_bytes()
        bad = subprocess.run(["ruby", str(helper), str(path), "0.0.0.0", "70000", ""], capture_output=True)
        assert bad.returncode and path.read_bytes() == before
        # Check the plugin's password field against the modern users array.
        bcrypt = "$2y$10$FfeQavihMUiXCuJhHuQwy.6EOXDvkXb/S50qI5fXizqarNT/ShhQm"
        subprocess.run(["ruby", str(helper), str(path), "0.0.0.0", "3000", bcrypt], check=True)
        account = load(path)["users"]
        assert account == [{"name": "root", "password": bcrypt}]
        print("PASS: old loopback config migrates to 0.0.0.0:3000; DNS/DHCP settings remain intact; port/hash validation works.")

        http_port = free_port(socket.SOCK_STREAM)
        seed["dns"]["bind_hosts"] = ["127.0.0.1"]
        seed["dns"]["port"] = free_port(socket.SOCK_DGRAM)
        seed["dhcp"]["enabled"] = False
        seed["filters"] = []
        for key in ["querylog", "statistics"]:
            (directory / key).mkdir()
            seed[key]["dir_path"] = str(directory / key)
        path.write_text(json.dumps(seed))
        subprocess.run(["ruby", str(helper), str(path), "0.0.0.0", str(http_port), ""], check=True)
        subprocess.run([str(binary), "--config", str(path), "--check-config"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with (directory / "core.log").open("w") as log:
            core = subprocess.Popen([str(binary), "--config", str(path), "--work-dir", str(directory), "--no-check-update"], stdout=log, stderr=log)
            try:
                for _ in range(60):
                    try:
                        with opener.open(f"http://127.0.0.1:{http_port}/control/status", timeout=1) as response:
                            assert response.status == 200
                            break
                    except OSError:
                        if core.poll() is not None:
                            raise RuntimeError((directory / "core.log").read_text())
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Web listener did not start")
                # UDP connect selects the local route/address without sending data.
                # This works on Linux and macOS, without assuming an interface name.
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                    route.connect(("192.0.2.1", 9))
                    lan_ip = route.getsockname()[0]
                assert lan_ip and not lan_ip.startswith("127.")
                for host in ["127.0.0.1", lan_ip]:
                    with opener.open(f"http://{host}:{http_port}/", timeout=3) as response:
                        assert response.status == 200
                        html = response.read().decode()
                        assert "AdGuard" in html
                    with opener.open(f"http://{host}:{http_port}/control/status", timeout=3) as response:
                        assert json.load(response)["version"] == "v0.107.79"
                for asset in re.findall(r'(?:src|href)="([^\"]+\.(?:js|css)(?:\?[^\"]*)?)"', html):
                    with opener.open(f"http://{lan_ip}:{http_port}/" + asset.lstrip("/"), timeout=3) as response:
                        assert response.status == 200 and response.read()
                # The OpenClash API helper must follow the plugin's configured port.
                tools_dir = directory / "tools"
                tools_dir.mkdir()
                uci = tools_dir / "uci"
                uci.write_text(f"#!/bin/sh\nprintf '%s\\n' '{http_port}'\n")
                uci.chmod(0o755)
                env = dict(os.environ, PATH=str(tools_dir) + os.pathsep + os.environ["PATH"],
                           AX6000_AGH_STATE=str(directory / "upstream.json"),
                           AX6000_AGH_LOCK=str(directory / "switch.lock"))
                env.pop("AX6000_AGH_URL", None)
                switch = ROOT / "configs/ax6000/files/usr/share/openclash/adguardhome_dns.rb"
                subprocess.run(["ruby", str(switch), "proxy"], env=env, check=True)
                with opener.open(f"http://127.0.0.1:{http_port}/control/dns_info", timeout=3) as response:
                    assert json.load(response)["upstream_dns"] == ["127.0.0.1:7874"]
                subprocess.run(["ruby", str(switch), "direct"], env=env, check=True)
                with opener.open(f"http://127.0.0.1:{http_port}/control/dns_info", timeout=3) as response:
                    assert json.load(response)["upstream_dns"] == seed["dns"]["upstream_dns"]
                print("PASS: real AdGuard Home Web/API/assets work through loopback and the host LAN address on a wildcard listener; DHCP disabled.")
                print("PASS: OpenClash API switch/restore follows the plugin's configured Web port.")
            finally:
                core.terminate()
                core.wait(timeout=10)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: test-ax6000-adguardhome-ui.py NATIVE_AGH_BINARY UI_PREPARE_HELPER")
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
