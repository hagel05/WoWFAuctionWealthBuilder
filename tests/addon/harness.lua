-- Loads the WoWFlip addon in plain Lua 5.1 with a stubbed WoW API and runs checks.
-- Usage: lua5.1 harness.lua <addon dir> <Data.lua path>
local addonDir, dataPath = arg[1], arg[2]

local function Obj()
    local o = { _shown = false, _scripts = {}, _events = {}, _lines = false }
    return setmetatable(o, { __index = function(t, k)
        return function(self, ...)
            local a = { ... }
            if k == "Show" then self._shown = true
            elseif k == "Hide" then
                local was = self._shown
                self._shown = false
                if was and self._scripts.OnHide then self._scripts.OnHide(self) end
            elseif k == "SetEnabled" then self._enabled = a[1] and true or false
            elseif k == "IsEnabled" then return self._enabled ~= false
            elseif k == "SetShown" then self._shown = a[1] and true or false
            elseif k == "IsShown" then return self._shown
            elseif k == "SetScript" then self._scripts[a[1]] = a[2]
            elseif k == "HookScript" then self._scripts[a[1]] = a[2]
            elseif k == "GetScript" then return self._scripts[a[1]]
            elseif k == "SetText" then self._text = a[1]
            elseif k == "GetText" then return self._text
            elseif k == "AddLine" then if not self._lines then self._lines = {} end; table.insert(self._lines, a[1])
            elseif k == "CreateFontString" or k == "CreateTexture" then return Obj()
            elseif k == "RegisterEvent" then self._events[a[1]] = true
            end
        end
    end })
end

frames = {}
function CreateFrame(kind, name, parent, template)
    local f = Obj()
    table.insert(frames, f)
    if name then _G[name] = f end
    return f
end
UIParent, GameTooltip, DEFAULT_CHAT_FRAME = Obj(), Obj(), Obj()
local chat = {}
DEFAULT_CHAT_FRAME.AddMessage = function(_, m) table.insert(chat, m) end
SlashCmdList = {}
local NOW = 1800000000
function GetServerTime() return NOW end
function GetMoney() return 25 * 10000 end
function UnitName() return "Matt" end
function GetRealmName() return "Dreamscythe" end
function UnitFactionGroup() return "Alliance" end
function strtrim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
function GetItemInfo() return nil end
local postcall
TooltipDataProcessor = { AddTooltipPostCall = function(kind, fn) postcall = fn end }
Enum = { TooltipDataType = { Item = 0 } }
C_Item = { GetItemNameByID = function(id) return nil end }

local function check(cond, msg)
    if not cond then error("FAIL: " .. msg, 2) end
end

-- Load the data addon, then the main addon's files in .toc order.
dofile(dataPath)
local ns = {}
local toc = io.open(addonDir .. "/WoWFlip.toc"):read("*a")
for file in toc:gmatch("\n([%w_]+%.lua)") do
    local chunk = assert(loadfile(addonDir .. "/" .. file))
    chunk("WoWFlip", ns)
end
local events = frames[1]
local onEvent = events._scripts.OnEvent
check(events._events.AUCTION_HOUSE_SHOW, "registers AUCTION_HOUSE_SHOW")

onEvent(events, "ADDON_LOADED", "WoWFlip")
check(type(WoWFlipDB) == "table", "creates WoWFlipDB")
check(ns.feed ~= nil, "loads the feed")
onEvent(events, "PLAYER_LOGIN")
check(chat[1] and chat[1]:find("market flips"), "prints a login summary: " .. tostring(chat[1]))
check(WoWFlipDB.chars["Matt - Dreamscythe"].gold == 250000, "records gold at login")

-- Tooltip lines for a flagged item and a priced item.
local flip = ns.feed.flips[1]
local lines = ns.TooltipLines(flip.item_id)
check(#lines >= 2 and lines[1]:find("Flip:"), "flip tooltip line")
local tip = Obj()
postcall(tip, { id = flip.item_id })
check(tip._lines and #tip._lines >= 2, "tooltip post-call adds lines")
check(#ns.TooltipLines(424242) == 0, "no lines for unknown items")

-- Auction House opens: panel shows, docks, lists flips; search and cross off.
AuctionHouseFrame = Obj()
AuctionHouseFrame._shown = true
local searched
AuctionHouseFrame.SearchBar = { SetSearchText = function(_, t) searched = t end, StartSearch = function() end }
NOW = NOW + 60
onEvent(events, "AUCTION_HOUSE_SHOW")
check(WoWFlipPanel and WoWFlipPanel._shown, "panel opens with the AH")
check(WoWFlipDB.chars["Matt - Dreamscythe"].seen == NOW, "records gold when the AH opens")
local n = #ns.PanelList()
check(n == #ns.feed.flips, "panel lists every flip")
ns.SearchAH(flip)
check(searched == flip.name, "click searches the AH by name")
ns.ToggleDone(flip.item_id)
check(#ns.PanelList() == n - 1, "right-click crosses a row off")
-- Snapshot (riskier) flips: own tab, tooltip lines, no days-to-sell needed.
local snap = ns.feed.snapshot[1]
check(snap and snap.kind == "snapshot" and snap.days_to_sell == nil, "feed has a snapshot flip")
local slines = ns.TooltipLines(snap.item_id)
check(#slines == 2 and slines[1]:find("Snapshot flip"), "snapshot tooltip lines")
WoWFlipDB.settings.tab = "snapshot"
check(#ns.PanelList() == #ns.feed.snapshot, "snapshot tab lists snapshot flips")
ns.RefreshPanel()
check(WoWFlipPanel.status._text:find("snapshot"), "status names snapshot flips: " .. tostring(WoWFlipPanel.status._text))
WoWFlipDB.settings.tab = "vendor"
check(#ns.PanelList() == #ns.feed.vendor, "vendor tab lists vendor flips")
ns.RefreshPanel()

---------------------------------------------------------------------------
-- Buy, list and collect (stubbed C_AuctionHouse)
---------------------------------------------------------------------------
local calls = {}
local function called(name) return calls[name] end
local commodityResults, itemResults = {}, {}
C_AuctionHouse = {
    MakeItemKey = function(id) return { itemID = id } end,
    SendSearchQuery = function(key) calls.search = key.itemID end,
    GetNumCommoditySearchResults = function() return #commodityResults end,
    GetCommoditySearchResultInfo = function(_, i) return commodityResults[i] end,
    GetNumItemSearchResults = function() return #itemResults end,
    GetItemSearchResultInfo = function(_, i) return itemResults[i] end,
    StartCommoditiesPurchase = function(id, qty) calls.start = { id, qty } end,
    ConfirmCommoditiesPurchase = function(id, qty) calls.confirm = { id, qty } end,
    CancelCommoditiesPurchase = function() calls.cancel = true end,
    PlaceBid = function(id, amount) calls.bids = calls.bids or {}; table.insert(calls.bids, { id, amount }) end,
    CalculateCommodityDeposit = function(id, duration, qty) return 30 end,
    PostCommodity = function(loc, duration, qty, price) calls.post = { loc, duration, qty, price } end,
}
local trade
for _, f in ipairs(frames) do
    if f._events.COMMODITY_PRICE_UPDATED then trade = f end
end
check(trade, "trade module listens for AH events")
local function fire(event, ...) trade._scripts.OnEvent(trade, event, ...) end
local function state() return ns.DialogState() or {} end

check(ns.feed.max_flip_cost == 45000, "feed carries the per-flip cap: " .. tostring(ns.feed.max_flip_cost))

-- Commodity: plan within limits, Blizzard quote, confirm.
local herb = ns.flipsByItem[2447]
commodityResults = {
    { unitPrice = 1000, quantity = 5, numOwnerItems = 0 },
    { unitPrice = 1100, quantity = 10, numOwnerItems = 0 },
    { unitPrice = 1300, quantity = 50, numOwnerItems = 0 },
}
ns.StartBuy(herb)
check(called("search") == 2447, "Buy searches the item")
fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2447)
check(state().primary == "Get exact price", "plan offers a quote: " .. tostring(state().primary))
check(state().body:find("Estimated total: " .. ns.Money(8300), 1, true), "plan shows the total: " .. state().body)
ns.DialogPress("primary")
check(called("start") and calls.start[1] == 2447 and calls.start[2] == 8, "starts a purchase of 8")
check(state().primaryEnabled == false, "buy button waits for the quote")
fire("COMMODITY_PRICE_UPDATED", 1050, 8400)
check(state().primary == "Buy for 84s 0c", "confirm names the exact total: " .. tostring(state().primary))
check(state().body:find("Total: 84s 0c", 1, true), "confirm body shows the total")
ns.DialogPress("primary")
check(called("confirm") and calls.confirm[2] == 8, "confirms the purchase")
fire("COMMODITY_PURCHASE_SUCCEEDED")
check(WoWFlipDB.bought[2447].qty == 8 and WoWFlipDB.bought[2447].cost == 8400, "records the purchase")
check(state().title:find("Bought"), "says it was bought")
check(state().body:find("Collect AH mail", 1, true), "points to the mailbox")
ns.CloseDialog()

-- Price rose between the plan and the quote: cancel, nothing bought.
calls = {}
ns.StartBuy(herb)
fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2447)
ns.DialogPress("primary")
fire("COMMODITY_PRICE_UPDATED", 1500, 12000)
check(calls.cancel and not calls.confirm, "cancels when the quote is over the limit")
check(state().title == "Price went up", "explains the cancel")
ns.CloseDialog()

-- Nothing cheap enough left.
commodityResults = { { unitPrice = 5000, quantity = 5, numOwnerItems = 0 } }
ns.StartBuy(herb)
fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2447)
check(state().title == "Nothing to buy" and state().body:find("above this flip's limit"), "refuses a risen price")
ns.CloseDialog()

-- Bankroll cap: never more than max_flip_cost.
local _, capQty, capCost = ns.PlanBuy({ { unit = 1000, qty = 100 } }, 100, 1100, 45000)
check(capQty == 45 and capCost == 45000, "caps the units by the per-flip limit")

-- Item auctions: one click per listing, skipping one that's too expensive.
calls = {}
itemResults = {
    { auctionID = 11, buyoutAmount = 5000, quantity = 5 },
    { auctionID = 12, buyoutAmount = 3300, quantity = 3 },
    { auctionID = 13, buyoutAmount = 99999, quantity = 1 },
    { auctionID = 14, buyoutAmount = 1000, quantity = 1, containsOwnerItem = true },
}
local thing = { item_id = 7777, name = "Thing", buy_max = 1100, quantity = 8, relist = 1800 }
ns.StartBuy(thing)
fire("ITEM_SEARCH_RESULTS_UPDATED", { itemID = 7777 })
check(state().body:find("Listing 1 of 2", 1, true), "item plan has 2 listings: " .. tostring(state().body))
ns.DialogPress("primary")
check(calls.bids[1][1] == 11 and calls.bids[1][2] == 5000, "bids the full buyout on listing 1")
fire("AUCTION_HOUSE_PURCHASE_COMPLETED", 11)
check(state().body:find("Listing 2 of 2", 1, true), "moves to listing 2")
ns.DialogPress("primary")
fire("AUCTION_HOUSE_PURCHASE_COMPLETED", 12)
check(#calls.bids == 2 and WoWFlipDB.bought[7777].qty == 8, "bought both listings")
ns.CloseDialog()
WoWFlipDB.bought[7777] = nil

-- Sell tab and List with deposit, cut and profit.
C_Item.GetItemCount = function(id) return id == 2447 and 8 or 0 end
C_Container = {
    GetContainerNumSlots = function(bag) return bag == 0 and 2 or 0 end,
    GetContainerItemInfo = function(bag, slot) if slot == 1 then return { itemID = 2447, stackCount = 8 } end end,
    GetContainerNumFreeSlots = function() return 5 end,
}
WoWFlipDB.settings.tab = "sell"
local sellList = ns.PanelList()
check(#sellList == 1 and sellList[1].paid_each == 1050, "sell tab lists the bought flip")
ns.RefreshPanel()
calls = {}
commodityResults = { { unitPrice = 1700, quantity = 20, numOwnerItems = 0 } }
ns.StartList(sellList[1])
fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2447)
local body = state().body or ""
check(body:find("Price each: " .. ns.Money(1700), 1, true), "matches the lowest price (LIFO): " .. body)
check(body:find("Deposit now: ", 1, true) and body:find("AH cut 5%", 1, true) and body:find("Profit", 1, true),
    "list confirm shows deposit, cut and profit")
check(body:find("for 24 hours", 1, true) and state().extra == "Length: 24h (change)", "defaults to 24h")
ns.DialogPress("extra")
check(state().body:find("for 2 hours", 1, true), "length can be changed to 2h")
ns.DialogPress("primary")
check(calls.post and calls.post[2] == 1 and calls.post[3] == 8 and calls.post[4] == 1700, "posts 8 at 1700 for 2h")
check(WoWFlipDB.settings.hours == 2, "remembers the length picked")
fire("AUCTION_HOUSE_AUCTION_CREATED", 99)
check(WoWFlipDB.bought[2447] == nil, "listed items leave the Sell tab")
ns.CloseDialog()
check(ns.BreakEven(1050, 30 / 8, 0.05) == 1110, "break-even price")

SlashCmdList.WOWFLIP("length 24")
check(WoWFlipDB.settings.hours == 24, "/flip length 24")

-- Deposit fallback when the game gives no number: 5% / 20% / 60% of vendor price.
C_AuctionHouse.CalculateCommodityDeposit = nil
C_Item.GetItemInfo = function() return "Peacebloom", nil, 1, 1, 1, "", "", 20, "", 0, 100 end
WoWFlipDB.bought[2447] = { qty = 8, cost = 8400, name = "Peacebloom", relist = 1800 }
ns.StartList(ns.PanelList()[1])
fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2447)
check(state().body:find("Deposit now: " .. ns.Money(480), 1, true), "24h fallback deposit 60%: " .. state().body)
ns.DialogPress("extra")
check(state().body:find("Deposit now: " .. ns.Money(40), 1, true), "2h fallback deposit 5%")
ns.DialogPress("extra")
check(state().body:find("Deposit now: " .. ns.Money(160), 1, true), "8h fallback deposit 20%")
ns.CloseDialog()
WoWFlipDB.bought[2447] = nil

-- Mailbox: collect only AH mail.
local inbox = {
    { subject = "Auction successful: Peacebloom", money = 15000, items = 0, invoice = "seller" },
    { subject = "hi", money = 0, items = 1 },
}
function GetInboxNumItems() return #inbox end
function GetInboxHeaderInfo(i)
    local m = inbox[i]
    return nil, nil, "x", m.subject, m.money, 0, 30, m.items
end
function GetInboxInvoiceInfo(i) return inbox[i].invoice end
function AutoLootMailItem(i) calls.loot = i; table.remove(inbox, i) end
local mail
for _, f in ipairs(frames) do
    if f._events.MAIL_SHOW then mail = f end
end
mail._scripts.OnEvent(mail, "MAIL_SHOW")
check(WoWFlipCollectButton._text == "Collect AH mail (1)", "collect button counts AH mail: " ..
    tostring(WoWFlipCollectButton._text))
WoWFlipCollectButton._scripts.OnClick(WoWFlipCollectButton)
check(calls.loot == 1 and #inbox == 1, "collects the AH mail only")
check(chat[#chat]:find("Collected 1 auction mails and " .. ns.Money(15000), 1, true), "reports what it collected: " .. chat[#chat])
WoWFlipDB.settings.tab = "vendor"
onEvent(events, "AUCTION_HOUSE_CLOSED")
check(not WoWFlipPanel._shown, "panel hides with the AH")
SlashCmdList.WOWFLIP("left")
check(WoWFlipDB.settings.side == "left", "/flip left")
SlashCmdList.WOWFLIP("status")
check(ns.Money(12345, true) == "1g 23s 45c", "money format")
check(ns.Money(7, true) == "7c", "money format copper only")
-- Stale data warning.
NOW = NOW + 5 * 3600
check(ns.FeedIsOld(), "old scans are flagged")
print("OK")
