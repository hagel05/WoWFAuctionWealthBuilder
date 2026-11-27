"""Entry point for the standalone sync helper (WoWFlipSync.exe).

Runs `wowflip sync --loop` with config.toml from the folder the .exe is in, so
another PC only needs the .exe and a config.toml with an [addon] section.
Pass --once to sync a single time instead.
"""

import sys
from pathlib import Path

from wowflip.cli import main

if __name__ == "__main__":
    here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    args = sys.argv[1:]
    once = "--once" in args
    args = [a for a in args if a != "--once"]
    if "--config" not in args:
        args = ["--config", str(here / "config.toml")] + args
    sys.exit(main(args + ["sync"] + ([] if once else ["--loop"])))
