#!/usr/bin/env python3
"""Run local DNS and OpenClash regressions using pinned native release binaries."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def native_binary(component, lock, cache):
    host = {("Darwin", "arm64"): "darwin_arm64",
            ("Linux", "x86_64"): "linux_amd64"}[(platform.system(), platform.machine())]
    metadata = lock[component]["host_test"]
    if host != "darwin_arm64":
        metadata = metadata["platforms"][host]
    archive = cache / metadata["url"].rsplit("/", 1)[1]
    if not archive.exists():
        partial = archive.with_suffix(archive.suffix + ".part")
        try:
            with urllib.request.urlopen(metadata["url"], timeout=60) as response:
                partial.write_bytes(response.read())
            assert hashlib.sha256(partial.read_bytes()).hexdigest() == metadata["sha256"], archive
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == metadata["sha256"], archive
    if component == "mihomo":
        payload = gzip.decompress(archive.read_bytes())
        arguments = ["-v"]
    else:
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as source:
                names = [name for name in source.namelist() if name.endswith("/AdGuardHome")]
                assert len(names) == 1, names
                payload = source.read(names[0])
        else:
            with tarfile.open(archive) as source:
                members = [member for member in source.getmembers()
                           if member.isfile() and member.name.endswith("/AdGuardHome")]
                assert len(members) == 1, members
                payload = source.extractfile(members[0]).read()
        arguments = ["--version"]
    destination = cache / "host-test" / (component + "-v" + lock[component]["version"] + "-" + host)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    destination.chmod(0o755)
    version = subprocess.check_output([str(destination), *arguments], text=True)
    assert "v" + lock[component]["version"] in version, version
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", required=True, type=Path)
    args = parser.parse_args()
    tree = args.tree.resolve()
    lock = json.loads((tree / ".ax6000-build-lock.json").read_text())
    cache = tree.parent.parent
    logs = ROOT / "artifacts/ax6000/releases" / lock["build_id"] / "logs/host-tests"
    logs.mkdir(parents=True, exist_ok=True)
    mihomo = native_binary("mihomo", lock, cache)
    adguard = native_binary("adguardhome", lock, cache)
    geosite = tree / "files/etc/openclash/GeoSite.dat"
    openclash = tree / "feeds/luci/applications/luci-app-openclash/root"
    tests = [
        ("geosite", ["scripts/ax6000_geosite.py", "test", str(cache / lock["assets"]["geosite"]["filename"]), str(geosite), str(mihomo)]),
        ("router-profile", ["scripts/test-ax6000-router-profile.py", "--mihomo", str(mihomo), "--geosite", str(geosite)]),
        ("dns", ["scripts/test-ax6000-dns.py", str(adguard), str(mihomo), str(geosite)]),
        ("adguard-ui", ["scripts/test-ax6000-adguardhome-ui.py", str(adguard), str(tree / "feeds/luci/applications/luci-app-adguardhome/root/usr/share/AdGuardHome/ax6000-ui-prepare.rb")]),
        ("routing", ["scripts/test-ax6000-routing.py"]),
        ("wed", ["scripts/test-ax6000-wed.py"]),
        ("openclash-lifecycle", ["scripts/test-ax6000-openclash-lifecycle.py", "--converter", str(openclash / "usr/share/openclash/yml_change.sh")]),
        ("openclash-integrity", ["scripts/test-ax6000-openclash-integrity.py", "--updater", str(openclash / "usr/share/openclash/openclash.sh")]),
        ("openclash-subscription", ["scripts/test-ax6000-openclash-subscription.py", "--init", str(openclash / "etc/init.d/openclash"), "--updater", str(openclash / "usr/share/openclash/openclash.sh"), "--process-helper", str(openclash / "usr/share/openclash/openclash_ps.sh")]),
    ]
    tests = [(name, ["python3", *command]) for name, command in tests]
    tests.extend(("luci-" + name.removesuffix(".js"),
                  ["node", str(tree / "feeds/luci/modules/luci-mod-status/tests" / name)])
                 for name in ["overview-async.js", "mount-points.js", "wifi-disabled.js"])
    results = {}
    for name, command in tests:
        with (logs / (name + ".log")).open("w") as output:
            result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        results[name] = "PASS" if result.returncode == 0 else "FAIL"
        (logs / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
        print(name + ": " + results[name], flush=True)
        if result.returncode:
            print((logs / (name + ".log")).read_text(), flush=True)
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
