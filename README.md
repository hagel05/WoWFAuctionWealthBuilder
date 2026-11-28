# WoW Forever Auction House flip scanner

Scans the WoW Forever Auction House once an hour through Blizzard's Battle.net API and writes a ranked list of listings worth buying and reselling, sized for a small bankroll that should grow steadily.

It is set up for **US, Normal ruleset, Alliance** (house 111), at 20 minutes past each hour.

## What you get each hour

`reports/latest.html` opens in any browser and shows:

- **Vendor flips:** listings priced below what a vendor pays for the item, grouped per item and shown only when the total profit is at least 10 silver (`min_vendor_profit`). Buy them and sell to any vendor; there are no auction house fees, so these are risk-free.
- **Market flips:** listings well below the item's usual price. For each one it lists which listings to buy (quantity at price), what to relist at for 24 hours, the expected profit after the 5% cut and deposits, and how many days it should take to sell.
- **Skipped deals:** cheap listings that failed a rule, with the reason, so you can see what the scanner is avoiding.

`reports/latest.csv` holds the same list, and `reports/flag_log.csv` keeps every flag ever raised so the rules can be tuned later.

**You get flips from the first scan, and they get safer as history builds:**

| History | What you get |
| --- | --- |
| From the first scan | **Vendor flips**, and **snapshot flips** (riskier): an item whose cheapest listings are at least 30% under the median of its other listings. There is no sales history yet, so these use a smaller bankroll share (10% per flip), a 30% ROI floor, need 8+ other listings and never buy more than a quarter of the supply. |
| From day 2 | **Early market flips**, marked "early": the normal rules, but stricter. At day 2 the discount and ROI floors are 15 points higher, the item must sell twice as often, and a flip may use only half the usual share of bankroll. These ease off day by day. |
| From day 7 | **Market flips** on the normal rules below. Snapshot flips continue only for items with under 2 days of history, such as ones newly listed. |

## Setup on Windows

### 1. Get Battle.net API credentials

1. Sign in at <https://develop.battle.net/access/clients> with your Battle.net account.
2. Click **Create Client**. Any name works; leave the redirect URL blank and tick "I do not have a service URL".
3. Keep the page open; you need the **Client ID** and **Client Secret** in step 3.

Treat the secret like a password: it only goes in the `.env` file on your PC, never in chat or in the repository.

### 2. Install Python and the scanner

Install Python 3.11 or newer from <https://www.python.org/downloads/> (tick "Add python.exe to PATH"). Then in PowerShell:

```powershell
git clone https://github.com/hagel05/WoWFAuctionWealthBuilder.git
cd WoWFAuctionWealthBuilder
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

The scanner uses only Python's standard library, so there is nothing else to install.

### 3. Add your credentials and settings

```powershell
copy .env.example .env
copy config.example.toml config.toml
notepad .env
```

Paste your Client ID and Secret after `BLIZZARD_CLIENT_ID=` and `BLIZZARD_CLIENT_SECRET=` and save. Both `.env` and `config.toml` are in `.gitignore`.

`config.toml` already holds the right realm and the default rules; edit `bankroll_gold` if you have more or less than 30g.

### 4. Check the API works

```powershell
wowflip check
```

This gets a token, lists the rulesets and auction houses, counts listings in house 111, and looks up one item to see whether the API returns its vendor price. If it fails, see [Troubleshooting](#troubleshooting).

### 5. Run a scan

```powershell
wowflip scan
start reports\latest.html
```

### 6. Run it every hour

Either register a scheduled task (runs even when no window is open, as long as you are logged in and the PC is awake):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
```

This creates a task called "WoW Flip Scanner" that runs `scripts\run_scan.bat` at :20 every hour. Output goes to `data\task.log`. Remove it with `Unregister-ScheduledTask -TaskName "WoW Flip Scanner"`.

Or keep a window open with `wowflip scan --loop --now`, which scans immediately and then at :20 every hour until you press Ctrl+C.

Missed hours are fine. They leave gaps in the history, and the scanner only counts sales across gaps short enough to tell a sale from an expired listing.

## In-game addon

The **WoWFlip** addon shows the flip list in game. When you open the Auction House, a **Flips** panel docks beside it:

- **Market** tab: each flip with what to buy (quantity and the most to pay per unit), what to relist at, and the profit after fees. Hover a row to see the exact listings to buy.
- **Snapshot** tab: the riskier flips judged from current listings only (tagged "risky"). Hover a row to see what the other listings ask. Early market flips show an "early" tag on the Market tab.
- **Vendor** tab: listings under what a vendor pays.
- **Click** a row to search for it in Blizzard's Auction House window. **Right-click** a row to cross it off until the next scan.
- A cost shown in red means you do not have that much gold on you.

### Buy, collect, list

Blizzard only allows a purchase or a posting from your own click, so each one is a button in a confirm window. Nothing is ever bought or posted without that click.

1. **Buy** (button on each row). The addon checks live prices and plans the purchase within the flip's limits: never above its max price per unit, never more units than the flip, never more than the per-flip share of your bankroll (15% while careful), and never more gold than you have.
   - Stackable goods (herbs, ore, cloth, potions): the window shows the quantity, price each and estimated total. **Get exact price** asks Blizzard for the final total, and **Buy for <total>** pays it. If the total came back above the flip's limit, the purchase is cancelled and nothing is spent.
   - Other items: one **Buy for <price>** click per listing, with the running total shown.
2. **Collect AH mail** (button under the mailbox window). Takes items and gold out of Auction House mail: purchases, sales, and expired or cancelled auctions. It skips cash-on-delivery and ordinary mail.
3. **List** (the panel's **Sell** tab shows the flips you bought that are now in your bags). The window shows price each, the total, the deposit, the 5% AH cut, what you receive, and your profit compared with what you paid. If someone is already listed lower, it matches their price (at the same price the newest listing sells first, so there is no need to undercut), but never goes below your break-even. **Length** switches between 24h, 2h and 8h, and the deposit updates with it (5%, 20% or 60% of the vendor price). The length you pick is remembered; `/flip length 2|8|24` sets it directly.

   Which length: the deposit is the same per hour (2.5% of the vendor price) and comes back when the item sells, and at the same price the newest listing sells first. So while you are playing, **2h** listings relisted as they expire keep you at the front of the queue for little risk. Before logging off, switch to **8h or 24h** so you stay listed while away.
- **Item tooltips** everywhere get a line such as "Flip: buy up to 12s each (8), relist at 18s", plus the item's market value and daily sales.

Commands: `/flip` shows or hides the panel, `/flip left` or `/flip right` docks it on that side, `/flip auto` turns opening with the AH on or off, `/flip tooltip` turns the tooltip lines on or off, `/flip length 2|8|24` sets the default auction length for List, and `/flip status` says when the data was scanned.

### How the data gets into the game

Addons cannot use the internet, so the data travels the way TradeSkillMaster's helper does it: after each scan, the scanner (or the sync helper on another PC) writes the list into a second small addon, **WoWFlipData**, in your AddOns folder. The game reads it when you log in or type `/reload`, so **type `/reload` after the :20 scan to see the new hour's list**. The panel turns red when its data is more than 90 minutes old.

The addon also notes your gold each time you open the Auction House. The game saves that when you log out or `/reload`, and the next scan uses it as your bankroll, so you no longer need `wowflip bankroll`.

### Setup on the PC where the scanner runs

1. Install the addon (default WoW folder shown; pass `-WowDir` if yours differs):

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install_addon.ps1
   ```

2. Add your WoW folder to `config.toml`:

   ```toml
   [addon]
   wow_dir = "C:/Program Files (x86)/World of Warcraft"
   ```

3. Run `wowflip scan` (or wait for the hourly task), then `/reload` in game. Check it with `/flip status`.

Nothing else is needed on this PC: every scan updates the addon directly. `wowflip sync` does the same thing on demand.

### Other PCs, and the TrueNAS setup

When the scanner runs on a server (see "Running in Docker" below), each PC you play on runs the small **sync helper**, which fetches the latest list from the server every 5 minutes and sends your in-game gold back.

1. Download **WoWFlipSync** from the latest successful run on the repository's Actions tab (or build it with `scripts\build_sync_exe.ps1`). It contains `WoWFlipSync.exe`, the addon and the install scripts. No Python needed.
2. Install the addon with `scripts\install_addon.ps1`.
3. Next to `WoWFlipSync.exe`, create `config.toml`:

   ```toml
   [addon]
   wow_dir = "C:/Program Files (x86)/World of Warcraft"
   sync_url = "http://truenas.local:8787"
   ```

   If the server has `WOWFLIP_API_TOKEN` set, set the same value as a Windows environment variable on the PC.
4. Run `install_sync_task.ps1` from that folder so the helper starts at every logon. `WoWFlipSync.exe --once` syncs a single time.

If you play on more than one character, set `bankroll_characters = ["Name - Realm", ...]` under `[addon]` to add up their gold; otherwise the last character that opened the Auction House is used.

## Keeping your bankroll current

With the addon installed and `wow_dir` set, this is automatic (see above). Without it, per-flip limits are a share of your gold (15% while careful), so tell the scanner when your gold changes:

```powershell
wowflip bankroll 42.5     # set to 42g 50s
wowflip bankroll          # show the current value and profile
```

Above 200g it switches automatically from the **careful** profile (trade goods and consumables, 2 days to sell) to **balanced** (adds bind-on-equip weapons and armor, 3 days to sell, higher profit floors).

## Commands

| Command | What it does |
| --- | --- |
| `wowflip scan` | Fetch the auction house, update history, write the report |
| `wowflip scan --loop [--now]` | Keep scanning at :20 every hour |
| `wowflip report` | Rebuild the report from stored data without calling the API (use after changing settings) |
| `wowflip bankroll [gold]` | Show or set your current gold |
| `wowflip check` | Test credentials and the Forever API endpoints |
| `wowflip sync [--loop] [--force]` | Copy the latest flip list into the in-game addon on this PC |
| `wowflip serve [--with-scanner]` | Run the API that sync helpers on other PCs read from (port 8787) |

## How flips are scored

The rules follow the "Flip scoring rules" doc. In short, per unit, with B = buy price:

- **Market value (MV)** is the median of the item's hourly cheapest price over 14 days; **MV3** is the same over 3 days.
- **Resale target** T = 0.97 × min(MV, MV3).
- **Net profit** = T × 0.95 − B − expected lost deposits, where the deposit is 60% of the vendor price for a 24 hour listing and is lost only if the listing expires.
- **Buy** when the discount is at least 30%, profit is at least 10s per unit and 50s per flip, ROI is at least 25%, the item sells 5 or more a day near MV, it should sell within 2 days, and the flip costs at most 15% of your bankroll.
- **Skip** items with under 7 days of history, fewer than 5 auctions, one price point holding over 60% of the supply, a falling price (MV3 under 85% of MV), a sudden buyout and price jump, or prices that swing too much.
- **Last in, first out:** WoW Forever sells the newest listing first among equal prices, so listings already at your relist price do not count as ahead of you, and snapshot flips match the next listing instead of undercutting it. Set `newest_first_at_same_price = false` under `[market]` if that changes.
- **Rank** by net profit × quantity × min(1, daily sales ÷ quantity) ÷ (1 + volatility), roughly gold per day.

The early and snapshot rules are under `[market]` in `config.toml` (`ramp_start_days`, `ramp_extra_discount`, `snapshot_flips = false` to turn snapshot flips off, and so on).

Every threshold is a first guess and can be changed in `config.toml`. After a few weeks, compare `reports/flag_log.csv` with what actually sold and tune them.

## Things to know

- **The Forever API is undocumented.** Blizzard's official Game Data docs describe the retail API, whose auction paths (`/data/wow/connected-realm/...`) do not work for Forever. The scanner uses the paths community testers found: `/data/wow/ruleset/{id}/auctions/{house}` and `.../commodities` in the `dynamic-forever-us` namespace. These can change without notice; `wowflip check` is the quickest way to see if they still work.
- **Sales are estimated.** The API has no sales history or seller names. A listing that disappears while it still had hours left counts as sold, so cancellations are counted too and the estimate is an upper bound. That is why the rules ask for 5 sales a day and a 30% discount.
- **Some items have no details.** About 43% of item ids returned 404 from the item endpoint in community tests. Those items are skipped because their type and vendor price are unknown. You can add them to `items_override.csv` (copy `items_override.example.csv`; `sell_price` is in copper), for example from an AHDB addon export.
- **Vendor price** comes from the item endpoint's `sell_price`. In the first live scan (27 Nov 2026) every item that resolved had one.
- **Item variants** such as random "of the Bear" suffixes are grouped under one item id. That does not matter for trade goods and consumables, but should be revisited before gear flips matter (above 200g).
- **Rate limits:** one scan makes 2 requests plus one per never-seen item (up to 1,000 on the first runs, cached forever after), well under Blizzard's usual limits.

## Running in Docker (TrueNAS)

The core has no Windows-specific code; everything can be configured with environment variables, and all state lives in one data folder.

```bash
docker build -t wowflip .
docker run -d --name wowflip --restart unless-stopped \
  -e BLIZZARD_CLIENT_ID=... -e BLIZZARD_CLIENT_SECRET=... \
  -e WOWFLIP_API_TOKEN=some-long-random-text \
  -e TZ=America/Chicago \
  -p 8787:8787 \
  -v /mnt/pool/apps/wowflip:/data \
  wowflip
```

The container scans at :20 every hour, writes reports to `/data/reports`, and serves the API on port 8787 for the sync helpers: `/api/v1/feed` (the flip list), `/api/v1/bankroll` (gold from the game) and `/health`. Opening `http://truenas.local:8787/` in a browser shows the latest HTML report. Keep the port on your home network; do not forward it to the internet. Put an optional `config.toml` and `items_override.csv` in the data folder. Environment variables: `WOWFLIP_REGION`, `WOWFLIP_RULESET_ID`, `WOWFLIP_HOUSE_ID`, `WOWFLIP_BANKROLL_GOLD`, `WOWFLIP_DATA_DIR`, `WOWFLIP_REPORT_DIR`, `WOWFLIP_ITEM_OVERRIDE_CSV`, `WOWFLIP_SCAN_MINUTE`, `WOWFLIP_INCLUDE_COMMODITIES`, `WOWFLIP_CONFIG`, `WOWFLIP_API_TOKEN`, `WOWFLIP_SERVER_PORT`. To move your history from the PC, copy the `data` folder into the volume.

## Troubleshooting

- **"credentials are missing"**: `BLIZZARD_CLIENT_ID` / `BLIZZARD_CLIENT_SECRET` are not set as environment variables (open a new PowerShell window after setting them) and there is no `.env` next to `config.toml`, or the names are misspelled.
- **The Flips panel says "No flip data yet"**: `wow_dir` is not set, or no scan has run since. Run `wowflip sync --force`, then `/reload`. The log says where it wrote `Data.lua`.
- **The panel does not appear**: check that WoWFlip is ticked in the AddOns list on the character screen (enable "Load out of date AddOns" if a patch changed the interface number), and try `/flip`.
- **"rejected the API credentials (HTTP 401)"**: the Client ID or Secret is wrong; create a new secret on the Battle.net developer site.
- **"Auction house 111 not found (404)"**: the Forever API paths changed. Run `wowflip check` and look at the house list it prints.
- **Logs** are in `data\scan.log` (and `data\task.log` for the scheduled task).

## Development

```bash
pip install -e ".[dev]"
pytest
```

The addon tests load the Lua addon with a stubbed WoW API and need `lua5.1` on the PATH (they are skipped without it; CI installs it).

The tests include the worked example from the scoring rules doc and an end-to-end run against a simulated auction house.
