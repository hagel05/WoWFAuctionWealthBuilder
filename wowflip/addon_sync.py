"""Bridge between the flip feed and the WoW client folder.

WoW addons cannot make network calls, so data reaches the game the way
TradeSkillMaster does it: this writes the feed as Lua into a small data addon,
`Interface/AddOns/WoWFlipData`, which the game loads at login or /reload.
Going the other way, the WoWFlip addon saves each character's gold in its
SavedVariables file, which the game writes on logout or /reload.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from wowflip.lua import LuaParseError, parse_saved_variables, to_lua

log = logging.getLogger("wowflip")

DATA_ADDON = "WoWFlipData"
MAIN_ADDON = "WoWFlip"
INTERFACE = "16001"  # WoW Forever client, Nov 2026

DATA_TOC = f"""## Interface: {INTERFACE}
## Title: WoWFlip Data
## Notes: Flip list written by the wowflip sync helper. Do not edit; it is replaced after each scan.
## Author: wowflip
## Version: 1
Data.lua
"""


def find_game_root(wow_dir: Path | str, game_folder: str = "_forever_") -> Path | None:
    """The `_forever_` folder for a wow_dir that may point at it or anywhere inside it.

    Accepts the World of Warcraft folder (the documented setting), the
    `_forever_` folder itself, or a folder under it such as Interface/AddOns.
    """
    path = Path(wow_dir)
    if (path / game_folder).is_dir():
        return path / game_folder
    for candidate in (path, *path.parents):
        if candidate.name.lower() == game_folder.lower() and candidate.is_dir():
            return candidate
    return None


class WowInstall:
    def __init__(self, wow_dir: Path | str, game_folder: str = "_forever_"):
        root = find_game_root(wow_dir, game_folder)
        if root is None:
            raise FileNotFoundError(
                f"No {game_folder} folder found at {wow_dir}. Set [addon] wow_dir in config.toml to the "
                f"World of Warcraft folder that contains {game_folder}, "
                'e.g. wow_dir = "C:/Program Files (x86)/World of Warcraft".'
            )
        self.root = root

    @property
    def addons_dir(self) -> Path:
        return self.root / "Interface" / "AddOns"

    @property
    def data_dir(self) -> Path:
        return self.addons_dir / DATA_ADDON

    def main_addon_installed(self) -> bool:
        return (self.addons_dir / MAIN_ADDON / f"{MAIN_ADDON}.toc").is_file()

    def saved_variable_files(self) -> list[Path]:
        return sorted((self.root / "WTF" / "Account").glob(f"*/SavedVariables/{MAIN_ADDON}.lua"))

    def write_feed(self, feed: dict) -> Path:
        """Write the feed into WoWFlipData/Data.lua (atomically)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        toc = self.data_dir / f"{DATA_ADDON}.toc"
        if not toc.is_file() or toc.read_text(encoding="utf-8") != DATA_TOC:
            toc.write_text(DATA_TOC, encoding="utf-8")
        target = self.data_dir / "Data.lua"
        tmp = target.with_name("Data.lua.tmp")
        tmp.write_text(render_data_lua(feed), encoding="utf-8")
        os.replace(tmp, target)
        return target

    def written_generated_at(self) -> int | None:
        """generated_at of the feed already in Data.lua, if any."""
        try:
            with (self.data_dir / "Data.lua").open(encoding="utf-8") as fh:
                for _ in range(5):
                    line = fh.readline()
                    if line.startswith("-- generated_at="):
                        return int(line.split("=", 1)[1])
        except (OSError, ValueError):
            pass
        return None

    def read_characters(self) -> dict:
        """Gold seen by the addon, merged across every account folder."""
        chars: dict = {}
        for path in self.saved_variable_files():
            try:
                data = parse_saved_variables(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, LuaParseError) as exc:
                log.warning("Could not read %s: %s", path, exc)
                continue
            db = data.get("WoWFlipDB")
            if not isinstance(db, dict) or not isinstance(db.get("chars"), dict):
                continue
            for name, info in db["chars"].items():
                if not isinstance(info, dict):
                    continue
                old = chars.get(name)
                if old is None or info.get("seen", 0) > old.get("seen", 0):
                    chars[name] = info
        return chars


def render_data_lua(feed: dict) -> str:
    data = dict(feed)
    # Lua tables keyed by item id (numbers) so the addon can look items up directly.
    data["prices"] = {int(k): v for k, v in (feed.get("prices") or {}).items()}
    return (
        f"-- generated_at={int(feed.get('generated_at', 0))}\n"
        "-- Written by the wowflip sync helper. Replaced after every scan.\n"
        f"WoWFlipData_Feed = {to_lua(data)}\n"
    )
