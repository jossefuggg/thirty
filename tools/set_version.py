#!/usr/bin/env python3
"""Set the product version everywhere it is recorded: thirty/__init__.py, pyproject.toml, desktop/package.json.

    python3 tools/set_version.py 1.2.0

The release workflow runs this with the pushed tag (v1.2.0 -> 1.2.0) so every artifact carries the same number."""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(version):
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+.][0-9A-Za-z.-]+)?", version):
        sys.exit(f"not a version: {version}")
    p = os.path.join(ROOT, "thirty", "__init__.py")
    s = open(p).read(); s = re.sub(r'__version__ = "[^"]*"', f'__version__ = "{version}"', s); open(p, "w").write(s)
    p = os.path.join(ROOT, "pyproject.toml")
    s = open(p).read(); s = re.sub(r'(?m)^version = "[^"]*"', f'version = "{version}"', s, count=1); open(p, "w").write(s)
    p = os.path.join(ROOT, "desktop", "package.json")
    d = json.load(open(p)); d["version"] = version
    with open(p, "w") as f:
        json.dump(d, f, indent=2); f.write("\n")
    print("version set to", version)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__))
