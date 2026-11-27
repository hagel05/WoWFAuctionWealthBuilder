-- WoWFlip: loads the flip feed, records gold for the bankroll, handles events.
local ADDON, ns = ...

ns.flipsByItem, ns.vendorByItem, ns.snapshotByItem = {}, {}, {}
ns.feed = nil

local OLD_AFTER = 90 * 60 -- a scan older than this is flagged as stale

local function Now()
    return (GetServerTime and GetServerTime()) or time()
end
ns.Now = Now

-- Index the feed written by the sync helper (WoWFlipData addon).
function ns.LoadFeed()
    local feed = WoWFlipData_Feed
    ns.flipsByItem, ns.vendorByItem, ns.snapshotByItem = {}, {}, {}
    if type(feed) ~= "table" or feed.version ~= 1 then
        ns.feed = nil
        return
    end
    ns.feed = feed
    feed.flips = feed.flips or {}
    feed.vendor = feed.vendor or {}
    feed.prices = feed.prices or {}
    feed.snapshot = feed.snapshot or {} -- riskier flips from current listings only
    for _, f in ipairs(feed.flips) do ns.flipsByItem[f.item_id] = f end
    for _, v in ipairs(feed.vendor) do ns.vendorByItem[v.item_id] = v end
    for _, f in ipairs(feed.snapshot) do ns.snapshotByItem[f.item_id] = f end
end

function ns.FeedAge()
    if not ns.feed or not ns.feed.generated_at then return nil end
    return Now() - ns.feed.generated_at
end

function ns.FeedIsOld()
    local age = ns.FeedAge()
    return age ~= nil and age > OLD_AFTER
end

-- Rows the player crossed off stay hidden until a newer scan arrives.
function ns.IsDone(itemID)
    local done = WoWFlipDB.done
    return ns.feed ~= nil and done.generated_at == ns.feed.generated_at and done.items[itemID] == true
end

function ns.ToggleDone(itemID)
    if not ns.feed then return end
    local done = WoWFlipDB.done
    if done.generated_at ~= ns.feed.generated_at then
        done.generated_at, done.items = ns.feed.generated_at, {}
    end
    done.items[itemID] = (not done.items[itemID]) or nil
end

-- The sync helper reads this to keep the scanner's bankroll current.
function ns.RecordGold()
    if not GetMoney then return end
    local money = GetMoney()
    if type(money) ~= "number" then return end -- e.g. a hidden value
    local faction = UnitFactionGroup and UnitFactionGroup("player") or nil
    WoWFlipDB.chars[ns.CharacterKey()] = { gold = money, seen = Now(), faction = faction }
end

local function InitDB()
    WoWFlipDB = type(WoWFlipDB) == "table" and WoWFlipDB or {}
    local db = WoWFlipDB
    db.chars = type(db.chars) == "table" and db.chars or {}
    db.done = type(db.done) == "table" and db.done or {}
    db.done.items = type(db.done.items) == "table" and db.done.items or {}
    db.settings = type(db.settings) == "table" and db.settings or {}
    -- Flip items bought through the panel, so the Sell tab knows what to list
    -- and what they cost: [itemID] = { qty, cost, relist, name, at }
    db.bought = type(db.bought) == "table" and db.bought or {}
    local s = db.settings
    if s.panel == nil then s.panel = true end -- show the panel with the AH
    if s.tooltip == nil then s.tooltip = true end
    if s.side ~= "left" then s.side = "right" end
    if s.tab ~= "vendor" and s.tab ~= "snapshot" and s.tab ~= "sell" then s.tab = "market" end
end

local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("AUCTION_HOUSE_SHOW")
events:RegisterEvent("AUCTION_HOUSE_CLOSED")
events:RegisterEvent("PLAYER_MONEY")
events:SetScript("OnEvent", function(_, event, arg1)
    if event == "ADDON_LOADED" and arg1 == ADDON then
        InitDB()
        ns.LoadFeed()
    elseif event == "PLAYER_LOGIN" then
        ns.RecordGold()
        if ns.feed then
            local msg = #ns.feed.flips .. " market flips, " .. #ns.feed.snapshot .. " snapshot flips (riskier) and " ..
                #ns.feed.vendor .. " vendor flips from a scan " .. ns.Ago(ns.FeedAge()) .. "."
            if ns.FeedIsOld() then msg = msg .. " That's old: is the sync helper running?" end
            ns.Print(msg)
        else
            ns.Print("No flip data yet. Run the sync helper, then /reload.")
        end
    elseif event == "AUCTION_HOUSE_SHOW" then
        ns.ahOpen = true
        ns.RecordGold()
        if WoWFlipDB.settings.panel and ns.ShowPanel then ns.ShowPanel() end
    elseif event == "AUCTION_HOUSE_CLOSED" then
        ns.ahOpen = false
        ns.RecordGold()
        if ns.HidePanel then ns.HidePanel() end
    elseif event == "PLAYER_MONEY" then
        if ns.ahOpen then
            ns.RecordGold()
            if ns.RefreshPanel then ns.RefreshPanel() end
        end
    end
end)

SLASH_WOWFLIP1 = "/flip"
SLASH_WOWFLIP2 = "/wowflip"
SlashCmdList["WOWFLIP"] = function(msg)
    msg = strtrim and strtrim(msg or ""):lower() or (msg or ""):lower()
    local s = WoWFlipDB.settings
    if msg == "" or msg == "show" or msg == "toggle" then
        if ns.TogglePanel then ns.TogglePanel() end
    elseif msg == "auto" then
        s.panel = not s.panel
        ns.Print("Open the panel with the Auction House: " .. (s.panel and "on" or "off"))
    elseif msg == "left" or msg == "right" then
        s.side = msg
        if ns.AnchorPanel then ns.AnchorPanel() end
        ns.Print("Panel docks on the " .. msg .. " of the Auction House.")
    elseif msg == "tooltip" then
        s.tooltip = not s.tooltip
        ns.Print("Tooltip lines: " .. (s.tooltip and "on" or "off"))
    elseif msg == "status" then
        if ns.feed then
            ns.Print("Scan " .. ns.Ago(ns.FeedAge()) .. ", house " .. tostring(ns.feed.house_id) ..
                ", " .. #ns.feed.flips .. " market flips, " .. #ns.feed.snapshot .. " snapshot flips, " ..
                #ns.feed.vendor .. " vendor flips, bankroll " ..
                ns.Money(ns.feed.bankroll) .. " (" .. tostring(ns.feed.profile) .. ").")
        else
            ns.Print("No flip data loaded.")
        end
    else
        ns.Print("/flip  show or hide the panel")
        ns.Print("/flip left | right  dock the panel on that side of the AH")
        ns.Print("/flip auto  open the panel with the AH (on/off)")
        ns.Print("/flip tooltip  flip prices on tooltips (on/off)")
        ns.Print("/flip status  when the data was scanned")
    end
end
