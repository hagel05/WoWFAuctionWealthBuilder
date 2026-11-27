"""The flip feed: what the in-game addon needs from a scan, as one JSON document.

The scanner writes it to `<report_dir>/latest.json` after every scan, the API
serves it at /api/v1/feed, and the sync helper turns it into the WoWFlipData
addon's Lua file.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from wowflip.config import Config
from wowflip.scan import ScanResult

FEED_VERSION = 1


def build_feed(result: ScanResult, cfg: Config) -> dict:
    def flip_row(f) -> dict:
        row = {
            "item_id": f.item_id,
            "name": f.name,
            "kind": f.kind,  # market | early | snapshot
            "buy_max": f.max_price,  # highest unit price worth paying
            "quantity": f.quantity,
            "cost": f.cost,
            "relist": int(round(f.target)),  # unit price to list at
            "profit": int(round(f.net_profit)),
            "roi": round(f.roi, 3),
            "buys": [[b.unit_price, b.quantity] for b in f.buys],
        }
        if f.days_to_sell == f.days_to_sell:  # unknown (NaN) for snapshot flips
            row["days_to_sell"] = round(f.days_to_sell, 1)
        if f.kind == "snapshot":
            row["reference"] = int(round(f.reference))  # what the other listings ask
        return row

    flips = [flip_row(f) for f in result.flips]
    snapshot = [flip_row(f) for f in result.snapshots[:100]]

    # One row per item: buy every listing under what a vendor pays.
    vendor: dict[int, dict] = {}
    for v in result.vendor:
        row = vendor.setdefault(v.item_id, {
            "item_id": v.item_id, "name": v.name, "vendor_price": v.sell_price,
            "buy_max": v.sell_price - 1, "quantity": 0, "cost": 0, "profit": 0,
        })
        row["quantity"] += v.quantity
        row["cost"] += v.cost
        row["profit"] += v.profit
    vendor_rows = sorted(vendor.values(), key=lambda r: r["profit"], reverse=True)

    return {
        "version": FEED_VERSION,
        "generated_at": int(result.taken_at),
        "region": cfg.region,
        "house_id": cfg.house_id,
        "profile": result.profile,
        "bankroll": int(result.bankroll),
        "history_days": round(result.history_days, 1),
        "listing_hours": cfg.market.listing_hours,
        "ah_cut": cfg.market.ah_cut,
        "deposit_rate": cfg.market.deposit_rate,
        # Most one flip may cost (bankroll share for this profile); the addon's
        # Buy button never spends more than this per item.
        "max_flip_cost": int(cfg.profile_for(result.bankroll).max_flip_share * result.bankroll),
        "flips": flips,
        # Riskier flips judged from current listings only (items with no history yet).
        "snapshot": snapshot,
        "vendor": vendor_rows[:100],
        # item id -> [market value in copper, units sold per day]
        "prices": {str(i): [int(round(mv)), round(ds, 1)] for i, (mv, ds) in sorted(result.prices.items())},
    }


def write_json_atomic(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
    return path


def feed_path(cfg: Config) -> Path:
    return cfg.report_dir / "latest.json"


def write_feed(result: ScanResult, cfg: Config) -> Path:
    return write_json_atomic(feed_path(cfg), build_feed(result, cfg))


def load_feed(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != FEED_VERSION:
        raise ValueError(f"{path} is not a version {FEED_VERSION} flip feed")
    return data


def feed_age_minutes(feed: dict, now: float | None = None) -> float:
    now = time.time() if now is None else now
    return (now - feed.get("generated_at", 0)) / 60
