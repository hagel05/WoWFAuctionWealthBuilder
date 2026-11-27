-- WoWFlip: "Collect AH mail" button at the mailbox.
--
-- Takes the items and gold out of Auction House mail (purchases, sales,
-- expired and cancelled auctions), one mail at a time, so bought flips are in
-- your bags ready to list. Mail with cash on delivery is never touched.
local ADDON, ns = ...

local button, collecting
local got = { gold = 0, mails = 0 }
local subjectPatterns

-- Blizzard's AH mail subjects ("Auction won: %s" etc.) as Lua patterns.
local function SubjectPatterns()
    if subjectPatterns then return subjectPatterns end
    subjectPatterns = {}
    for _, name in ipairs({ "AUCTION_WON_MAIL_SUBJECT", "AUCTION_SOLD_MAIL_SUBJECT", "AUCTION_EXPIRED_MAIL_SUBJECT",
        "AUCTION_REMOVED_MAIL_SUBJECT", "AUCTION_OUTBID_MAIL_SUBJECT" }) do
        local fmt = _G[name]
        if type(fmt) == "string" then
            local pattern = fmt:gsub("([%(%)%.%+%-%*%?%[%]%^%$])", "%%%1"):gsub("%%s", ".+")
            subjectPatterns[#subjectPatterns + 1] = "^" .. pattern .. "$"
        end
    end
    return subjectPatterns
end

local function IsAuctionMail(index, subject)
    if GetInboxInvoiceInfo and GetInboxInvoiceInfo(index) then return true end
    if type(subject) ~= "string" then return false end
    for _, p in ipairs(SubjectPatterns()) do
        if subject:match(p) then return true end
    end
    return false
end

-- Index of the last AH mail that has something to take, or nil.
function ns.NextAuctionMail()
    if not GetInboxNumItems then return nil end
    for i = GetInboxNumItems(), 1, -1 do
        local _, _, _, subject, money, cod, _, itemCount = GetInboxHeaderInfo(i)
        if (cod or 0) == 0 and ((money or 0) > 0 or (itemCount or 0) > 0) and IsAuctionMail(i, subject) then
            return i, money or 0, itemCount or 0
        end
    end
    return nil
end

local function CountAuctionMail()
    local n = 0
    if not GetInboxNumItems then return 0 end
    for i = 1, GetInboxNumItems() do
        local _, _, _, subject, money, cod, _, itemCount = GetInboxHeaderInfo(i)
        if (cod or 0) == 0 and ((money or 0) > 0 or (itemCount or 0) > 0) and IsAuctionMail(i, subject) then
            n = n + 1
        end
    end
    return n
end

local function FreeBagSlots()
    if not C_Container or not C_Container.GetContainerNumFreeSlots then return 99 end
    local free = 0
    for bag = 0, (NUM_BAG_SLOTS or 4) do
        free = free + (C_Container.GetContainerNumFreeSlots(bag) or 0)
    end
    return free
end

local function Refresh()
    if not button then return end
    if collecting then
        button:SetText("Collecting...")
        button:SetEnabled(false)
        return
    end
    local n = CountAuctionMail()
    button:SetText(n > 0 and ("Collect AH mail (" .. n .. ")") or "No AH mail")
    button:SetEnabled(n > 0)
end
ns.RefreshMailButton = Refresh

local function Stop(msg)
    collecting = false
    if msg then ns.Print(msg) end
    Refresh()
end

local Step
local function Later(fn)
    if C_Timer and C_Timer.After then C_Timer.After(0.6, fn) else fn() end
end

Step = function()
    if not collecting then return end
    local index, money, items = ns.NextAuctionMail()
    if not index then
        return Stop("Collected " .. got.mails .. " auction mails" ..
            (got.gold > 0 and (" and " .. ns.Money(got.gold)) or "") .. ".")
    end
    if items > 0 and FreeBagSlots() == 0 then
        return Stop("Your bags are full. Make room, then press Collect again.")
    end
    got.mails = got.mails + 1
    got.gold = got.gold + money
    if AutoLootMailItem then
        AutoLootMailItem(index)
    else
        if money > 0 and TakeInboxMoney then TakeInboxMoney(index) end
        if items > 0 and TakeInboxItem then TakeInboxItem(index, 1) end
    end
    Later(Step)
end

function ns.CollectAuctionMail()
    if collecting then return end
    collecting = true
    got.gold, got.mails = 0, 0
    Refresh()
    Step()
end

local function Build()
    local parent = MailFrame or UIParent
    button = CreateFrame("Button", "WoWFlipCollectButton", parent, "UIPanelButtonTemplate")
    button:SetSize(170, 22)
    if MailFrame then
        button:SetPoint("TOPRIGHT", MailFrame, "BOTTOMRIGHT", 0, -2)
    else
        button:SetPoint("CENTER")
    end
    button:SetScript("OnClick", ns.CollectAuctionMail)
    button:SetScript("OnEnter", function(self)
        if not GameTooltip then return end
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        GameTooltip:SetText("Collect AH mail")
        GameTooltip:AddLine("Takes items and gold from Auction House mail: purchases, sales, " ..
            "expired and cancelled auctions. Skips cash-on-delivery mail.", 1, 1, 1, true)
        GameTooltip:Show()
    end)
    button:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
end

local events = CreateFrame("Frame")
events:RegisterEvent("MAIL_SHOW")
events:RegisterEvent("MAIL_CLOSED")
events:RegisterEvent("MAIL_INBOX_UPDATE")
events:RegisterEvent("UI_ERROR_MESSAGE")
events:SetScript("OnEvent", function(_, event, _, message)
    if event == "MAIL_SHOW" then
        if not button then Build() end
        button:Show()
        Refresh()
    elseif event == "MAIL_CLOSED" then
        if collecting then Stop() end
        if button then button:Hide() end
    elseif event == "MAIL_INBOX_UPDATE" then
        if not collecting then Refresh() end
    elseif event == "UI_ERROR_MESSAGE" and collecting then
        if message and (message == ERR_INV_FULL or message == ERR_ITEM_MAX_COUNT) then
            Stop("Stopped: " .. message)
        end
    end
end)
