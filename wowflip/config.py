"""Settings: defaults from the flip scoring rules, overridable in config.toml.

All money is kept in copper (1 gold = 100 silver = 10,000 copper).
Every number marked "guess" comes from the scoring rules doc and is meant to
be tuned after a few weeks of real snapshots.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

GOLD = 10_000
SILVER = 100


@dataclass(frozen=True)
class Profile:
    """Buy rules that change with bankroll size."""

    name: str
    min_discount: float  # rule 1: 1 - B / MV
    min_profit_per_unit: int  # rule 2, copper
    min_profit_per_flip: int  # rule 2, copper
    min_roi: float  # rule 2
    min_daily_sales: float  # rule 3
    max_days_to_sell: float  # rule 3
    max_flip_share: float  # rule 5: share of bankroll per flip
    max_item_days_of_sales: float  # exposure cap: units <= this many days of sales
    volatility_cap: float  # (P80 - P20) / MV
    item_classes: tuple[str, ...]  # item_class names that may be flipped
    allow_boe_gear: bool  # Weapon/Armor that bind on equip


CAREFUL = Profile(
    name="careful",
    min_discount=0.30,
    min_profit_per_unit=10 * SILVER,
    min_profit_per_flip=50 * SILVER,
    min_roi=0.25,
    min_daily_sales=5,
    max_days_to_sell=2,
    max_flip_share=0.15,
    max_item_days_of_sales=2,
    volatility_cap=0.5,
    item_classes=("Trade Goods", "Consumable"),
    allow_boe_gear=False,
)

# Used automatically once the bankroll passes Market.balanced_at_gold.
# The rules doc only fixes "3 days to sell, higher floors"; the rest are guesses.
BALANCED = Profile(
    name="balanced",
    min_discount=0.25,
    min_profit_per_unit=25 * SILVER,
    min_profit_per_flip=2 * GOLD,
    min_roi=0.20,
    min_daily_sales=3,
    max_days_to_sell=3,
    max_flip_share=0.20,
    max_item_days_of_sales=3,
    volatility_cap=0.6,
    item_classes=("Trade Goods", "Consumable", "Weapon", "Armor"),
    allow_boe_gear=True,
)


@dataclass(frozen=True)
class Market:
    """Market-wide settings that do not depend on bankroll."""

    history_days: float = 14  # MV window
    recent_days: float = 3  # MV3 window
    undercut: float = 0.03  # T = (1 - undercut) * min(MV, MV3)
    # WoW Forever's AH sells the newest listing first among equal prices (LIFO),
    # so listings at your price are behind you and matching a price is enough.
    newest_first_at_same_price: bool = True
    ah_cut: float = 0.05  # confirmed: faction AH
    listing_hours: int = 24  # default listing duration
    deposit_rates: dict = field(
        default_factory=lambda: {"2": 0.05, "8": 0.20, "24": 0.60}
    )  # confirmed: share of vendor sell price
    max_sell_chance: float = 0.95
    min_history_days: float = 7
    min_seen_share: float = 0.70
    sales_price_floor: float = 0.80  # only count sales at >= 0.8 * MV
    min_auctions: float = 5
    max_price_point_share: float = 0.60
    price_point_window: float = 1.2  # look at units listed up to 1.2 * MV
    crash_ratio: float = 0.85  # skip if MV3 < 0.85 * MV
    reset_rise: float = 0.50  # skip if min buyout rose > 50% in 24h ...
    reset_supply_drop: float = 0.50  # ... while units listed fell by more than half
    min_vendor_profit: int = 10 * SILVER  # skip vendor flips worth less than this per item
    # Early market flips: from ramp_start_days of history, with stricter rules
    # that relax linearly until min_history_days (guesses).
    ramp_start_days: float = 2
    ramp_extra_discount: float = 0.15  # +15 points on min discount at the start
    ramp_extra_roi: float = 0.15  # +15 points on min ROI at the start
    ramp_sales_factor: float = 2.0  # need 2x the daily sales at the start
    ramp_share_factor: float = 0.5  # half the per-flip bankroll share at the start
    # Snapshot flips: judged from the current listings alone, for items without
    # ramp_start_days of history. Riskier: sales speed is unknown (guesses).
    snapshot_flips: bool = True
    snapshot_min_discount: float = 0.30  # cheapest vs median of the rest
    snapshot_min_roi: float = 0.30
    snapshot_min_auctions: int = 8  # listings left after buying
    snapshot_flip_share: float = 0.10  # of bankroll per flip
    snapshot_max_unit_share: float = 0.25  # buy at most this share of the units listed
    snapshot_sell_chance: float = 0.5  # assumed chance a relist sells, for deposit risk
    balanced_at_gold: float = 200
    keep_days: float = 30  # prune history older than this

    @property
    def deposit_rate(self) -> float:
        return float(self.deposit_rates[str(self.listing_hours)])


@dataclass(frozen=True)
class Addon:
    """In-game addon and sync helper settings (the [addon] section)."""

    wow_dir: Path | None = None  # e.g. C:/Program Files (x86)/World of Warcraft
    game_folder: str = "_forever_"  # client folder inside wow_dir
    sync_url: str = ""  # scanner API on another machine, e.g. http://truenas:8787
    sync_minutes: float = 5  # how often `wowflip sync --loop` checks for new data
    bankroll_from_game: bool = True  # use the gold the addon saw as the bankroll
    bankroll_characters: tuple[str, ...] = ()  # "Name - Realm"; empty = last character at the AH


@dataclass(frozen=True)
class Server:
    host: str = "0.0.0.0"
    port: int = 8787


@dataclass(frozen=True)
class Config:
    region: str = "us"
    ruleset_id: int = 2  # Normal
    house_id: int = 111  # Alliance Normal
    include_commodities: bool = True
    bankroll_gold: float = 30
    data_dir: Path = Path("data")
    report_dir: Path = Path("reports")
    item_override_csv: Path = Path("items_override.csv")
    max_new_item_lookups: int = 1000
    item_lookup_workers: int = 8
    scan_minute: int = 20
    market: Market = field(default_factory=Market)
    addon: Addon = field(default_factory=Addon)
    server: Server = field(default_factory=Server)
    api_token: str = ""  # shared secret between the API and sync helpers; empty = no check
    careful: Profile = CAREFUL
    balanced: Profile = BALANCED
    client_id: str = ""
    client_secret: str = ""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wowflip.sqlite"

    @property
    def bankroll_file(self) -> Path:
        return self.data_dir / "bankroll.json"

    def bankroll_copper(self) -> int:
        """Bankroll for this run: `wowflip bankroll` value if set, else config."""
        try:
            data = json.loads(self.bankroll_file.read_text())
            return int(round(float(data["gold"]) * GOLD))
        except (OSError, ValueError, KeyError, TypeError):
            return int(round(self.bankroll_gold * GOLD))

    def profile_for(self, bankroll: int) -> Profile:
        if bankroll >= self.market.balanced_at_gold * GOLD:
            return self.balanced
        return self.careful


def _override(obj, values: dict):
    """Return a copy of a dataclass with matching keys replaced."""
    known = {f.name: f for f in fields(obj)}
    changes = {}
    for key, value in values.items():
        if key not in known:
            raise ValueError(f"Unknown setting '{key}' in config.toml")
        if isinstance(getattr(obj, key), tuple):
            value = tuple(value)
        if key in ("min_profit_per_unit", "min_profit_per_flip"):
            value = int(value)
        changes[key] = value
    return replace(obj, **changes)


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without overriding real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def load_config(path: Path | str = "config.toml") -> Config:
    path = Path(path)
    base = path.parent if path.parent != Path("") else Path(".")
    load_dotenv(base / ".env")

    raw: dict = {}
    if path.is_file():
        with path.open("rb") as fh:
            raw = tomllib.load(fh)

    cfg = Config()
    account = raw.get("account", {})
    storage = raw.get("storage", {})
    items = raw.get("items", {})
    schedule = raw.get("schedule", {})

    simple = {}
    for key in ("region", "ruleset_id", "house_id", "include_commodities", "bankroll_gold"):
        if key in account:
            simple[key] = account[key]
    if "data_dir" in storage:
        simple["data_dir"] = Path(storage["data_dir"])
    if "report_dir" in storage:
        simple["report_dir"] = Path(storage["report_dir"])
    if "override_csv" in items:
        simple["item_override_csv"] = Path(items["override_csv"])
    if "max_new_lookups_per_run" in items:
        simple["max_new_item_lookups"] = int(items["max_new_lookups_per_run"])
    if "minute" in schedule:
        simple["scan_minute"] = int(schedule["minute"])
    cfg = replace(cfg, **simple)

    # Relative paths are relative to the config file's folder.
    cfg = replace(
        cfg,
        data_dir=(base / cfg.data_dir),
        report_dir=(base / cfg.report_dir),
        item_override_csv=(base / cfg.item_override_csv),
    )

    if "market" in raw:
        cfg = replace(cfg, market=_override(cfg.market, raw["market"]))
    if "addon" in raw:
        a = dict(raw["addon"])
        if a.get("wow_dir"):
            a["wow_dir"] = Path(a["wow_dir"])
        if "bankroll_characters" in a:
            a["bankroll_characters"] = tuple(a["bankroll_characters"])
        cfg = replace(cfg, addon=_override(cfg.addon, a))
    if "server" in raw:
        cfg = replace(cfg, server=_override(cfg.server, raw["server"]))
    profiles = raw.get("profiles", {})
    if "careful" in profiles:
        cfg = replace(cfg, careful=_override(cfg.careful, profiles["careful"]))
    if "balanced" in profiles:
        cfg = replace(cfg, balanced=_override(cfg.balanced, profiles["balanced"]))

    # Environment variables win over config.toml, so a container can be
    # configured without a config file.
    env = os.environ
    env_changes: dict = {}
    for var, key, cast in (
        ("WOWFLIP_REGION", "region", str),
        ("WOWFLIP_RULESET_ID", "ruleset_id", int),
        ("WOWFLIP_HOUSE_ID", "house_id", int),
        ("WOWFLIP_BANKROLL_GOLD", "bankroll_gold", float),
        ("WOWFLIP_DATA_DIR", "data_dir", Path),
        ("WOWFLIP_REPORT_DIR", "report_dir", Path),
        ("WOWFLIP_ITEM_OVERRIDE_CSV", "item_override_csv", Path),
        ("WOWFLIP_SCAN_MINUTE", "scan_minute", int),
    ):
        if env.get(var):
            env_changes[key] = cast(env[var])
    if env.get("WOWFLIP_INCLUDE_COMMODITIES"):
        env_changes["include_commodities"] = env["WOWFLIP_INCLUDE_COMMODITIES"].lower() in ("1", "true", "yes")
    addon_env = {}
    if env.get("WOWFLIP_WOW_DIR"):
        addon_env["wow_dir"] = Path(env["WOWFLIP_WOW_DIR"])
    if env.get("WOWFLIP_SYNC_URL"):
        addon_env["sync_url"] = env["WOWFLIP_SYNC_URL"]
    if addon_env:
        env_changes["addon"] = replace(cfg.addon, **addon_env)
    server_env = {}
    if env.get("WOWFLIP_SERVER_HOST"):
        server_env["host"] = env["WOWFLIP_SERVER_HOST"]
    if env.get("WOWFLIP_SERVER_PORT"):
        server_env["port"] = int(env["WOWFLIP_SERVER_PORT"])
    if server_env:
        env_changes["server"] = replace(cfg.server, **server_env)
    cfg = replace(
        cfg,
        **env_changes,
        api_token=env.get("WOWFLIP_API_TOKEN", ""),
        client_id=env.get("BLIZZARD_CLIENT_ID", ""),
        client_secret=env.get("BLIZZARD_CLIENT_SECRET", ""),
    )
    return cfg


def money(copper: float) -> str:
    """Format copper as '1g 86s 24c'."""
    copper = int(round(copper))
    sign = "-" if copper < 0 else ""
    copper = abs(copper)
    g, rest = divmod(copper, GOLD)
    s, c = divmod(rest, SILVER)
    parts = []
    if g:
        parts.append(f"{g}g")
    if s or g:
        parts.append(f"{s}s")
    parts.append(f"{c}c")
    return sign + " ".join(parts)
