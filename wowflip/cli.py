"""Command line: `wowflip scan`, `scan --loop`, `serve`, `sync`, `check`, `bankroll 42.5`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

from wowflip.api import ApiError, BlizzardClient
from wowflip.config import Config, load_config, money
from wowflip.feed import build_feed, feed_path, write_json_atomic
from wowflip.report import print_summary, write_reports
from wowflip.scan import parse_item, run_scan, score
from wowflip.store import Store

log = logging.getLogger("wowflip")


def setup_logging(cfg: Config) -> None:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger("wowflip")
    root.setLevel(logging.INFO)
    if not root.handlers:
        for handler in (logging.StreamHandler(sys.stderr), logging.FileHandler(cfg.data_dir / "scan.log", encoding="utf-8")):
            handler.setFormatter(fmt)
            root.addHandler(handler)


def client_for(cfg: Config) -> BlizzardClient:
    return BlizzardClient(cfg.client_id, cfg.client_secret, cfg.region)


def local_game(cfg: Config):
    """The WoW folder on this PC, when the scanner and the game share a PC."""
    if not cfg.addon.wow_dir or cfg.addon.sync_url:
        return None
    from wowflip.sync import wow_install

    try:
        return wow_install(cfg)
    except FileNotFoundError as exc:
        log.warning("Addon sync skipped: %s", exc)
        return None


def scan_once(cfg: Config) -> int:
    game = local_game(cfg)
    if game:
        from wowflip.bankroll import apply_game_bankroll

        apply_game_bankroll(cfg, game.read_characters())
    store = Store(cfg.db_path)
    try:
        result = run_scan(client_for(cfg), store, cfg)
    except ApiError as exc:
        log.error("%s", exc)
        return 2
    finally:
        store.close()
    path = write_reports(result, cfg)
    feed = build_feed(result, cfg)
    write_json_atomic(feed_path(cfg), feed)
    if game:
        game.write_feed(feed)
        log.info("Updated the WoWFlipData addon. /reload in game to see the new list.")
    print_summary(result, path)
    return 0


def scan_loop(config_path, now: bool) -> None:
    cfg = load_config(config_path)
    log.info("Loop mode: scanning at minute %02d of every hour. Ctrl+C to stop.", cfg.scan_minute)
    if now:
        try:
            scan_once(cfg)
        except Exception:
            log.exception("Scan failed; will try again next hour.")
    while True:
        wait = seconds_until_minute(cfg.scan_minute)
        log.info("Next scan in %d minutes.", round(wait / 60))
        time.sleep(wait)
        cfg = load_config(config_path)  # pick up config edits between runs
        try:
            scan_once(cfg)
        except Exception:  # keep the loop alive through one bad hour
            log.exception("Scan failed; will try again next hour.")


def seconds_until_minute(minute: int, now: float | None = None) -> float:
    now = time.time() if now is None else now
    t = time.localtime(now)
    wait = (minute - t.tm_min) * 60 - t.tm_sec
    if wait <= 0:
        wait += 3600
    return wait


def cmd_scan(cfg: Config, args) -> int:
    if not args.loop:
        return scan_once(cfg)
    scan_loop(args.config, args.now)
    return 0


def cmd_serve(cfg: Config, args) -> int:
    from wowflip.server import serve

    if args.with_scanner:
        threading.Thread(target=scan_loop, args=(args.config, True), daemon=True, name="scanner").start()
    serve(cfg)
    return 0


def cmd_sync(cfg: Config, args) -> int:
    from wowflip.sync import SyncError, sync_loop, sync_once

    if args.loop:
        sync_loop(cfg)
        return 0
    try:
        wrote = sync_once(cfg, force=args.force)
    except (SyncError, FileNotFoundError, ValueError) as exc:
        log.error("Sync failed: %s", exc)
        return 2
    if not wrote:
        print("The addon already has the latest scan.")
    return 0


def cmd_report(cfg: Config, args) -> int:
    store = Store(cfg.db_path)
    try:
        last = store.last_snapshot()
        if not last:
            print("No scans stored yet. Run `wowflip scan` first.")
            return 1
        result = score(store, cfg, int(time.time()))
        result.changed = True
    finally:
        store.close()
    write_json_atomic(feed_path(cfg), build_feed(result, cfg))
    print_summary(result, write_reports(result, cfg))
    return 0


def cmd_bankroll(cfg: Config, args) -> int:
    if args.gold is None:
        print(f"Bankroll: {money(cfg.bankroll_copper())} ({cfg.profile_for(cfg.bankroll_copper()).name} profile)")
        return 0
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.bankroll_file.write_text(json.dumps({"gold": args.gold, "set_at": int(time.time())}))
    print(f"Bankroll set to {args.gold:g}g. Next scan uses the {cfg.profile_for(cfg.bankroll_copper()).name} profile.")
    return 0


def cmd_check(cfg: Config, args) -> int:
    """Check credentials and the undocumented Forever endpoints."""
    try:
        client = client_for(cfg)
        print("Getting an API token... ", end="", flush=True)
        client._bearer()
        print("ok")
        print(f"Rulesets: {json.dumps(client.rulesets())[:300]}")
        houses = client.houses(cfg.ruleset_id)
        print(f"Houses for ruleset {cfg.ruleset_id}: {json.dumps(houses)[:600]}")
        auctions = client.auctions(cfg.ruleset_id, cfg.house_id)
        print(f"House {cfg.house_id}: {len(auctions):,} item auctions")
        if cfg.include_commodities:
            print(f"House {cfg.house_id} commodities: {len(client.commodities(cfg.ruleset_id, cfg.house_id)):,}")
        if auctions:
            item_id = auctions[0]["item"]["id"]
            info = parse_item(item_id, client.item(item_id))
            print(f"Sample item {item_id}: {info}")
            print("sell_price present:", info.sell_price is not None)
    except ApiError as exc:
        print(f"\nFailed: {exc}")
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wowflip", description="WoW Forever Auction House flip scanner")
    parser.add_argument("--config", default=os.environ.get("WOWFLIP_CONFIG", "config.toml"),
                        help="path to config.toml (default: ./config.toml)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="fetch the auction house and write the flip list")
    p.add_argument("--loop", action="store_true", help="keep running, scanning once an hour")
    p.add_argument("--now", action="store_true", help="with --loop, also scan immediately")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("serve", help="run the API that sync helpers on other PCs read from")
    p.add_argument("--with-scanner", action="store_true", help="also scan every hour (one process for Docker)")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("sync", help="copy the latest flip list into the WoWFlip addon on this PC")
    p.add_argument("--loop", action="store_true", help="keep running, checking every few minutes")
    p.add_argument("--force", action="store_true", help="rewrite the addon data even if unchanged")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("report", help="rebuild the flip list from stored data (no API calls)")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("bankroll", help="show or set your current gold, e.g. `wowflip bankroll 42.5`")
    p.add_argument("gold", type=float, nargs="?")
    p.set_defaults(func=cmd_bankroll)

    p = sub.add_parser("check", help="test API credentials and endpoints")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    cfg = load_config(Path(args.config))
    setup_logging(cfg)
    try:
        return args.func(cfg, args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
