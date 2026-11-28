"""Feed, Lua bridge, sync helper, API, and (if Lua 5.1 is installed) the addon itself."""

import json
import shutil
import subprocess
import threading
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from wowflip.addon_sync import WowInstall, render_data_lua
from wowflip.bankroll import apply_game_bankroll, choose_bankroll
from wowflip.config import GOLD, Addon, Config
from wowflip.feed import build_feed, feed_path, write_json_atomic
from wowflip.lua import as_list, parse_saved_variables, to_lua
from wowflip.scan import ScanResult
from wowflip.scoring import Buy, Flip, VendorFlip
from wowflip.sync import sync_once

ROOT = Path(__file__).resolve().parent.parent


def sample_result(taken_at=1_800_000_000):
    flip = Flip(item_id=2447, name='Peacebloom "fresh"', target=1800, mv=2000,
                buys=[Buy(1000, 5, 600.0), Buy(1100, 3, 500.0)], net_profit=4500, cost=8300,
                roi=0.54, days_to_sell=1.23)
    snap = Flip(item_id=2589, name="Linen Cloth", target=95, mv=100, buys=[Buy(50, 20, 35.0)],
                net_profit=700, cost=1000, roi=0.7, days_to_sell=float("nan"), kind="snapshot", reference=100)
    return ScanResult(
        taken_at=taken_at, changed=True, listings=100, sales_found=3, history_days=8.2,
        bankroll=30 * GOLD, profile="careful", flips=[flip],
        vendor=[VendorFlip(2770, "Copper Ore", 40, 5, 50, cost=200), VendorFlip(2770, "Copper Ore", 45, 2, 50, cost=90)],
        snapshots=[snap],
        prices={2447: (2000.4, 12.34), 2770: (60.0, 40.0)},
    )


def make_cfg(tmp_path, **addon):
    wow = tmp_path / "World of Warcraft"
    (wow / "_forever_" / "Interface" / "AddOns").mkdir(parents=True)
    return Config(data_dir=tmp_path / "data", report_dir=tmp_path / "reports",
                  addon=Addon(wow_dir=wow, **addon))


def write_saved_vars(cfg, chars_lua):
    sv = cfg.addon.wow_dir / "_forever_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
    sv.mkdir(parents=True)
    (sv / "WoWFlip.lua").write_text(
        "\nWoWFlipDB = {\n[\"chars\"] = {\n" + chars_lua + "},\n[\"settings\"] = {\n[\"panel\"] = true,\n},\n}\n",
        encoding="utf-8",
    )


def test_feed_shape():
    feed = build_feed(sample_result(), Config())
    assert feed["version"] == 1
    f = feed["flips"][0]
    assert (f["buy_max"], f["quantity"], f["relist"], f["profit"]) == (1100, 8, 1800, 4500)
    assert f["buys"] == [[1000, 5], [1100, 3]]
    s = feed["snapshot"][0]
    assert (s["kind"], s["reference"], s["relist"]) == ("snapshot", 100, 95)
    assert "days_to_sell" not in s
    assert feed["flips"][0]["kind"] == "market"
    json.dumps(feed, allow_nan=False)  # NaN must never reach the feed
    v = feed["vendor"][0]
    assert (v["quantity"], v["buy_max"], v["profit"]) == (7, 49, 60)
    assert feed["prices"]["2447"] == [2000, 12.3]


def test_lua_round_trip():
    data = {"a": 1, "b": [1, 2.5, "x\"y\\z\n"], "end": True, 7: {"nested": None}, "s p": "ünï"}
    lua = "X = " + to_lua(data)
    back = parse_saved_variables(lua)["X"]
    assert back["a"] == 1 and back["end"] is True and back[7] == {}
    assert as_list(back["b"]) == [1, 2.5, "x\"y\\z\n"]
    assert back["s p"] == "ünï"


def test_parse_wow_saved_variables_format():
    text = """
WoWFlipDB = {
["chars"] = {
["Matt - Dreamscythe"] = {
["gold"] = 312345,
["seen"] = 1800000100,
["faction"] = "Alliance",
},
},
["done"] = {
["items"] = {
[2447] = true,
},
},
}
OtherVar = nil
"""
    data = parse_saved_variables(text)
    assert data["WoWFlipDB"]["chars"]["Matt - Dreamscythe"]["gold"] == 312345
    assert data["WoWFlipDB"]["done"]["items"][2447] is True


def test_choose_bankroll():
    chars = {"A - R": {"gold": 100, "seen": 5}, "B - R": {"gold": 200, "seen": 9}, "bad": {"gold": "x"}}
    assert choose_bankroll(chars) == (200, 9, "B - R")
    assert choose_bankroll(chars, ("a - r", "B - R"))[:2] == (300, 9)
    assert choose_bankroll(chars, ("nobody",)) is None
    assert choose_bankroll({}) is None


def test_game_bankroll_respects_newer_manual_value(tmp_path):
    cfg = Config(data_dir=tmp_path)
    chars = {"A - R": {"gold": 45 * GOLD, "seen": 1000}}
    assert apply_game_bankroll(cfg, chars) == 45
    assert cfg.bankroll_copper() == 45 * GOLD
    cfg.bankroll_file.write_text(json.dumps({"gold": 50, "set_at": 2000}))  # typed later by hand
    assert apply_game_bankroll(cfg, chars) is None
    assert cfg.bankroll_copper() == 50 * GOLD
    assert apply_game_bankroll(replace(cfg, addon=Addon(bankroll_from_game=False)),
                               {"A - R": {"gold": 1, "seen": 3000}}) is None


def test_local_sync_writes_data_addon_and_bankroll(tmp_path):
    cfg = make_cfg(tmp_path)
    write_json_atomic(feed_path(cfg), build_feed(sample_result(), cfg))
    write_saved_vars(cfg, '["Matt - Dreamscythe"] = {\n["gold"] = 420000,\n["seen"] = 1800000500,\n},\n')

    assert sync_once(cfg) is True
    data_dir = cfg.addon.wow_dir / "_forever_" / "Interface" / "AddOns" / "WoWFlipData"
    assert (data_dir / "WoWFlipData.toc").read_text().startswith("## Interface: 16001")
    lua = (data_dir / "Data.lua").read_text(encoding="utf-8")
    assert lua.startswith("-- generated_at=1800000000")
    parsed = parse_saved_variables(lua.split("\n", 2)[2])["WoWFlipData_Feed"]
    assert parsed["prices"][2447] == {1: 2000, 2: 12.3}
    assert cfg.bankroll_copper() == 420000
    assert sync_once(cfg) is False  # unchanged scan is not rewritten


def test_api_serves_feed_and_takes_bankroll(tmp_path):
    from http.server import ThreadingHTTPServer

    from wowflip.server import make_handler

    cfg = replace(make_cfg(tmp_path), api_token="s3cret")
    write_json_atomic(feed_path(cfg), build_feed(sample_result(), cfg))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cfg))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(url + "/api/v1/feed")
        assert err.value.code == 401
        with urllib.request.urlopen(url + "/health") as r:
            assert json.loads(r.read())["has_feed"] is True

        # A sync helper on another PC: fetches over HTTP, posts its gold back.
        other = make_cfg(tmp_path / "pc2", sync_url=url)
        other = replace(other, api_token="s3cret")
        write_saved_vars(other, '["Alt - R"] = {\n["gold"] = 990000,\n["seen"] = 1800000900,\n},\n')
        assert sync_once(other) is True
        assert cfg.bankroll_copper() == 990000  # stored on the server side
        lua = (other.addon.wow_dir / "_forever_" / "Interface" / "AddOns" / "WoWFlipData" / "Data.lua").read_text()
        assert "Peacebloom" in lua
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_missing_wow_folder_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="wow_dir"):
        WowInstall(tmp_path / "nope")


def test_data_toc_matches_repo_copy():
    from wowflip.addon_sync import DATA_TOC

    assert (ROOT / "addon" / "WoWFlipData" / "WoWFlipData.toc").read_text() == DATA_TOC
    assert "## Interface: 16001" in (ROOT / "addon" / "WoWFlip" / "WoWFlip.toc").read_text()


@pytest.mark.skipif(not (shutil.which("lua5.1") or shutil.which("lua")), reason="Lua not installed")
def test_addon_runs_in_lua(tmp_path):
    lua = shutil.which("lua5.1") or shutil.which("lua")
    data = tmp_path / "Data.lua"
    data.write_text(render_data_lua(build_feed(sample_result(), Config())), encoding="utf-8")
    out = subprocess.run([lua, str(ROOT / "tests" / "addon" / "harness.lua"), str(ROOT / "addon" / "WoWFlip"),
                          str(data)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and out.stdout.strip().endswith("OK"), out.stdout + out.stderr


def test_scan_updates_addon_and_uses_game_gold(tmp_path, monkeypatch):
    """`wowflip scan` with [addon] wow_dir set: reads gold first, writes Data.lua after."""
    import sys

    sys.path.insert(0, str(ROOT / "tests"))
    from test_scan import FakeClient

    from wowflip import cli

    cfg = make_cfg(tmp_path)
    cfg = replace(cfg, item_override_csv=tmp_path / "none.csv")
    write_saved_vars(cfg, '["Matt - R"] = {\n["gold"] = 777777,\n["seen"] = 1800000000,\n},\n')
    monkeypatch.setattr(cli, "client_for", lambda c: FakeClient())
    assert cli.scan_once(cfg) == 0
    assert cfg.bankroll_copper() == 777777
    feed = json.loads(feed_path(cfg).read_text())
    assert feed["bankroll"] == 777777
    data = cfg.addon.wow_dir / "_forever_" / "Interface" / "AddOns" / "WoWFlipData" / "Data.lua"
    assert f"generated_at={feed['generated_at']}" in data.read_text()


def test_wow_dir_may_point_inside_the_game_folder(tmp_path):
    cfg = make_cfg(tmp_path)
    game = cfg.addon.wow_dir / "_forever_"
    for wow_dir in (cfg.addon.wow_dir, game, game / "Interface" / "AddOns"):
        assert WowInstall(wow_dir).root == game
    with pytest.raises(FileNotFoundError, match="World of Warcraft folder"):
        WowInstall(tmp_path)


def test_scan_finds_default_wow_folder_without_config(tmp_path, monkeypatch):
    from wowflip import cli

    wow = tmp_path / "World of Warcraft"
    (wow / "_forever_" / "Interface" / "AddOns").mkdir(parents=True)
    monkeypatch.setattr(cli, "DEFAULT_WOW_DIRS", (str(tmp_path / "missing"), str(wow)))
    game = cli.local_game(Config())
    assert game is not None and game.root == wow / "_forever_"
    assert cli.local_game(replace(Config(), addon=Addon(sync_url="http://x"))) is None
