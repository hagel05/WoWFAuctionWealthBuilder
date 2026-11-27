# WoW Forever Auction House flip scanner

Scans the WoW Forever Auction House once an hour through Blizzard's Battle.net API and writes a ranked list of listings worth buying and reselling, sized for a small bankroll that should grow steadily.

It is set up for **US, Normal ruleset, Alliance** (house 111), at 20 minutes past each hour.

## What you get each hour

`reports/latest.html` opens in any browser and shows:

- **Vendor flips:** listings priced below what a vendor pays for the item, grouped per item and shown only when the total profit is at least 10 silver (`min_vendor_profit`). Buy them and sell to any vendor; there are no auction house fees, so these are risk-free.
- **Market flips:** listings well below the item's usual price. For each one it lists which listings to buy (quantity at price), what to relist at for 24 hours, the expected profit after the 5% cut and deposits, and how many days it should take to sell.
- **Skipped deals:** cheap listings that failed a rule, with the reason, so you can see what the scanner is avoiding.

`reports/latest.csv` holds the same list, and `reports/flag_log.csv` keeps every flag ever raised so the rules can be tuned later.

**Market flips need about a week of history first.** The scanner compares each listing with the item's 14-day price history and only trusts items with at least 7 days of it. Vendor flips work from the first scan.

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

## Keeping your bankroll current

Per-flip limits are a share of your gold (15% while careful), so tell the scanner when your gold changes:

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

## How flips are scored

The rules follow the "Flip scoring rules" doc. In short, per unit, with B = buy price:

- **Market value (MV)** is the median of the item's hourly cheapest price over 14 days; **MV3** is the same over 3 days.
- **Resale target** T = 0.97 × min(MV, MV3).
- **Net profit** = T × 0.95 − B − expected lost deposits, where the deposit is 60% of the vendor price for a 24 hour listing and is lost only if the listing expires.
- **Buy** when the discount is at least 30%, profit is at least 10s per unit and 50s per flip, ROI is at least 25%, the item sells 5 or more a day near MV, it should sell within 2 days, and the flip costs at most 15% of your bankroll.
- **Skip** items with under 7 days of history, fewer than 5 auctions, one price point holding over 60% of the supply, a falling price (MV3 under 85% of MV), a sudden buyout and price jump, or prices that swing too much.
- **Rank** by net profit × quantity × min(1, daily sales ÷ quantity) ÷ (1 + volatility), roughly gold per day.

Every threshold is a first guess and can be changed in `config.toml`. After a few weeks, compare `reports/flag_log.csv` with what actually sold and tune them.

## Things to know

- **The Forever API is undocumented.** Blizzard's official Game Data docs describe the retail API, whose auction paths (`/data/wow/connected-realm/...`) do not work for Forever. The scanner uses the paths community testers found: `/data/wow/ruleset/{id}/auctions/{house}` and `.../commodities` in the `dynamic-forever-us` namespace. These can change without notice; `wowflip check` is the quickest way to see if they still work.
- **Sales are estimated.** The API has no sales history or seller names. A listing that disappears while it still had hours left counts as sold, so cancellations are counted too and the estimate is an upper bound. That is why the rules ask for 5 sales a day and a 30% discount.
- **Some items have no details.** About 43% of item ids returned 404 from the item endpoint in community tests. Those items are skipped because their type and vendor price are unknown. You can add them to `items_override.csv` (copy `items_override.example.csv`; `sell_price` is in copper), for example from an AHDB addon export.
- **Vendor price** comes from the item endpoint's `sell_price`. In the first live scan (27 Nov 2026) every item that resolved had one.
- **Item variants** such as random "of the Bear" suffixes are grouped under one item id. That does not matter for trade goods and consumables, but should be revisited before gear flips matter (above 200g).
- **Rate limits:** one scan makes 2 requests plus one per never-seen item (up to 1,000 on the first runs, cached forever after), well under Blizzard's usual limits.

## Running in Docker (for later, such as TrueNAS)

The core has no Windows-specific code; everything can be configured with environment variables, and all state lives in one data folder.

```bash
docker build -t wowflip .
docker run -d --name wowflip --restart unless-stopped \
  -e BLIZZARD_CLIENT_ID=... -e BLIZZARD_CLIENT_SECRET=... \
  -e TZ=America/Chicago \
  -v /mnt/pool/apps/wowflip:/data \
  wowflip
```

The container scans at :20 every hour and writes reports to `/data/reports`. Put an optional `config.toml` and `items_override.csv` in the data folder. Environment variables: `WOWFLIP_REGION`, `WOWFLIP_RULESET_ID`, `WOWFLIP_HOUSE_ID`, `WOWFLIP_BANKROLL_GOLD`, `WOWFLIP_DATA_DIR`, `WOWFLIP_REPORT_DIR`, `WOWFLIP_ITEM_OVERRIDE_CSV`, `WOWFLIP_SCAN_MINUTE`, `WOWFLIP_INCLUDE_COMMODITIES`, `WOWFLIP_CONFIG`. To move your history from the PC, copy the `data` folder into the volume.

## Troubleshooting

- **"credentials are missing"**: `.env` is not in the folder you ran the command from, or the names are misspelled.
- **"rejected the API credentials (HTTP 401)"**: the Client ID or Secret is wrong; create a new secret on the Battle.net developer site.
- **"Auction house 111 not found (404)"**: the Forever API paths changed. Run `wowflip check` and look at the house list it prints.
- **Logs** are in `data\scan.log` (and `data\task.log` for the scheduled task).

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests include the worked example from the scoring rules doc and an end-to-end run against a simulated auction house.
