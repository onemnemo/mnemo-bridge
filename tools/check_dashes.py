"""Fails when a tracked text file contains an em dash or an en dash."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DASHES = (chr(0x2014), chr(0x2013))
BINARY = {".png", ".ico", ".icns"}


def main() -> int:
    names = subprocess.check_output(["git", "ls-files"], text=True).split()
    bad = [
        name
        for name in names
        if Path(name).suffix not in BINARY
        and any(dash in Path(name).read_text(encoding="utf-8", errors="ignore") for dash in DASHES)
    ]
    if bad:
        print("Em or en dashes in: " + ", ".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
