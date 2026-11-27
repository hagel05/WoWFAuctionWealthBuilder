"""Checks against the worked example in the Flip scoring rules doc."""

import pytest

from wowflip.config import CAREFUL, GOLD, SILVER, Market, money
from wowflip.scoring import MarketStats, evaluate_item, net_profit_per_unit, sell_chance, target_price
from wowflip.store import ItemInfo, Listing

HERB = ItemInfo(item_id=1, name="Test Herb", class_name="Trade Goods", sell_price=2 * SILVER)


def herb_market(**kw):
    base = dict(
        item_id=1, mv=2.00 * GOLD, mv3=1.92 * GOLD, p20=1.70 * GOLD, p80=2.30 * GOLD,
        daily_sales=12, history_days=14, seen_share=1.0, typical_auctions=9,
    )
    base.update(kw)
    return MarketStats(**base)


def herb_listings(extra=()):
    # 3 units at 1.20g (the deal) plus 8 more units at or below the target, spread over prices.
    ls = [Listing(100, 1, 3, 12_000, "VERY_LONG")]
    prices = [17_000, 17_500, 18_000, 18_200, 18_400, 18_500, 18_600, 18_620]
    ls += [Listing(200 + i, 1, 1, p, "LONG") for i, p in enumerate(prices)]
    ls += [Listing(300, 1, 2, 21_000, "LONG")]
    return ls + list(extra)


def test_worked_example_numbers():
    market = Market()
    m = herb_market()
    t = target_price(m, market)
    assert t == pytest.approx(18_624)
    p = sell_chance(12, 24, ahead=8, qty=3, cap=0.95)
    assert p == pytest.approx(0.95)
    net = net_profit_per_unit(12_000, t, 0.05, 0.6 * 200, p)
    assert net / GOLD == pytest.approx(0.57, abs=0.005)


def test_worked_example_flip():
    flip, reason = evaluate_item(herb_market(), herb_listings(), HERB, Market(), CAREFUL, 30 * GOLD)
    assert flip is not None, reason
    assert flip.quantity == 3
    assert flip.cost == 36_000
    assert flip.net_profit / GOLD == pytest.approx(1.71, abs=0.01)
    assert flip.days_to_sell == pytest.approx(11 / 12)
    assert flip.score / GOLD == pytest.approx(1.31, abs=0.01)


def test_second_listing_at_156_fails_discount():
    listings = [Listing(1, 1, 1, 15_600, "LONG")] + herb_listings()[1:]
    flip, reason = evaluate_item(herb_market(), listings, HERB, Market(), CAREFUL, 30 * GOLD)
    assert flip is None
    assert "discount" in reason


def test_bankroll_cap_blocks_big_flip():
    flip, reason = evaluate_item(herb_market(), herb_listings(), HERB, Market(), CAREFUL, 10 * GOLD)
    assert flip is None and "bankroll" in reason


@pytest.mark.parametrize(
    "change, expect",
    [
        (dict(history_days=1.5), "history"),
        (dict(daily_sales=2), "sells"),
        (dict(mv3=1.5 * GOLD), "falling"),
        (dict(p20=1.0 * GOLD, p80=2.5 * GOLD), "volatile"),
        (dict(typical_auctions=2), "auctions"),
    ],
)
def test_market_filters(change, expect):
    flip, reason = evaluate_item(herb_market(**change), herb_listings(), HERB, Market(), CAREFUL, 30 * GOLD)
    assert flip is None and expect in reason


def test_price_point_concentration():
    wall = [Listing(900, 1, 40, 19_000, "LONG")]
    flip, reason = evaluate_item(herb_market(), herb_listings(wall), HERB, Market(), CAREFUL, 30 * GOLD)
    assert flip is None and "price point" in reason


def test_gear_out_of_scope_for_careful():
    gear = ItemInfo(item_id=1, name="Sword", class_name="Weapon", binding="ON_EQUIP", sell_price=100)
    flip, reason = evaluate_item(herb_market(), herb_listings(), gear, Market(), CAREFUL, 30 * GOLD)
    assert flip is None and "scope" in reason


def test_money_format():
    assert money(18_624) == "1g 86s 24c"
    assert money(57) == "57c"
    assert money(1_000) == "10s 0c"


def test_vendor_flips_grouped_with_floor_and_budget():
    from wowflip.scoring import vendor_flips

    info = ItemInfo(item_id=7, name="Oil", class_name="Trade Goods", sell_price=100)
    ls = [Listing(1, 7, 10, 50, "LONG"), Listing(2, 7, 10, 60, "LONG"), Listing(3, 7, 5, 120, "LONG")]
    [v] = vendor_flips(ls, info, min_profit=0)
    assert (v.quantity, v.cost, v.unit_price, v.listings, v.profit) == (20, 1100, 60, 2, 900)
    assert vendor_flips(ls, info, min_profit=1000) == []
    [v] = vendor_flips(ls, info, min_profit=0, budget=700)
    assert v.quantity == 10


def test_ramp_is_stricter_early_and_relaxes():
    from wowflip.scoring import ramp_profile

    m = Market()
    p2, early2 = ramp_profile(CAREFUL, m, 2)
    assert early2 and p2.min_discount == pytest.approx(0.45) and p2.max_flip_share == pytest.approx(0.075)
    assert p2.min_daily_sales == pytest.approx(10)
    p7, early7 = ramp_profile(CAREFUL, m, 7)
    assert not early7 and p7 == CAREFUL
    # Day 3: the 40% deal is not cheap enough yet. Day 6: it passes, marked early.
    flip, reason = evaluate_item(herb_market(history_days=3), herb_listings(), HERB, Market(), CAREFUL, 30 * GOLD)
    assert flip is None and "discount" in reason
    flip, reason = evaluate_item(herb_market(history_days=6), herb_listings(), HERB, Market(), CAREFUL, 30 * GOLD)
    assert flip is not None and flip.kind == "early", reason
    flip, _ = evaluate_item(herb_market(), herb_listings(), HERB, Market(), CAREFUL, 30 * GOLD)
    assert flip.kind == "market"


def deep_market(cheap):
    """10 listings of 1 unit around 2g, plus the given cheap listings."""
    rest = [Listing(500 + i, 1, 1, 20_000 + 100 * i, "LONG") for i in range(10)]
    return list(cheap) + rest


def test_snapshot_flip_from_one_scan():
    from wowflip.scoring import evaluate_snapshot

    flip, reason = evaluate_snapshot(deep_market([Listing(1, 1, 2, 11_000, "LONG")]), HERB, Market(), CAREFUL, 30 * GOLD)
    assert flip is not None, reason
    assert flip.kind == "snapshot" and flip.quantity == 2
    assert flip.reference == 20_400  # median of the other listings
    # LIFO: matching the next listing (2g) would be enough, but 3% under the median is lower.
    assert flip.target == pytest.approx(min(0.97 * 20_400, 20_000))
    from dataclasses import replace as dc_replace
    fifo = dc_replace(Market(), newest_first_at_same_price=False)
    flip2, _ = evaluate_snapshot(deep_market([Listing(1, 1, 2, 11_000, "LONG")]), HERB, fifo, CAREFUL, 30 * GOLD)
    assert flip2.target == pytest.approx(0.97 * 20_000)  # oldest-first: undercut the next listing
    assert flip.cost <= 0.10 * 30 * GOLD


@pytest.mark.parametrize(
    "listings, expect",
    [
        (deep_market([Listing(1, 1, 1, 16_000, "LONG")]), "under the rest"),  # only 22% off
        ([Listing(1, 1, 1, 10_000, "LONG")] + deep_market([])[:5], "listings"),  # thin market
        (deep_market([Listing(1, 1, 3, 11_000, "LONG")]) + [Listing(99, 1, 40, 20_000, "LONG")], "price point"),
        (deep_market([Listing(1, 1, 4, 11_000, "LONG")]), "supply"),  # 4 of 14 units
    ],
)
def test_snapshot_rejections(listings, expect):
    from wowflip.scoring import evaluate_snapshot

    flip, reason = evaluate_snapshot(listings, HERB, Market(), CAREFUL, 30 * GOLD)
    assert flip is None and expect in reason


def test_lifo_listings_at_target_price_are_not_ahead():
    from dataclasses import replace as dc_replace

    # 6 units sit exactly at the target price (1.8624g). Under LIFO a fresh relist sells before them.
    wall = [Listing(800 + i, 1, 1, 18_624, "LONG") for i in range(6)]
    lifo, _ = evaluate_item(herb_market(), herb_listings(wall), HERB, Market(), CAREFUL, 30 * GOLD)
    fifo_market = dc_replace(Market(), newest_first_at_same_price=False)
    fifo, _ = evaluate_item(herb_market(), herb_listings(wall), HERB, fifo_market, CAREFUL, 30 * GOLD)
    assert lifo.days_to_sell == pytest.approx(11 / 12)
    assert fifo.days_to_sell == pytest.approx(17 / 12)
