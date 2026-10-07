"""Command line entry point. Each source has its own command."""

from __future__ import annotations

import sys

from . import __version__

USAGE = """\
usage: mnemo-bridge <command> ...

commands:
  notion   pull Notion pages into a .mnemo package, or push one into Notion
  gui      open the app

Add --help after a command for its options.
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command, rest = (argv[0], argv[1:]) if argv else ("", [])

    if command == "notion":
        from .sources.notion.cli import main as notion_main

        return notion_main(rest)
    if command == "gui":
        from .gui.app import run_gui

        return run_gui()
    if command == "--version":
        print(f"mnemo-bridge {__version__}")
        return 0
    asked = command in {"-h", "--help"}
    print(USAGE, file=sys.stdout if asked else sys.stderr)
    return 0 if asked else 2
