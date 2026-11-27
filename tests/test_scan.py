"""End to end: simulated hourly snapshots through the scanner with a fake API."""

import random

from wowflip.config import Config, GOLD
from wowflip.scan import normalize, run_scan
from wowflip.stats import infer_sales
from wowflip.store import Listing, Store

HOUR = 3600
HERB, ORE, SWORD, JUNK = 2447, 2770, 1234, 999


class FakeClient:
    """Serves a small market where each hour a few herbs and ore sell and get relisted."""

    def __init__(self, seed=1):
        self.rng = random.Random(seed)
        self.next_id = 1
        self.auctions_now = []
        self.items = {
            HERB: {"name": "Peacebloom", "item_class": {"name": "Trade Goods"}, "sell_price": 20,
                   "preview_item": {"binding": None}},
            ORE: {"name": "Copper Ore", "item_class": {"name": "Trade Goods"}, "sell_price": 50},
            SWORD: {"name": "Shiny Sword", "item_class": {"name": "Weapon"}, "sell_price": 5000,
                    "preview_item": {"binding": {"type": "ON_EQUIP"}}},
        }
        for _ in range(12):
            self._list(HERB, 1, self._herb_price())
            self._list(ORE, 5, None)

    def _herb_price(self):
        return self.rng.randint(1_900, 2_100) * 10  # around 2g... per unit in copper/10

    def _list(self, item, qty, unit, time_left="VERY_LONG"):
        unit = unit if unit is not None else self.rng.randint(450, 550)
        self.auctions_now.append({"id": self.next_id, "item": {"id": item}, "quantity": qty,
                                  "buyout": unit * qty, "time_left": time_left})
        self.next_id += 1

    def tick(self, deal=False):
        # Cheapest 1/4 of herb listings sell each hour, and get replaced.
        herbs = sorted([a for a in self.auctions_now if a["item"]["id"] == HERB], key=lambda a: a["buyout"])
        for a in herbs[:3]:
            self.auctions_now.remove(a)
            self._list(HERB, 1, self._herb_price())
        ore = [a for a in self.auctions_now if a["item"]["id"] == ORE]
        self.auctions_now.remove(ore[0])
        self._list(ORE, 5, None)
        if deal:
            self._list(HERB, 2, 12_000)  # 1.20g each, about 40% under market
            self._list(JUNK, 20, 5)  # below its vendor price (19s profit)
            self._list(JUNK, 1, 99)  # also below, but worth only 1c

    # API surface used by the scanner
    def auctions(self, ruleset, house):
        return [dict(a) for a in self.auctions_now]

    def commodities(self, ruleset, house):
        return []

    def item(self, item_id):
        if item_id == JUNK:
            return {"name": "Junk", "item_class": {"name": "Miscellaneous"}, "sell_price": 100}
        return self.items.get(item_id)


def test_normalize_skips_bid_only_and_rounds_up():
    raw = [
        {"id": 1, "item": {"id": 5}, "quantity": 3, "buyout": 10, "time_left": "LONG"},
        {"id": 2, "item": {"id": 5}, "quantity": 1, "bid": 50, "time_left": "LONG"},
        {"id": 3, "item": {"id": 6}, "quantity": 20, "unit_price": 7, "time_left": "SHORT"},
    ]
    out = normalize(raw[:2], commodity=False) + normalize(raw[2:], commodity=True)
    assert [(l.auction_id, l.unit_price) for l in out] == [(1, 4), (3, 7)]


def test_infer_sales():
    prev = [Listing(1, 5, 1, 100, "VERY_LONG"), Listing(2, 5, 1, 100, "SHORT"), Listing(3, 6, 10, 9, "LONG")]
    cur = [Listing(3, 6, 4, 9, "LONG")]
    rows, covered = infer_sales(prev, cur, HOUR)
    assert sorted(rows) == [(5, 100, 1), (6, 9, 6)]
    assert covered == HOUR
    assert infer_sales(prev, cur, 20 * HOUR) == ([], 0)


def test_end_to_end(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", report_dir=tmp_path / "reports",
                 item_override_csv=tmp_path / "none.csv", bankroll_gold=30)
    store = Store(cfg.db_path)
    client = FakeClient()
    t0 = 1_800_000_000
    hours = 8 * 24
    for h in range(hours):
        client.tick()
        result = run_scan(client, store, cfg, now=t0 + h * HOUR)
    assert result.history_days > 7
    assert result.flips == []  # fair market, nothing to flip

    # An unchanged hour is not recorded twice.
    again = run_scan(client, store, cfg, now=t0 + hours * HOUR)
    assert again.changed is False

    client.tick(deal=True)
    result = run_scan(client, store, cfg, now=t0 + (hours + 1) * HOUR)
    names = [f.name for f in result.flips]
    assert names == ["Peacebloom"], result.near_misses
    flip = result.flips[0]
    assert flip.quantity == 2 and flip.max_price == 12_000
    assert flip.cost <= 0.15 * 30 * GOLD
    assert [v.name for v in result.vendor] == ["Junk"]

    from wowflip.report import write_reports
    path = write_reports(result, cfg)
    text = path.read_text()
    assert "Peacebloom" in text and "Junk" in text
    store.close()


def test_snapshot_flips_on_the_first_scan(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", report_dir=tmp_path / "reports",
                 item_override_csv=tmp_path / "none.csv", bankroll_gold=30)
    store = Store(cfg.db_path)
    client = FakeClient()
    client.tick(deal=True)
    result = run_scan(client, store, cfg, now=1_800_000_000)
    assert result.flips == []  # no history yet
    assert [f.name for f in result.snapshots] == ["Peacebloom"]
    assert result.snapshots[0].quantity == 2 and result.snapshots[0].kind == "snapshot"

    from wowflip.report import write_reports
    assert "Snapshot flips" in write_reports(result, cfg).read_text()
    store.close()
