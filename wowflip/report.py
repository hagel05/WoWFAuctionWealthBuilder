"""Write the buy list as HTML (to open in a browser) and CSV, and log flags."""

from __future__ import annotations

import csv
import html
import time
from pathlib import Path

from wowflip.config import Config, money
from wowflip.scan import ScanResult

CSS = """
:root { color-scheme: light dark; --bg:#fff; --fg:#1d1d1f; --muted:#6b6b70; --line:#e3e3e6; --accent:#9a6b00; }
@media (prefers-color-scheme: dark) { :root { --bg:#17171a; --fg:#ececef; --muted:#a0a0a8; --line:#2e2e33; --accent:#f0b429; } }
body { background:var(--bg); color:var(--fg); font:15px/1.45 system-ui, sans-serif; margin:0 auto; max-width:1100px; padding:24px 16px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:28px 0 8px; }
.meta { color:var(--muted); margin-bottom:16px; }
.note { border-left:3px solid var(--accent); padding:6px 12px; margin:12px 0; }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; font-size:13px; }
td.num, th.num { text-align:right; white-space:nowrap; }
.wrap { overflow-x:auto; }
"""


def _buys_text(flip) -> str:
    return ", ".join(f"{b.quantity} @ {money(b.unit_price)}" for b in flip.buys)


def write_reports(result: ScanResult, cfg: Config) -> Path:
    out = cfg.report_dir
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(result.taken_at))

    # CSV of this run
    with (out / "latest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["kind", "item_id", "item", "buy_listings", "quantity", "cost_copper",
                    "relist_at_copper", "net_profit_copper", "roi", "days_to_sell", "score"])
        for f in result.flips:
            w.writerow(["flip", f.item_id, f.name, _buys_text(f), f.quantity, f.cost,
                        round(f.target), round(f.net_profit), round(f.roi, 3),
                        round(f.days_to_sell, 2), round(f.score)])
        for v in result.vendor:
            w.writerow(["vendor", v.item_id, v.name, f"{v.listings} listings up to {money(v.unit_price)}", v.quantity,
                        v.cost, v.sell_price, v.profit, round(v.profit / v.cost, 3) if v.cost else "", "", ""])

    # Running log of every flag, to tune the rules later.
    log_path = out / "flag_log.csv"
    new = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["scanned_at", "kind", "item_id", "item", "quantity", "max_buy_copper",
                        "relist_at_copper", "net_profit_copper", "profile"])
        for f in result.flips:
            w.writerow([stamp, "flip", f.item_id, f.name, f.quantity, f.max_price,
                        round(f.target), round(f.net_profit), result.profile])
        for v in result.vendor:
            w.writerow([stamp, "vendor", v.item_id, v.name, v.quantity, v.unit_price,
                        v.sell_price, v.profit, result.profile])

    (out / "latest.html").write_text(render_html(result, cfg, stamp), encoding="utf-8")
    return out / "latest.html"


def render_html(result: ScanResult, cfg: Config, stamp: str) -> str:
    e = html.escape
    notes = []
    if result.history_days < cfg.market.min_history_days:
        notes.append(
            f"Collecting price history: {result.history_days:.1f} of {cfg.market.min_history_days:.0f} days so far. "
            "Market flips appear once items have a week of history; vendor flips work from day one."
        )
    if not result.changed:
        notes.append("The auction data had not changed since the last scan, so this report reuses it.")
    if result.items_missing:
        notes.append(
            f"{result.items_missing} item ids have no details from the API, so they are skipped. "
            "Add them to items_override.csv to include them."
        )

    rows = []
    for i, f in enumerate(result.flips, 1):
        rows.append(
            "<tr>"
            f"<td class=num>{i}</td><td>{e(f.name)}</td><td>{e(_buys_text(f))}</td>"
            f"<td class=num>{money(f.cost)}</td><td class=num>{money(f.target)}</td>"
            f"<td class=num>{money(f.net_profit)}</td><td class=num>{f.roi:.0%}</td>"
            f"<td class=num>{f.days_to_sell:.1f}</td><td class=num>{money(f.score)}</td>"
            "</tr>"
        )
    flips_html = (
        "<div class=wrap><table><tr><th class=num>#</th><th>Item</th><th>Buy these listings (qty @ unit price)</th>"
        "<th class=num>Cost</th><th class=num>Relist at (each)</th><th class=num>Net profit</th>"
        "<th class=num>ROI</th><th class=num>Days to sell</th><th class=num>Score</th></tr>"
        + "".join(rows) + "</table></div>"
        if rows else "<p>No market flips pass the rules this hour.</p>"
    )

    vrows = [
        f"<tr><td>{e(v.name)}</td><td class=num>{v.quantity} ({v.listings} listings)</td><td class=num>{money(v.unit_price)}</td>"
        f"<td class=num>{money(v.sell_price)}</td><td class=num>{money(v.profit)}</td></tr>"
        for v in result.vendor[:50]
    ]
    vendor_html = (
        "<div class=wrap><table><tr><th>Item</th><th class=num>Qty</th><th class=num>Pay up to (each)</th>"
        "<th class=num>Vendor pays</th><th class=num>Profit</th></tr>" + "".join(vrows) + "</table></div>"
        if vrows else "<p>None this hour.</p>"
    )

    mrows = [f"<tr><td>{e(n)}</td><td>{e(r)}</td></tr>" for n, r in result.near_misses]
    miss_html = (
        "<details><summary>Cheap listings that were skipped, and why</summary><div class=wrap><table>"
        "<tr><th>Item</th><th>Reason</th></tr>" + "".join(mrows) + "</table></div></details>"
        if mrows else ""
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flip list</title><style>{CSS}</style></head><body>
<h1>Flip list</h1>
<div class=meta>Scanned {e(stamp)} · house {cfg.house_id} · {result.listings:,} listings ·
bankroll {money(result.bankroll)} ({e(result.profile)} profile)</div>
{''.join(f'<div class=note>{e(n)}</div>' for n in notes)}
<h2>Vendor flips (buy, then sell to any vendor)</h2>
{vendor_html}
<h2>Market flips (buy, then relist on the AH for 24 hours)</h2>
{flips_html}
{miss_html}
</body></html>
"""


def print_summary(result: ScanResult, report_path: Path) -> None:
    print(
        f"Scan done: {result.listings:,} listings, {len(result.flips)} market flips, "
        f"{len(result.vendor)} vendor flips, {result.history_days:.1f} days of history, "
        f"bankroll {money(result.bankroll)} ({result.profile})."
    )
    for f in result.flips[:10]:
        print(f"  {f.name}: buy {_buys_text(f)}, relist at {money(f.target)}, profit {money(f.net_profit)}")
    for v in result.vendor[:5]:
        print(f"  [vendor] {v.name}: {v.quantity} up to {money(v.unit_price)} each, profit {money(v.profit)}")
    print(f"Report: {report_path.resolve()}")
