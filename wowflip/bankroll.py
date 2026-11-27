"""Bankroll from the game: the addon records each character's gold at the AH.

The newest value wins, whether it came from the game or from `wowflip bankroll`,
so typing a bankroll by hand still works and lasts until the next time you
open the Auction House in game.
"""

from __future__ import annotations

import json
import logging
import time

from wowflip.config import GOLD, Config

log = logging.getLogger("wowflip")


def choose_bankroll(chars: dict, wanted: tuple[str, ...] = ()) -> tuple[int, int, str] | None:
    """Pick (copper, seen_at, label) from {"Name - Realm": {"gold": c, "seen": t}}.

    With `wanted` names, their gold is added up; otherwise the character seen
    at the Auction House most recently is used.
    """
    rows = []
    for name, info in (chars or {}).items():
        if not isinstance(info, dict):
            continue
        try:
            rows.append((str(name), int(info["gold"]), int(info["seen"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not rows:
        return None
    if wanted:
        want = {w.strip().lower() for w in wanted}
        picked = [r for r in rows if r[0].lower() in want]
        if not picked:
            return None
        return sum(r[1] for r in picked), max(r[2] for r in picked), ", ".join(r[0] for r in picked)
    name, gold, seen = max(rows, key=lambda r: r[2])
    return gold, seen, name


def apply_game_bankroll(cfg: Config, chars: dict) -> float | None:
    """Store the in-game gold as the bankroll if it is newer. Returns gold or None."""
    if not cfg.addon.bankroll_from_game:
        return None
    picked = choose_bankroll(chars, cfg.addon.bankroll_characters)
    if not picked:
        return None
    copper, seen, label = picked
    try:
        current = json.loads(cfg.bankroll_file.read_text())
        if int(current.get("set_at", 0)) >= seen:
            return None
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    gold = round(copper / GOLD, 4)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.bankroll_file.write_text(json.dumps({
        "gold": gold, "set_at": seen, "source": "game", "character": label, "saved_at": int(time.time()),
    }))
    log.info("Bankroll updated from the game: %sg (%s).", gold, label)
    return gold
