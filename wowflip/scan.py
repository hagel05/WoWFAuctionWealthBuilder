"""One hourly scan: fetch listings, update history, score flips, write the report."""

from __future__ import annotations

import csv
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from wowflip.config import Config
from wowflip.scoring import (
    Flip,
    VendorFlip,
    build_market_stats,
    evaluate_item,
    vendor_flips,
)
from wowflip.stats import fingerprint, group_by_item, infer_sales, summarize
from wowflip.store import ItemInfo, Listing, Store

log = logging.getLogger("wowflip")
DAY = 86_400


def normalize(raw: list[dict], commodity: bool) -> list[Listing]:
    """Turn API auctions into per-unit listings. Bid-only listings are skipped."""
    out = []
    for a in raw:
        try:
            item_id = int(a["item"]["id"])
            qty = int(a.get("quantity") or 1)
            if commodity or a.get("unit_price"):
                unit = a.get("unit_price")
            else:
                buyout = a.get("buyout")
                unit = -(-int(buyout) // qty) if buyout else None  # round up
            if not unit or qty <= 0:
                continue
            out.append(Listing(int(a["id"]), item_id, qty, int(unit), str(a.get("time_left", ""))))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def parse_item(item_id: int, data: dict | None) -> ItemInfo:
    if data is None:
        return ItemInfo(item_id=item_id, status="missing")
    preview = data.get("preview_item") or {}
    binding = (preview.get("binding") or {}).get("type")
    sell = data.get("sell_price")
    if sell is None:
        sell = ((preview.get("sell_price") or {}).get("value"))
    return ItemInfo(
        item_id=item_id,
        name=data.get("name"),
        class_name=(data.get("item_class") or {}).get("name"),
        subclass_name=(data.get("item_subclass") or {}).get("name"),
        quality=(data.get("quality") or {}).get("name"),
        sell_price=int(sell) if sell is not None else None,
        binding=binding,
        status="ok",
    )


def load_overrides(cfg: Config) -> dict[int, ItemInfo]:
    """items_override.csv: item_id,name,class_name,sell_price,binding (any may be blank)."""
    path = cfg.item_override_csv
    if not path.is_file():
        return {}
    out = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                item_id = int(row["item_id"])
            except (KeyError, ValueError):
                continue
            sell = (row.get("sell_price") or "").strip()
            out[item_id] = ItemInfo(
                item_id=item_id,
                name=(row.get("name") or "").strip() or None,
                class_name=(row.get("class_name") or "").strip() or None,
                sell_price=int(sell) if sell else None,
                binding=(row.get("binding") or "").strip() or None,
                status="ok",
            )
    return out


def merged_items(store: Store, cfg: Config) -> dict[int, ItemInfo]:
    items = store.items()
    for item_id, over in load_overrides(cfg).items():
        base = items.get(item_id) or ItemInfo(item_id=item_id)
        items[item_id] = ItemInfo(
            item_id=item_id,
            name=over.name or base.name,
            class_name=over.class_name or base.class_name,
            subclass_name=base.subclass_name,
            quality=base.quality,
            sell_price=over.sell_price if over.sell_price is not None else base.sell_price,
            binding=over.binding or base.binding,
            status="ok",
        )
    return items


def lookup_new_items(client, store: Store, item_ids: set[int], cfg: Config, now: int) -> int:
    todo = sorted(item_ids - store.known_item_ids())[: cfg.max_new_item_lookups]
    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=cfg.item_lookup_workers) as pool:
        results = list(pool.map(lambda i: (i, client.item(i)), todo))
    for item_id, data in results:
        store.save_item(parse_item(item_id, data), now)
    return len(todo)


@dataclass
class ScanResult:
    taken_at: int
    changed: bool
    listings: int
    sales_found: int
    history_days: float
    bankroll: int
    profile: str
    flips: list[Flip] = field(default_factory=list)
    vendor: list[VendorFlip] = field(default_factory=list)
    items_looked_up: int = 0
    items_missing: int = 0
    near_misses: list[tuple[str, str]] = field(default_factory=list)


def record_snapshot(store: Store, listings: list[Listing], now: int, cfg: Config) -> tuple[bool, int]:
    """Save a snapshot if the data changed. Returns (changed, sales rows found)."""
    fp = fingerprint(listings)
    last = store.last_snapshot()
    if last and last[2] == fp:
        log.info("Auction data unchanged since %s; not recording a new hour.", time.ctime(last[1]))
        return False, 0

    sales, covered = [], 0
    if last:
        sales, covered = infer_sales(store.last_listings(), listings, now - last[1])
    snap_id = store.add_snapshot(now, fp, len(listings), covered)
    store.add_item_hourly(snap_id, summarize(listings))
    store.add_sales(snap_id, sales)
    store.replace_last_listings(listings)
    store.prune(now - int(cfg.market.keep_days * DAY))
    store.commit()
    return True, len(sales)


def score(store: Store, cfg: Config, now: int, listings: list[Listing] | None = None) -> ScanResult:
    """Score the latest listings against stored history."""
    if listings is None:
        listings = store.last_listings()
    market = cfg.market
    bankroll = cfg.bankroll_copper()
    profile = cfg.profile_for(bankroll)
    items = merged_items(store, cfg)

    since = now - int(market.history_days * DAY)
    snaps = store.snapshot_count(since)
    coverage = store.sales_coverage_secs(since)
    first = store.first_snapshot_time()

    result = ScanResult(
        taken_at=now,
        changed=True,
        listings=len(listings),
        sales_found=0,
        history_days=(now - first) / DAY if first else 0.0,
        bankroll=bankroll,
        profile=profile.name,
        items_missing=sum(1 for i in items.values() if i.status == "missing"),
    )

    misses = []
    for item_id, group in group_by_item(listings).items():
        info = items.get(item_id)
        result.vendor.extend(vendor_flips(group, info, market.min_vendor_profit, bankroll))
        history = store.item_history(item_id, since)
        if not history:
            continue
        m = build_market_stats(
            item_id, history, store.item_sales(item_id, since), now, snaps, coverage, market
        )
        if m is None:
            continue
        flip, reason = evaluate_item(m, group, info, market, profile, bankroll)
        if flip:
            result.flips.append(flip)
        elif info and info.status == "ok" and min(l.unit_price for l in group) < 0.75 * m.mv:
            misses.append((m.mv - min(l.unit_price for l in group), info.name or str(item_id), reason))

    result.flips.sort(key=lambda f: f.score, reverse=True)
    result.vendor.sort(key=lambda v: v.profit, reverse=True)
    misses.sort(reverse=True)
    result.near_misses = [(name, reason) for _, name, reason in misses[:15]]
    return result


def run_scan(client, store: Store, cfg: Config, now: int | None = None) -> ScanResult:
    now = int(now if now is not None else time.time())
    raw = client.auctions(cfg.ruleset_id, cfg.house_id)
    listings = normalize(raw, commodity=False)
    if cfg.include_commodities:
        listings += normalize(client.commodities(cfg.ruleset_id, cfg.house_id), commodity=True)
    # Guard against the same auction appearing in both feeds.
    listings = list({l.auction_id: l for l in listings}.values())
    log.info("Fetched %d listings from house %d.", len(listings), cfg.house_id)

    changed, sales = record_snapshot(store, listings, now, cfg)
    looked_up = lookup_new_items(client, store, {l.item_id for l in listings}, cfg, now)
    store.commit()
    if looked_up:
        log.info("Looked up %d new items.", looked_up)

    result = score(store, cfg, now, listings)
    result.changed = changed
    result.sales_found = sales
    result.items_looked_up = looked_up
    return result
