#!/usr/bin/env python3
"""Check WED boot-option transitions without accessing a router or host modules."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "configs/ax6000/files/usr/share/turboacc/ax6000-wed.sh"


def main():
    with tempfile.TemporaryDirectory(prefix="ax6000-wed-") as directory:
        config = Path(directory) / "modules.conf"
        env = dict(os.environ, AX6000_MODULES_CONF=str(config))

        def apply(value):
            subprocess.run(["sh", str(HELPER), value], env=env, check=True)

        def options():
            tokens = [shlex.split(line, comments=True) for line in config.read_text().splitlines()]
            return [word for line in tokens if line[:2] == ["options", "mt7915e"] for word in line[2:]]

        apply("Y")
        assert options() == ["wed_enable=Y"]
        print("PASS: a missing modules.conf receives the WED driver boot option.")

        unrelated = "options example keep=1\n# options mt7915e ignored=1\n"
        comment = "# Wi-Fi settings: old wed_enable=N stays in this comment"
        config.write_text(unrelated + f"  options mt7915e wed_enable=N other=1 {comment}\n"
                          "options mt7915e extra=2 wed_enable=1 # also preserve wed_enable=1 here\n")
        apply("Y")
        assert config.read_text().startswith(unrelated)
        assert comment in config.read_text()
        assert "# also preserve wed_enable=1 here" in config.read_text()
        assert sorted(options()) == ["extra=2", "other=1", "wed_enable=Y"]
        print("PASS: duplicate WED values are replaced while other module options and comments survive.")

        before = config.read_bytes(), config.stat().st_mtime_ns
        apply("Y")
        assert (config.read_bytes(), config.stat().st_mtime_ns) == before
        apply("N")
        assert sorted(options()) == ["extra=2", "other=1", "wed_enable=N"]
        apply("Y")
        assert sorted(options()) == ["extra=2", "other=1", "wed_enable=Y"]
        print("PASS: enable/disable/re-enable persist correctly; repeated application does not rewrite the file.")

        before = config.read_bytes()
        result = subprocess.run(["sh", str(HELPER), "invalid"], env=env)
        assert result.returncode == 2 and config.read_bytes() == before
        print("PASS: invalid requests leave the module configuration unchanged.")
        print("Host logic only: real WED initialization and throughput require router boot testing.")


if __name__ == "__main__":
    main()
