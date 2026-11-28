-- WoWFlip: the Flips panel docked beside the Auction House window.
--
-- Built from plain frames and font strings (no Blizzard scroll templates), so
-- it does not depend on Auction House internals that may change. Each row has a
-- Buy (or, on the Sell tab, List) button that opens a confirm window; the
-- player's click there is what spends gold (see Trade.lua).
local ADDON, ns = ...

local ROWS, ROW_H, WIDTH = 12, 34, 340
local panel, rows, offset = nil, {}, 0

local function List()
    if not ns.feed then return {} end
    local tab = WoWFlipDB.settings.tab
    if tab == "sell" then return ns.SellList and ns.SellList() or {} end
    local src = (tab == "vendor" and ns.feed.vendor) or (tab == "snapshot" and ns.feed.snapshot) or ns.feed.flips
    local out = {}
    for _, entry in ipairs(src) do
        if not ns.IsDone(entry.item_id) then out[#out + 1] = entry end
    end
    return out
end
ns.PanelList = List

-- Search Blizzard's Auction House for an item so the player can check it and buy.
function ns.SearchAH(entry)
    local name = entry.name
    if C_Item and C_Item.GetItemNameByID then
        name = C_Item.GetItemNameByID(entry.item_id) or name
    end
    local ah = AuctionHouseFrame
    if ah and ah.SearchBar and ah.SearchBar.SetSearchText and ah.SearchBar.StartSearch then
        if ah.SetDisplayMode and AuctionHouseFrameDisplayMode and AuctionHouseFrameDisplayMode.Buy then
            pcall(ah.SetDisplayMode, ah, AuctionHouseFrameDisplayMode.Buy)
        end
        ah.SearchBar:SetSearchText(name)
        ah.SearchBar:StartSearch()
        return true
    end
    if C_AuctionHouse and C_AuctionHouse.SendBrowseQuery then
        C_AuctionHouse.SendBrowseQuery({ searchString = name, sorts = {}, filters = {}, itemClassFilters = {} })
        return true
    end
    ns.Print("Could not start a search; type \"" .. name .. "\" into the AH search box.")
    return false
end

local TAGS = { early = "  |cffffd040early|r", snapshot = "  |cffffa040risky|r" }

local function RowText(entry)
    local market = WoWFlipDB.settings.tab ~= "vendor"
    local line1, line2
    if entry.sell then
        line1 = entry.name .. "  x" .. entry.quantity .. " in bags"
        line2 = "Paid " .. ns.Money(entry.paid_each) .. " each, list at ~" .. ns.Money(entry.relist)
        return line1, line2
    elseif market then
        line1 = entry.name .. "  |cff40ff40+" .. ns.Money(entry.profit, true) .. "|r" .. (TAGS[entry.kind] or "")
        line2 = "Buy " .. entry.quantity .. " up to " .. ns.Money(entry.buy_max) .. ", relist " .. ns.Money(entry.relist)
    else
        line1 = entry.name .. "  |cff40ff40+" .. ns.Money(entry.profit, true) .. "|r"
        line2 = "Buy " .. entry.quantity .. " under " .. ns.Money(entry.vendor_price) .. ", sell to a vendor"
    end
    local money = GetMoney and GetMoney()
    if type(money) == "number" and entry.cost and entry.cost > money then
        line2 = line2 .. "  |cffff6060(costs " .. ns.Money(entry.cost, true) .. ")|r"
    end
    return line1, line2
end

function ns.RefreshPanel()
    if not panel or not panel:IsShown() then return end
    local list = List()
    offset = math.max(0, math.min(offset, #list - ROWS))
    local tab = WoWFlipDB.settings.tab
    local market = tab ~= "vendor"
    -- Counts on the tabs, so flips on another tab are easy to spot.
    local function Count(src)
        local n = 0
        for _, e in ipairs(src or {}) do
            if not ns.IsDone(e.item_id) then n = n + 1 end
        end
        return n
    end
    local feed = ns.feed or {}
    panel.marketTab:SetText("Market (" .. Count(feed.flips) .. ")")
    panel.snapshotTab:SetText("Snapshot (" .. Count(feed.snapshot) .. ")")
    panel.vendorTab:SetText("Vendor (" .. Count(feed.vendor) .. ")")
    local sellCount = ns.SellList and #ns.SellList() or 0
    panel.sellTab:SetText(sellCount > 0 and ("Sell (" .. sellCount .. ")") or "Sell")
    panel.marketTab:SetEnabled(tab ~= "market")
    panel.snapshotTab:SetEnabled(tab ~= "snapshot")
    panel.vendorTab:SetEnabled(tab ~= "vendor")
    panel.sellTab:SetEnabled(tab ~= "sell")
    local noun = (tab == "vendor" and " vendor flips") or (tab == "snapshot" and " snapshot flips (riskier)") or
        (tab == "sell" and " to list") or " flips"

    if not ns.feed then
        panel.status:SetText("No flip data yet. Run the sync helper, then /reload.")
    else
        local age = ns.Ago(ns.FeedAge())
        local text = "Scanned " .. age .. "  ·  " .. #list .. noun
        if ns.FeedIsOld() then
            text = "|cffff6060Scanned " .. age .. ". /reload after the next sync.|r"
        end
        panel.status:SetText(text)
    end

    for i = 1, ROWS do
        local row, entry = rows[i], list[offset + i]
        row.entry = entry
        if entry then
            local l1, l2 = RowText(entry)
            row.line1:SetText(l1)
            row.line2:SetText(l2)
            row.action:SetText(entry.sell and "List" or "Buy")
            row:Show()
        else
            row:Hide()
        end
    end
    panel.empty:SetText(tab == "sell" and "Nothing to list. Buy flips here, then collect them from the mailbox."
        or "Nothing passes the rules this hour.")
    panel.empty:SetShown((ns.feed ~= nil or tab == "sell") and #list == 0)
end

function ns.AnchorPanel()
    if not panel then return end
    panel:ClearAllPoints()
    local ah = AuctionHouseFrame
    if ah and ah:IsShown() then
        if WoWFlipDB.settings.side == "left" then
            panel:SetPoint("TOPRIGHT", ah, "TOPLEFT", -2, 0)
        else
            panel:SetPoint("TOPLEFT", ah, "TOPRIGHT", 2, 0)
        end
    else
        panel:SetPoint("CENTER", UIParent, "CENTER", 0, 0)
    end
end

local function OnRowClick(row, button)
    if not row.entry then return end
    if button == "RightButton" then
        ns.ToggleDone(row.entry.item_id)
        ns.RefreshPanel()
    else
        ns.SearchAH(row.entry)
    end
end

local function OnRowEnter(row)
    if not row.entry or not GameTooltip then return end
    GameTooltip:SetOwner(row, "ANCHOR_RIGHT")
    if GameTooltip.SetItemByID then
        GameTooltip:SetItemByID(row.entry.item_id)
    else
        GameTooltip:SetText(row.entry.name)
    end
    if row.entry.sell then
        GameTooltip:AddLine("List: shows price, deposit, AH cut and profit, then posts on your click", 0.6, 0.8, 1, true)
    else
        GameTooltip:AddLine("Buy: checks live prices and shows the exact total before you pay", 0.6, 0.8, 1, true)
        GameTooltip:AddLine("Click: search the Auction House", 0.6, 0.8, 1)
        GameTooltip:AddLine("Right-click: cross off until the next scan", 0.6, 0.8, 1)
    end
    if row.entry.kind == "snapshot" then
        GameTooltip:AddLine("Riskier: priced against the other listings (" .. ns.Money(row.entry.reference) ..
            ") with no sales history, so it may sell slowly.", 1, 0.63, 0.25, true)
    elseif row.entry.kind == "early" then
        GameTooltip:AddLine("Early: under a week of price history, so stricter rules applied.", 1, 0.82, 0.25, true)
    end
    if WoWFlipDB.settings.tab ~= "vendor" and row.entry.buys then
        GameTooltip:AddLine("Listings to buy:", 1, 0.82, 0)
        for _, b in ipairs(row.entry.buys) do
            GameTooltip:AddLine(b[2] .. " @ " .. ns.Money(b[1]), 1, 1, 1)
        end
    end
    GameTooltip:Show()
end

local function OnRowLeave()
    if GameTooltip then GameTooltip:Hide() end
end

local function Build()
    panel = CreateFrame("Frame", "WoWFlipPanel", UIParent, "BackdropTemplate")
    panel:SetSize(WIDTH, 74 + ROWS * ROW_H)
    panel:SetFrameStrata("HIGH")
    panel:SetClampedToScreen(true)
    if panel.SetBackdrop then
        panel:SetBackdrop({
            bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
            edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
            tile = true, tileSize = 16, edgeSize = 16,
            insets = { left = 4, right = 4, top = 4, bottom = 4 },
        })
        panel:SetBackdropColor(0.05, 0.05, 0.07, 0.94)
    end
    panel:EnableMouseWheel(true)
    panel:SetScript("OnMouseWheel", function(_, delta)
        offset = math.max(0, offset - delta * 3)
        ns.RefreshPanel()
    end)
    panel:Hide()

    local title = panel:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    title:SetPoint("TOPLEFT", 12, -10)
    title:SetText("Flips")

    local close = CreateFrame("Button", nil, panel, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", -2, -2)
    close:SetScript("OnClick", function() panel:Hide() end)

    local function Tab(label, key, x)
        local b = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
        b:SetSize(80, 20)
        -- Small font so labels with counts, e.g. "Snapshot (12)", fit.
        b:SetNormalFontObject("GameFontNormalSmall")
        b:SetHighlightFontObject("GameFontHighlightSmall")
        b:SetDisabledFontObject("GameFontDisableSmall")
        b:SetPoint("TOPLEFT", x, -34)
        b:SetText(label)
        b:SetScript("OnClick", function()
            WoWFlipDB.settings.tab = key
            offset = 0
            ns.RefreshPanel()
        end)
        return b
    end
    panel.marketTab = Tab("Market", "market", 10)
    panel.snapshotTab = Tab("Snapshot", "snapshot", 91)
    panel.vendorTab = Tab("Vendor", "vendor", 172)
    panel.sellTab = Tab("Sell", "sell", 253)

    panel.status = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    panel.status:SetPoint("TOPLEFT", 12, -58)
    panel.status:SetWidth(WIDTH - 24)
    panel.status:SetJustifyH("LEFT")

    panel.empty = panel:CreateFontString(nil, "OVERLAY", "GameFontDisable")
    panel.empty:SetPoint("TOP", 0, -90)
    panel.empty:SetText("Nothing passes the rules this hour.")

    for i = 1, ROWS do
        local row = CreateFrame("Button", nil, panel)
        row:SetSize(WIDTH - 20, ROW_H - 2)
        row:SetPoint("TOPLEFT", 10, -72 - (i - 1) * ROW_H)
        row:RegisterForClicks("LeftButtonUp", "RightButtonUp")
        local hl = row:CreateTexture(nil, "HIGHLIGHT")
        hl:SetAllPoints()
        hl:SetColorTexture(1, 1, 1, 0.08)
        row.line1 = row:CreateFontString(nil, "OVERLAY", "GameFontNormal")
        row.line1:SetPoint("TOPLEFT", 2, -2)
        row.line1:SetWidth(WIDTH - 78)
        row.line1:SetJustifyH("LEFT")
        row.line2 = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        row.line2:SetPoint("TOPLEFT", row.line1, "BOTTOMLEFT", 0, -2)
        row.line2:SetWidth(WIDTH - 78)
        row.line2:SetJustifyH("LEFT")
        row.action = CreateFrame("Button", nil, row, "UIPanelButtonTemplate")
        row.action:SetSize(50, 20)
        row.action:SetPoint("RIGHT", row, "RIGHT", -2, 0)
        row.action:SetText("Buy")
        row.action:SetScript("OnClick", function()
            local entry = row.entry
            if not entry then return end
            if entry.sell then ns.StartList(entry) else ns.StartBuy(entry) end
        end)
        row:SetScript("OnClick", OnRowClick)
        row:SetScript("OnEnter", OnRowEnter)
        row:SetScript("OnLeave", OnRowLeave)
        rows[i] = row
    end
end

function ns.ShowPanel()
    if not panel then Build() end
    ns.AnchorPanel()
    panel:Show()
    ns.RefreshPanel()
end

function ns.HidePanel()
    if panel then panel:Hide() end
end

function ns.TogglePanel()
    if panel and panel:IsShown() then ns.HidePanel() else ns.ShowPanel() end
end
