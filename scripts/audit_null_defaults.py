#!/usr/bin/env python3
"""(bug class 54) Find defaults a null config value would silently defeat.

``config.get("key", SAFE_DEFAULT)`` returns the default only when the key is
ABSENT. A key present holding ``None`` returns None, and the safe default never
fires — on exactly the installs that never configured the setting, which is the
population the default exists to protect.

Unit tests cannot see this: they construct configs explicitly, so a key is
present-with-a-value or absent, never present-holding-null. That third state is
created only by the options flow and ``set_option``, i.e. only by a real
install. So the audit has to run against one.

    python3 scripts/audit_null_defaults.py --host root@10.10.20.150 \
        --key ~/.ssh/ha-prod.key

Reports each call site relying on a default for a key that is null on that
install, and whether the default is consumed safely. A default only ever tested
for truthiness is safe — ``None`` and ``""`` and ``0`` all fall the same way.
The dangerous shape is a default carrying a NUMBER the arithmetic then uses.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

REMOTE = r'''
import json
d = json.load(open('/config/.storage/core.config_entries'))
out = []
for e in d['data']['entries']:
    if e['domain'] == 'solar_energy_management':
        c = {**e.get('data', {}), **e.get('options', {})}
        out = [k for k, v in c.items() if v is None]
print(json.dumps(out))
'''

CALL = re.compile(r'config\.get\(\s*["\']([a-z0-9_]+)["\']\s*,\s*([^)\n]+)\)')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--root", default=".")
    args = ap.parse_args()

    got = subprocess.run(
        ["ssh", "-i", args.key, "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=30", args.host, "python3 -"],
        input=REMOTE, capture_output=True, text=True, timeout=120)
    if got.returncode != 0:
        raise SystemExit("remote read failed: %s" % got.stderr[-300:])
    nulls = set(json.loads(got.stdout))
    print("  %d config key(s) hold null on %s" % (len(nulls), args.host))

    root = pathlib.Path(args.root)
    files = [f for f in root.rglob("*.py")
             if "/tests/" not in str(f) and "node_modules" not in str(f)]

    hazards, safe = [], []
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines, 1):
            for m in CALL.finditer(line):
                key, default = m.group(1), m.group(2).strip()
                if key not in nulls:
                    continue
                tail = line[m.end():m.end() + 12].strip()
                # `or X` re-supplies the value; a default of "" or None is only
                # ever truthiness-tested and cannot be defeated by a null.
                benign = (tail.startswith("or ") or default in ('""', "''", "None")
                          or default in ("[]", "{}", "0", "False"))
                (safe if benign else hazards).append(
                    (str(f.relative_to(root)), i, key, default))

    for path, i, key, default in sorted(safe):
        print("    ok    %s:%d  %s (default %s)" % (path, i, key, default[:24]))
    for path, i, key, default in sorted(hazards):
        print("    HAZARD %s:%d  %s -> default %s never fires"
              % (path, i, key, default[:24]))

    print()
    print("  %d hazard(s), %d safe" % (len(hazards), len(safe)))
    return 1 if hazards else 0


if __name__ == "__main__":
    sys.exit(main())
