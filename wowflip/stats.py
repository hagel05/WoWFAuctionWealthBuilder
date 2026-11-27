"""Small statistics helpers and per-snapshot item summaries."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict

from wowflip.store import Listing


def percentile(values, q: float) -> float:
    """Linear-interpolated percentile, q in [0, 1]."""
    vals = sorted(values)
    if not vals:
        raise ValueError("percentile of empty list")
    if len(vals) == 1:
        return float(vals[0])
    pos = q * (len(vals) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def median(values) -> float:
    return percentile(values, 0.5)


def unit_percentile(listings: list[Listing], q: float) -> int:
    """Unit price at which a share q of the listed units are at or below it."""
    ordered = sorted(listings, key=lambda l: l.unit_price)
    total = sum(l.quantity for l in ordered)
    need = q * total
    running = 0
    for l in ordered:
        running += l.quantity
        if running >= need:
            return l.unit_price
    return ordered[-1].unit_price


def group_by_item(listings: list[Listing]) -> dict[int, list[Listing]]:
    out: dict[int, list[Listing]] = defaultdict(list)
    for l in listings:
        out[l.item_id].append(l)
    return out


def summarize(listings: list[Listing]):
    """Rows of (item_id, min_unit, p25_unit, units, auctions) for one snapshot."""
    rows = []
    for item_id, group in group_by_item(listings).items():
        rows.append(
            (
                item_id,
                min(l.unit_price for l in group),
                unit_percentile(group, 0.25),
                sum(l.quantity for l in group),
                len(group),
            )
        )
    return rows


def fingerprint(listings: list[Listing]) -> str:
    """Hash of the listing set, to tell whether the API returned new data."""
    h = hashlib.sha256()
    for l in sorted(listings, key=lambda l: l.auction_id):
        h.update(f"{l.auction_id}:{l.quantity}:{l.unit_price};".encode())
    return h.hexdigest()


# time_left buckets (Blizzard API): SHORT < 30m, MEDIUM 30m-2h, LONG 2h-12h, VERY_LONG 12h-48h.
def infer_sales(previous: list[Listing], current: list[Listing], gap_secs: int):
    """Guess which listings sold between two snapshots.

    The API has no sales history, so a listing that disappears while it still
    had plenty of time left is counted as sold. Cancellations also look like
    this, so the result is an upper bound. Commodity listings that shrink are
    counted as partial sales.

    Returns (rows, covered_secs): rows are (item_id, unit_price, quantity);
    covered_secs is how much time the inference speaks for (0 if the gap was
    too long to tell sales from expiries).
    """
    if gap_secs <= 2 * 3600:
        safe = {"LONG", "VERY_LONG"}
    elif gap_secs <= 12 * 3600:
        safe = {"VERY_LONG"}
    else:
        return [], 0

    now = {l.auction_id: l for l in current}
    rows = []
    for old in previous:
        new = now.get(old.auction_id)
        if new is None:
            if old.time_left in safe:
                rows.append((old.item_id, old.unit_price, old.quantity))
        elif new.quantity < old.quantity:
            rows.append((old.item_id, old.unit_price, old.quantity - new.quantity))
    # With only VERY_LONG listings trusted, we see a fraction of real sales;
    # still report the full gap so estimates stay conservative.
    return rows, gap_secs
