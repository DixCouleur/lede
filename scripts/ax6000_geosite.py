#!/usr/bin/env python3
"""Copy selected GeoSite protobuf entries without rewriting their domain data.

Schema: https://github.com/v2fly/v2ray-core/blob/master/app/router/routercommon/common.proto
Only the GeoSiteList envelope and category names are parsed. Complete retained
entry bytes, including all domain types, attributes and unknown fields, survive.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

POLICY = Path(__file__).resolve().parents[1] / "configs/ax6000/geosite-keep.json"
if not POLICY.is_file():
    POLICY = Path(__file__).with_name("geosite-keep.json")


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("Truncated protobuf varint")
        byte = data[offset]
        offset += 1
        if shift == 63 and byte > 1:
            raise ValueError("Protobuf varint exceeds uint64")
        value |= (byte & 0x7f) << shift
        if byte < 0x80:
            return value, offset
    raise ValueError("Invalid protobuf varint")


def fields(data):
    offset = 0
    while offset < len(data):
        start = offset
        tag, offset = varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise ValueError("Invalid protobuf field number")
        if wire == 0:
            value, offset = varint(data, offset)
        else:
            if wire == 2:
                size, offset = varint(data, offset)
            elif wire in (1, 5):
                size = 8 if wire == 1 else 4
            else:
                raise ValueError(f"Unsupported protobuf wire type {wire}")
            end = offset + size
            if end > len(data):
                raise ValueError("Truncated protobuf field")
            value = data[offset:end]
            offset = end
        yield number, wire, value, data[start:offset]


def entries(data):
    result = {}
    for number, wire, payload, raw in fields(data):
        if (number, wire) != (1, 2):
            raise ValueError("Unexpected GeoSiteList field; refusing to drop it")
        names = [value.decode("ascii").lower()
                 for number, wire, value, _ in fields(payload)
                 if (number, wire) == (1, 2)]
        if len(names) != 1 or not names[0] or names[0] in result:
            raise ValueError(f"Invalid or duplicate GeoSite category: {names}")
        result[names[0]] = raw
    if not result:
        raise ValueError("Empty GeoSite data")
    return result


def load_policy(path=None):
    policy = json.loads((path or POLICY).read_text())
    categories = policy["categories"]
    if not categories or categories != sorted(set(categories)):
        raise ValueError("GeoSite categories must be sorted and unique")
    if any(ref.split("@", 1)[0] not in categories for ref in policy["test_references"]):
        raise ValueError("Test reference missing from retained categories")
    return policy


def check_geosite(data, policy=None):
    policy = policy or load_policy()
    if hashlib.sha256(data).hexdigest() != policy["output_sha256"]:
        raise ValueError("Trimmed GeoSite SHA256 differs from policy")
    selected = entries(data)
    if set(selected) != set(policy["categories"]):
        raise ValueError("Trimmed GeoSite categories differ from policy")
    return selected


def trim(source, destination, manifest=None):
    policy = load_policy()
    original = source.read_bytes()
    if hashlib.sha256(original).hexdigest() != policy["source_sha256"]:
        raise ValueError("Full GeoSite SHA256 differs from pinned source")
    all_entries = entries(original)
    missing = set(policy["categories"]) - set(all_entries)
    if missing:
        raise ValueError(f"GeoSite categories absent in source: {sorted(missing)}")
    # Preserve original category order and every byte inside retained entries.
    selected = {name: raw for name, raw in all_entries.items() if name in policy["categories"]}
    output = b"".join(selected.values())
    check_geosite(output, policy)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_bytes() != output:
        destination.write_bytes(output)
    destination.chmod(0o644)
    report = {
        "source_sha256": policy["source_sha256"], "source_bytes": len(original),
        "source_categories": len(all_entries), "output_sha256": policy["output_sha256"],
        "output_bytes": len(output), "output_categories": len(selected),
        "entries": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                    for name, raw in sorted(selected.items())},
    }
    if manifest:
        manifest.write_text(json.dumps(report, indent=2) + "\n")
    print(f"GeoSite: {len(original)} -> {len(output)} bytes; "
          f"{len(all_entries)} -> {len(selected)} categories; exact entry bytes retained: PASS")
    return report


def test_native(source, trimmed, mihomo):
    policy = load_policy()
    original = source.read_bytes()
    assert hashlib.sha256(original).hexdigest() == policy["source_sha256"]
    all_entries = entries(original)
    selected = check_geosite(trimmed.read_bytes(), policy)
    assert all(raw == all_entries[name] for name, raw in selected.items())
    print("All retained domain/regex/attribute protobuf bytes match full source: PASS", flush=True)
    with tempfile.TemporaryDirectory(prefix="ax6000-geosite-test-") as tmp:
        directory = Path(tmp)
        shutil.copyfile(trimmed, directory / "GeoSite.dat")
        for loader in ("memconservative", "standard"):
            config = {
                "mode": "rule", "log-level": "info", "find-process-mode": "off",
                "geo-auto-update": False, "geodata-loader": loader,
                "rules": [f"GEOSITE,{name},DIRECT" for name in policy["test_references"]] + ["MATCH,DIRECT"],
            }
            path = directory / "config.json"
            path.write_text(json.dumps(config))
            result = subprocess.run([str(mihomo.resolve()), "-t", "-d", tmp, "-f", str(path)],
                                    capture_output=True, text=True, timeout=90)
            print(result.stdout + result.stderr, end="", flush=True)
            if result.returncode:
                raise ValueError(f"Mihomo {loader} GeoSite check failed")
            output = result.stdout + result.stderr
            if "test is successful" not in output.lower():
                raise ValueError("Mihomo did not confirm configuration validation")
            for name in policy["test_references"]:
                if f"Finished initial GeoSite rule {name} => DIRECT, records:" not in output:
                    raise ValueError(f"Mihomo did not load GeoSite reference {name}")
            print(f"Mihomo {loader}: all retained categories including category-games@cn: PASS", flush=True)


def main():
    global POLICY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=POLICY)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("trim")
    create.add_argument("source", type=Path)
    create.add_argument("destination", type=Path)
    create.add_argument("--manifest", type=Path)
    check = sub.add_parser("check")
    check.add_argument("file", type=Path)
    test = sub.add_parser("test")
    test.add_argument("source", type=Path)
    test.add_argument("trimmed", type=Path)
    test.add_argument("mihomo", type=Path)
    args = parser.parse_args()
    POLICY = args.policy
    if args.command == "trim":
        trim(args.source, args.destination, args.manifest)
    elif args.command == "check":
        result = check_geosite(args.file.read_bytes())
        print(f"Trimmed GeoSite hash and {len(result)} categories: PASS")
    else:
        test_native(args.source, args.trimmed, args.mihomo)


if __name__ == "__main__":
    main()
