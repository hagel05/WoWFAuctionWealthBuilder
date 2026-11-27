"""Flip scoring, following the "Flip scoring rules" doc.

Per unit, with B = buy price, T = resale target, c = AH cut, D = deposit per
listing, p = chance one listing sells before it expires:

    T          = (1 - undercut) * min(MV, MV3)
    discount   = 1 - B / MV
    net profit = T(1 - c) - B - D(1 - p)/p
    ROI        = net profit / B
    p          = min(0.95, daily sales * listing days / (Q + qty))
    days       = (Q + qty) / daily sales
    score      = net profit * qty * min(1, daily sales / qty) / (1 + volatility)

Q is units already listed at or below T that we are not buying.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from wowflip.config import Market, Profile
from wowflip.stats import median, percentile, unit_percentile
from wowflip.store import ItemInfo, Listing

DAY = 86_400


@dataclass
class MarketStats:
    item_id: int
    mv: float  # median hourly min buyout, history window
    mv3: float  # same, recent window
    p20: float
    p80: float
    daily_sales: float  # units/day sold at >= sales_price_floor * MV
    history_days: float  # how far back this item's history goes
    seen_share: float  # share of snapshots in the window that listed it
    typical_auctions: float  # median auctions listed per snapshot
    min_24h_ago: float | None = None
    units_24h_ago: float | None = None
    min_now: float | None = None
    units_now: float | None = None

    @property
    def volatility(self) -> float:
        return (self.p80 - self.p20) / self.mv if self.mv else float("inf")


def build_market_stats(
    item_id: int,
    history,  # [(taken_at, min_unit, p25_unit, units, auctions)]
    sales,  # [(unit_price, quantity)]
    now: int,
    snapshots_in_window: int,
    sales_coverage_secs: int,
    market: Market,
) -> MarketStats | None:
    if not history:
        return None
    mins = [h[1] for h in history]
    mv = median(mins)
    recent_cut = now - market.recent_days * DAY
    recent = [h[1] for h in history if h[0] >= recent_cut] or mins[-1:]
    mv3 = median(recent)

    floor = market.sales_price_floor * mv
    sold_units = sum(q for price, q in sales if price >= floor)
    coverage_days = sales_coverage_secs / DAY
    daily_sales = sold_units / coverage_days if coverage_days > 0 else 0.0

    # Value roughly 24h ago: the snapshot closest to now - 1 day (within 3h).
    target = now - DAY
    closest = min(history, key=lambda h: abs(h[0] - target))
    if abs(closest[0] - target) <= 3 * 3600:
        min_24h, units_24h = closest[1], closest[3]
    else:
        min_24h = units_24h = None

    last = history[-1]
    return MarketStats(
        item_id=item_id,
        mv=mv,
        mv3=mv3,
        p20=percentile(mins, 0.2),
        p80=percentile(mins, 0.8),
        daily_sales=daily_sales,
        history_days=(now - history[0][0]) / DAY,
        seen_share=len(history) / snapshots_in_window if snapshots_in_window else 0.0,
        typical_auctions=median([h[4] for h in history]),
        min_24h_ago=min_24h,
        units_24h_ago=units_24h,
        min_now=last[1],
        units_now=last[3],
    )


def target_price(m: MarketStats, market: Market) -> float:
    return (1 - market.undercut) * min(m.mv, m.mv3)


def sell_chance(daily_sales: float, listing_hours: float, ahead: float, qty: float, cap: float) -> float:
    if daily_sales <= 0:
        return 0.0
    return min(cap, daily_sales * (listing_hours / 24) / (ahead + qty))


def days_to_sell(daily_sales: float, ahead: float, qty: float) -> float:
    if daily_sales <= 0:
        return float("inf")
    return (ahead + qty) / daily_sales


def net_profit_per_unit(b: float, t: float, cut: float, deposit: float, p: float) -> float:
    if p <= 0:
        return float("-inf")
    return t * (1 - cut) - b - deposit * (1 - p) / p


def market_filters(m: MarketStats, listings: list[Listing], market: Market, profile: Profile) -> list[str]:
    """Reasons this item's market is untrustworthy (empty list = passes)."""
    reasons = []
    if m.history_days < min(market.ramp_start_days, market.min_history_days):
        reasons.append(f"only {m.history_days:.1f} days of history")
    if m.seen_share < market.min_seen_share:
        reasons.append(f"listed in only {m.seen_share:.0%} of snapshots")
    if m.daily_sales < profile.min_daily_sales:
        reasons.append(f"sells ~{m.daily_sales:.1f}/day near MV")
    if m.typical_auctions < market.min_auctions:
        reasons.append(f"typically {m.typical_auctions:.0f} auctions listed")

    window = market.price_point_window * m.mv
    near = [l for l in listings if l.unit_price <= window]
    units_near = sum(l.quantity for l in near)
    if units_near:
        by_price: dict[int, int] = {}
        for l in near:
            by_price[l.unit_price] = by_price.get(l.unit_price, 0) + l.quantity
        top = max(by_price.values()) / units_near
        if top > market.max_price_point_share:
            reasons.append(f"one price point holds {top:.0%} of units")

    if m.mv3 < market.crash_ratio * m.mv:
        reasons.append("price falling (MV3 well below MV)")
    if (
        m.min_24h_ago
        and m.units_24h_ago
        and m.min_now is not None
        and m.units_now is not None
        and m.min_now > (1 + market.reset_rise) * m.min_24h_ago
        and m.units_now < (1 - market.reset_supply_drop) * m.units_24h_ago
    ):
        reasons.append("possible market reset (price up, supply bought out)")
    if m.volatility > profile.volatility_cap:
        reasons.append(f"volatile ({m.volatility:.2f})")
    return reasons


def ramp_profile(profile: Profile, market: Market, history_days: float) -> tuple[Profile, bool]:
    """Stricter rules while an item has less than a full week of history.

    From ramp_start_days the extra strictness starts at its maximum and fades
    linearly to the normal profile at min_history_days. Returns (profile, early).
    """
    full, start = market.min_history_days, market.ramp_start_days
    if history_days >= full or full <= start:
        return profile, False
    s = min(1.0, max(0.0, (full - history_days) / (full - start)))
    return (
        replace(
            profile,
            min_discount=profile.min_discount + market.ramp_extra_discount * s,
            min_roi=profile.min_roi + market.ramp_extra_roi * s,
            min_daily_sales=profile.min_daily_sales * (1 + (market.ramp_sales_factor - 1) * s),
            max_flip_share=profile.max_flip_share * (1 - (1 - market.ramp_share_factor) * s),
        ),
        True,
    )


def item_allowed(info: ItemInfo | None, profile: Profile) -> tuple[bool, str]:
    if info is None or info.status != "ok" or not info.class_name:
        return False, "unknown item type"
    if info.binding == "ON_ACQUIRE":
        return False, "soulbound"
    if info.class_name not in profile.item_classes:
        return False, f"{info.class_name} not in scope"
    if info.class_name in ("Weapon", "Armor"):
        if not profile.allow_boe_gear or info.binding != "ON_EQUIP":
            return False, "gear not in scope"
    return True, ""


@dataclass
class Buy:
    unit_price: int
    quantity: int
    net_per_unit: float


@dataclass
class Flip:
    item_id: int
    name: str
    target: float
    mv: float
    buys: list[Buy] = field(default_factory=list)
    net_profit: float = 0.0
    cost: int = 0
    roi: float = 0.0
    days_to_sell: float = 0.0
    daily_sales: float = 0.0
    sell_chance: float = 0.0
    volatility: float = 0.0
    score: float = 0.0
    kind: str = "market"  # market | early (ramp rules) | snapshot (no history)
    reference: float = 0.0  # snapshot only: median price of the other listings

    @property
    def quantity(self) -> int:
        return sum(b.quantity for b in self.buys)

    @property
    def max_price(self) -> int:
        return max(b.unit_price for b in self.buys)


def evaluate_item(
    m: MarketStats,
    listings: list[Listing],
    info: ItemInfo | None,
    market: Market,
    profile: Profile,
    bankroll: int,
) -> tuple[Flip | None, str]:
    """Pick which of an item's listings to buy. Returns (flip or None, reason)."""
    ok, why = item_allowed(info, profile)
    if not ok:
        return None, why
    profile, early = ramp_profile(profile, market, m.history_days)
    problems = market_filters(m, listings, market, profile)
    if problems:
        return None, "; ".join(problems)

    t = target_price(m, market)
    deposit = market.deposit_rate * (info.sell_price or 0)  # per unit
    cut = market.ah_cut
    max_cost = profile.max_flip_share * bankroll
    max_units = profile.max_item_days_of_sales * m.daily_sales
    units_at_or_below_t = sum(l.quantity for l in listings if l.unit_price <= t)

    chosen: list[Listing] = []
    reason = "no listing cheap enough"
    for l in sorted(listings, key=lambda l: l.unit_price):
        if l.unit_price >= t:
            break
        trial = chosen + [l]
        qty = sum(x.quantity for x in trial)
        cost = sum(x.quantity * x.unit_price for x in trial)
        ahead = units_at_or_below_t - qty
        p = sell_chance(m.daily_sales, market.listing_hours, ahead, qty, market.max_sell_chance)
        net = net_profit_per_unit(l.unit_price, t, cut, deposit, p)
        discount = 1 - l.unit_price / m.mv
        if discount < profile.min_discount:
            reason = f"best discount {discount:.0%}"
            break
        if net < profile.min_profit_per_unit or net / l.unit_price < profile.min_roi:
            reason = "profit after fees too thin"
            break
        if days_to_sell(m.daily_sales, ahead, qty) > profile.max_days_to_sell:
            reason = "would take too long to sell"
            break
        if qty > max_units:
            reason = "more than the market absorbs"
            break
        if cost > max_cost:
            reason = "over the per-flip bankroll cap"
            break
        chosen = trial

    if not chosen:
        return None, reason

    qty = sum(x.quantity for x in chosen)
    cost = sum(x.quantity * x.unit_price for x in chosen)
    ahead = units_at_or_below_t - qty
    p = sell_chance(m.daily_sales, market.listing_hours, ahead, qty, market.max_sell_chance)
    buys = [Buy(x.unit_price, x.quantity, net_profit_per_unit(x.unit_price, t, cut, deposit, p)) for x in chosen]
    total = sum(b.net_per_unit * b.quantity for b in buys)
    if total < profile.min_profit_per_flip:
        return None, "whole flip under the profit floor"

    flip = Flip(
        item_id=m.item_id,
        name=(info.name if info and info.name else f"item {m.item_id}"),
        target=t,
        mv=m.mv,
        buys=buys,
        net_profit=total,
        cost=cost,
        roi=total / cost,
        days_to_sell=days_to_sell(m.daily_sales, ahead, qty),
        daily_sales=m.daily_sales,
        sell_chance=p,
        volatility=m.volatility,
        score=total * min(1.0, m.daily_sales / qty) / (1 + m.volatility),
        kind="early" if early else "market",
    )
    return flip, ""


def evaluate_snapshot(
    listings: list[Listing],
    info: ItemInfo | None,
    market: Market,
    profile: Profile,
    bankroll: int,
) -> tuple[Flip | None, str]:
    """Judge an item from the current listings alone (no price history).

    Buys the cheapest listings while each is at least snapshot_min_discount
    below the median unit price of the listings left after buying, and relists
    just under the cheaper of that median and the next listing up. Sales speed
    is unknown, so the bankroll share is smaller, the ROI floor higher, and the
    deposit is charged as if half of relists fail.
    """
    if not market.snapshot_flips:
        return None, "snapshot flips are off"
    ok, why = item_allowed(info, profile)
    if not ok:
        return None, why
    ordered = sorted(listings, key=lambda l: l.unit_price)
    deposit = market.deposit_rate * (info.sell_price or 0)
    p = market.snapshot_sell_chance
    cut = market.ah_cut
    max_cost = market.snapshot_flip_share * bankroll
    total_units = sum(l.quantity for l in ordered)

    def target_for(rest: list[Listing]) -> tuple[float, float]:
        ref = unit_percentile(rest, 0.5)
        return (1 - market.undercut) * min(ref, rest[0].unit_price), ref

    def concentrated(rest: list[Listing], ref: float) -> bool:
        window = [l for l in rest if l.unit_price <= market.price_point_window * ref]
        units = sum(l.quantity for l in window)
        by_price: dict[int, int] = {}
        for l in window:
            by_price[l.unit_price] = by_price.get(l.unit_price, 0) + l.quantity
        return bool(units) and max(by_price.values()) / units > market.max_price_point_share

    count = 0
    reason = "no listing far enough under the rest"
    for i, l in enumerate(ordered):
        rest = ordered[i + 1 :]
        if len(rest) < market.snapshot_min_auctions:
            reason = f"only {len(ordered)} listings"
            break
        t, ref = target_for(rest)
        qty = sum(x.quantity for x in ordered[: i + 1])
        cost = sum(x.quantity * x.unit_price for x in ordered[: i + 1])
        net = net_profit_per_unit(l.unit_price, t, cut, deposit, p)
        if 1 - l.unit_price / ref < market.snapshot_min_discount:
            reason = f"cheapest is only {1 - l.unit_price / ref:.0%} under the rest"
            break
        if net < profile.min_profit_per_unit or net / l.unit_price < market.snapshot_min_roi:
            reason = "profit after fees too thin"
            break
        if concentrated(rest, ref):
            reason = "the rest is mostly one price point"
            break
        if qty > market.snapshot_max_unit_share * total_units:
            reason = "would buy too much of the supply"
            break
        if cost > max_cost:
            reason = "over the per-flip bankroll cap"
            break
        count = i + 1

    if not count:
        return None, reason

    chosen, rest = ordered[:count], ordered[count:]
    t, ref = target_for(rest)
    buys = [Buy(x.unit_price, x.quantity, net_profit_per_unit(x.unit_price, t, cut, deposit, p)) for x in chosen]
    qty = sum(b.quantity for b in buys)
    cost = sum(b.unit_price * b.quantity for b in buys)
    total = sum(b.net_per_unit * b.quantity for b in buys)
    if total < profile.min_profit_per_flip:
        return None, "whole flip under the profit floor"
    return (
        Flip(
            item_id=info.item_id,
            name=info.name or f"item {info.item_id}",
            target=t,
            mv=ref,
            buys=buys,
            net_profit=total,
            cost=cost,
            roi=total / cost,
            days_to_sell=float("nan"),
            sell_chance=p,
            score=total,
            kind="snapshot",
            reference=ref,
        ),
        "",
    )


@dataclass
class VendorFlip:
    """All listings of one item priced below what a vendor pays for it."""

    item_id: int
    name: str
    unit_price: int  # highest price paid per unit among the listings to buy
    quantity: int
    sell_price: int
    cost: int
    listings: int = 1

    @property
    def profit(self) -> int:
        return self.sell_price * self.quantity - self.cost


def vendor_flips(
    listings: list[Listing], info: ItemInfo | None, min_profit: int = 0, budget: int | None = None
) -> list[VendorFlip]:
    """Buy listings below vendor price (cheapest first, within budget), sell to a vendor.

    No AH fees apply. Returns at most one entry per item, and none if the
    total profit is under min_profit.
    """
    if info is None or not info.sell_price:
        return []
    qty = cost = count = top = 0
    for l in sorted(listings, key=lambda l: l.unit_price):
        if l.unit_price >= info.sell_price:
            break
        if budget is not None and cost + l.unit_price * l.quantity > budget:
            break
        qty += l.quantity
        cost += l.unit_price * l.quantity
        count += 1
        top = l.unit_price
    if not qty:
        return []
    flip = VendorFlip(info.item_id, info.name or f"item {info.item_id}", top, qty, info.sell_price, cost, count)
    return [flip] if flip.profit >= min_profit else []
