"""SQLite storage for hourly snapshots, inferred sales and item info."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    taken_at INTEGER NOT NULL,          -- unix seconds
    fingerprint TEXT NOT NULL,
    listings INTEGER NOT NULL,
    sales_window_secs INTEGER NOT NULL  -- time covered by sales inference (0 if none)
);
CREATE INDEX IF NOT EXISTS snapshots_taken ON snapshots(taken_at);

CREATE TABLE IF NOT EXISTS item_hourly (
    snapshot_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    min_unit INTEGER NOT NULL,
    p25_unit INTEGER NOT NULL,
    units INTEGER NOT NULL,
    auctions INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, item_id)
);
CREATE INDEX IF NOT EXISTS item_hourly_item ON item_hourly(item_id, snapshot_id);

CREATE TABLE IF NOT EXISTS sales (
    snapshot_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    unit_price INTEGER NOT NULL,
    quantity INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sales_item ON sales(item_id, snapshot_id);

-- The most recent snapshot's listings, used to infer sales next hour and to
-- rebuild the report without calling the API.
CREATE TABLE IF NOT EXISTS last_listings (
    auction_id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price INTEGER NOT NULL,
    time_left TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    item_id INTEGER PRIMARY KEY,
    name TEXT,
    class_name TEXT,
    subclass_name TEXT,
    quality TEXT,
    sell_price INTEGER,
    binding TEXT,
    status TEXT NOT NULL,   -- ok | missing (API 404)
    fetched_at INTEGER NOT NULL
);
"""


@dataclass
class Listing:
    auction_id: int
    item_id: int
    quantity: int
    unit_price: int  # copper per unit (buyout / quantity for item auctions)
    time_left: str


@dataclass
class ItemInfo:
    item_id: int
    name: str | None = None
    class_name: str | None = None
    subclass_name: str | None = None
    quality: str | None = None
    sell_price: int | None = None
    binding: str | None = None
    status: str = "ok"


class Store:
    def __init__(self, path: Path | str):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # -- snapshots ----------------------------------------------------------
    def last_snapshot(self):
        return self.db.execute(
            "SELECT id, taken_at, fingerprint FROM snapshots ORDER BY taken_at DESC LIMIT 1"
        ).fetchone()

    def add_snapshot(self, taken_at: int, fingerprint: str, listings: int, sales_window_secs: int) -> int:
        cur = self.db.execute(
            "INSERT INTO snapshots(taken_at, fingerprint, listings, sales_window_secs) VALUES (?,?,?,?)",
            (taken_at, fingerprint, listings, sales_window_secs),
        )
        return int(cur.lastrowid)

    def snapshot_count(self, since: int) -> int:
        return self.db.execute("SELECT COUNT(*) FROM snapshots WHERE taken_at >= ?", (since,)).fetchone()[0]

    def sales_coverage_secs(self, since: int) -> int:
        return self.db.execute(
            "SELECT COALESCE(SUM(sales_window_secs),0) FROM snapshots WHERE taken_at >= ?", (since,)
        ).fetchone()[0]

    def first_snapshot_time(self) -> int | None:
        row = self.db.execute("SELECT MIN(taken_at) FROM snapshots").fetchone()
        return row[0]

    def add_item_hourly(self, snapshot_id: int, rows) -> None:
        self.db.executemany(
            "INSERT INTO item_hourly(snapshot_id,item_id,min_unit,p25_unit,units,auctions) VALUES (?,?,?,?,?,?)",
            [(snapshot_id, *r) for r in rows],
        )

    def add_sales(self, snapshot_id: int, rows) -> None:
        self.db.executemany(
            "INSERT INTO sales(snapshot_id,item_id,unit_price,quantity) VALUES (?,?,?,?)",
            [(snapshot_id, *r) for r in rows],
        )

    def item_history(self, item_id: int, since: int):
        """[(taken_at, min_unit, p25_unit, units, auctions)] oldest first."""
        return self.db.execute(
            """SELECT s.taken_at, h.min_unit, h.p25_unit, h.units, h.auctions
               FROM item_hourly h JOIN snapshots s ON s.id = h.snapshot_id
               WHERE h.item_id = ? AND s.taken_at >= ? ORDER BY s.taken_at""",
            (item_id, since),
        ).fetchall()

    def item_sales(self, item_id: int, since: int):
        """[(unit_price, quantity)]"""
        return self.db.execute(
            """SELECT x.unit_price, x.quantity FROM sales x JOIN snapshots s ON s.id = x.snapshot_id
               WHERE x.item_id = ? AND s.taken_at >= ?""",
            (item_id, since),
        ).fetchall()

    def prune(self, before: int) -> None:
        old = "SELECT id FROM snapshots WHERE taken_at < ?"
        self.db.execute(f"DELETE FROM item_hourly WHERE snapshot_id IN ({old})", (before,))
        self.db.execute(f"DELETE FROM sales WHERE snapshot_id IN ({old})", (before,))
        self.db.execute("DELETE FROM snapshots WHERE taken_at < ?", (before,))

    # -- listings -----------------------------------------------------------
    def last_listings(self) -> list[Listing]:
        return [
            Listing(*row)
            for row in self.db.execute(
                "SELECT auction_id,item_id,quantity,unit_price,time_left FROM last_listings"
            )
        ]

    def replace_last_listings(self, listings: list[Listing]) -> None:
        self.db.execute("DELETE FROM last_listings")
        self.db.executemany(
            "INSERT OR REPLACE INTO last_listings VALUES (?,?,?,?,?)",
            [(l.auction_id, l.item_id, l.quantity, l.unit_price, l.time_left) for l in listings],
        )

    # -- items --------------------------------------------------------------
    def known_item_ids(self) -> set[int]:
        return {r[0] for r in self.db.execute("SELECT item_id FROM items")}

    def save_item(self, info: ItemInfo, fetched_at: int) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?,?)",
            (
                info.item_id, info.name, info.class_name, info.subclass_name, info.quality,
                info.sell_price, info.binding, info.status, fetched_at,
            ),
        )

    def items(self) -> dict[int, ItemInfo]:
        out = {}
        for row in self.db.execute(
            "SELECT item_id,name,class_name,subclass_name,quality,sell_price,binding,status FROM items"
        ):
            out[row[0]] = ItemInfo(*row)
        return out

    def commit(self) -> None:
        self.db.commit()
