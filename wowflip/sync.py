"""Sync helper: keep the WoWFlipData addon on this PC up to date.

It gets the latest flip feed, either from the scanner's API on another machine
([addon] sync_url, e.g. your TrueNAS box) or from this PC's own scanner output,
writes it into the game's AddOns folder, and passes the gold the addon saw back
as the bankroll.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from wowflip.addon_sync import WowInstall
from wowflip.bankroll import apply_game_bankroll
from wowflip.config import Config
from wowflip.feed import feed_path, load_feed

log = logging.getLogger("wowflip")


class SyncError(RuntimeError):
    pass


def _request(cfg: Config, path: str, body: dict | None = None):
    url = cfg.addon.sync_url.rstrip("/") + path
    headers = {"Accept": "application/json", "User-Agent": "wowflip-sync"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if cfg.api_token:
        headers["Authorization"] = f"Bearer {cfg.api_token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SyncError(f"{url} answered {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SyncError(f"could not reach {url}: {exc}") from exc


def fetch_feed(cfg: Config) -> dict:
    if cfg.addon.sync_url:
        feed = _request(cfg, "/api/v1/feed")
        if not isinstance(feed, dict) or "flips" not in feed:
            raise SyncError("the server sent something that is not a flip feed")
        return feed
    path = feed_path(cfg)
    if not path.is_file():
        raise SyncError(f"no scan output at {path} yet; run `wowflip scan` first")
    return load_feed(path)


def push_bankroll(cfg: Config, chars: dict) -> None:
    """Send the gold seen in game to wherever the scanner runs."""
    if not chars or not cfg.addon.bankroll_from_game:
        return
    if cfg.addon.sync_url:
        reply = _request(cfg, "/api/v1/bankroll", {"characters": chars})
        if reply.get("updated"):
            log.info("Sent bankroll %sg to the server.", reply.get("bankroll_gold"))
    else:
        apply_game_bankroll(cfg, chars)


def wow_install(cfg: Config) -> WowInstall:
    if not cfg.addon.wow_dir:
        raise SyncError("set [addon] wow_dir in config.toml to your World of Warcraft folder")
    return WowInstall(cfg.addon.wow_dir, cfg.addon.game_folder)


def sync_once(cfg: Config, force: bool = False) -> bool:
    """One pass. Returns True if new data was written for the game."""
    wow = wow_install(cfg)
    try:
        push_bankroll(cfg, wow.read_characters())
    except SyncError as exc:
        log.warning("Bankroll not sent: %s", exc)
    feed = fetch_feed(cfg)
    if not force and wow.written_generated_at() == int(feed.get("generated_at", 0)):
        return False
    path = wow.write_feed(feed)
    log.info(
        "Wrote %d flips and %d vendor flips to %s. /reload in game to see them.",
        len(feed.get("flips", [])), len(feed.get("vendor", [])), path,
    )
    if not wow.main_addon_installed():
        log.warning("The WoWFlip addon is not in %s yet; see the README to install it.", wow.addons_dir)
    return True


def sync_loop(cfg: Config) -> None:
    minutes = max(1.0, float(cfg.addon.sync_minutes))
    log.info("Sync helper running: checking every %g minutes. Ctrl+C to stop.", minutes)
    while True:
        try:
            sync_once(cfg)
        except (SyncError, FileNotFoundError, ValueError) as exc:
            log.error("Sync failed: %s", exc)
        except Exception:  # keep the helper alive through one bad pass
            log.exception("Sync failed")
        time.sleep(minutes * 60)
