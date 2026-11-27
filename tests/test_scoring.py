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
        (dict(history_days=3), "history"),
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
