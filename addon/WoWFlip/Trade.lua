-- WoWFlip: Buy and List with a confirm window.
--
-- Blizzard only lets a purchase or a posting happen from the player's own
-- click, so every one of them is a button press in the confirm window:
--   Stackable goods (commodities): check prices -> "Get exact price" ->
--     Blizzard quotes the total -> "Buy for <total>".
--   Other items: one "Buy this listing" click per listing.
--   Listing: one "Post" click per auction, after showing price, deposit,
--     the AH cut and the expected profit.
-- Limits from the scan are enforced here: never above the flip's max price per
-- unit, never more units than the flip, never more than the per-flip bankroll
-- cap (max_flip_cost), and never more gold than the character has.
local ADDON, ns = ...

local pending -- the one buy or list in progress

local DURATION_INDEX = { [2] = 1, [8] = 2, [24] = 3 } -- auction length in hours -> AH duration option

local function API() return C_AuctionHouse end

local function Hours()
    return (ns.feed and ns.feed.listing_hours) or 24
end

-- Auction length for the listing being set up (the List window can change it).
-- Last length picked in the List window (or /flip length), else the scan's.
local function ListHours()
    local saved = WoWFlipDB and WoWFlipDB.settings and WoWFlipDB.settings.hours
    return (pending and pending.hours) or saved or Hours()
end

local function Duration()
    return DURATION_INDEX[ListHours()] or 3
end

-- Deposit by auction length, as a share of the vendor price (faction AH).
local DEPOSIT_RATE = { [2] = 0.05, [8] = 0.20, [24] = 0.60 }

local NEXT_HOURS = { [24] = 2, [2] = 8, [8] = 24 }

local function Cut()
    return (ns.feed and ns.feed.ah_cut) or 0.05
end

local function Gold()
    local money = GetMoney and GetMoney()
    return type(money) == "number" and money or 0
end

local function ItemName(itemID, fallback)
    if C_Item and C_Item.GetItemNameByID then
        return C_Item.GetItemNameByID(itemID) or fallback or ("item " .. itemID)
    end
    return fallback or ("item " .. itemID)
end

local function Clear()
    pending = nil
end

local function Say(title, body)
    ns.OpenDialog({ title = title, body = body, secondary = "Close", onHide = Clear })
end

-- Ask the AH for the current listings of one item. Whichever results event
-- answers tells us if it is a commodity (stackable) or an item.
local function Search(itemID)
    local api = API()
    if not api or not api.SendSearchQuery or not api.MakeItemKey then
        Say("Can't search", "This client has no Auction House search API.")
        return false
    end
    local sorts = {}
    if Enum and Enum.AuctionHouseSortOrder then
        sorts = { { sortOrder = Enum.AuctionHouseSortOrder.Price, reverseSort = false } }
    end
    pending.stage = "search"
    api.SendSearchQuery(api.MakeItemKey(itemID), sorts, true)
    return true
end

local function Limits(entry)
    local cap = (ns.feed and ns.feed.max_flip_cost) or math.huge
    if cap <= 0 then cap = math.huge end
    return entry.quantity or 0, entry.buy_max or 0, math.min(cap, Gold()), cap
end

-- What stopped a plan from buying anything, in plain words.
local function WhyNothing(cheapest, unitMax, room)
    if not cheapest then return "There are no listings from other players right now." end
    if cheapest > unitMax then
        return "The cheapest is now " .. ns.Money(cheapest) .. " each, above this flip's limit of " ..
            ns.Money(unitMax) .. ". Someone bought the cheap ones or the price rose."
    end
    if room < cheapest then
        return "Not enough gold: you have " .. ns.Money(Gold()) .. " and the flip limit is " ..
            ns.Money((ns.feed and ns.feed.max_flip_cost) or 0) .. "."
    end
    return "Nothing fits this flip's limits."
end

-- Pick listings (sorted cheapest first) within the flip's limits.
-- rows: { unit = copper each, qty = units, ... }; returns chosen rows, qty, cost.
function ns.PlanBuy(rows, limitQty, unitMax, room)
    table.sort(rows, function(a, b) return a.unit < b.unit end)
    local chosen, qty, cost = {}, 0, 0
    for _, r in ipairs(rows) do
        if r.unit > unitMax or qty >= limitQty then break end
        local take = math.min(r.qty, limitQty - qty)
        local affordable = math.floor((room - cost) / r.unit)
        if r.whole then -- an item auction is all or nothing
            if take < r.qty or affordable < r.qty then break end
        else
            take = math.min(take, affordable)
        end
        if take <= 0 then break end
        chosen[#chosen + 1] = { unit = r.unit, qty = take, row = r }
        qty, cost = qty + take, cost + take * r.unit
        if take < r.qty then break end
    end
    return chosen, qty, cost
end

local function RecordBuy(itemID, qty, cost)
    local entry = pending and pending.entry or {}
    local rec = WoWFlipDB.bought[itemID] or { qty = 0, cost = 0 }
    rec.qty = rec.qty + qty
    rec.cost = rec.cost + cost
    rec.name = entry.name or rec.name
    rec.relist = entry.relist or rec.relist
    rec.vendor = entry.vendor_price ~= nil or nil
    rec.at = ns.Now()
    WoWFlipDB.bought[itemID] = rec
    if pending then
        pending.boughtQty = (pending.boughtQty or 0) + qty
        pending.spent = (pending.spent or 0) + cost
    end
end

local function FinishBuy()
    local p = pending
    if not p then return end
    if (p.boughtQty or 0) > 0 then
        if ns.feed and ns.IsDone and not ns.IsDone(p.itemID) then ns.ToggleDone(p.itemID) end
        local where = p.entry.vendor_price and "then sell them to any vendor." or
            "then list them from the Sell tab."
        Say("Bought " .. p.name, "Bought " .. p.boughtQty .. " for " .. ns.Money(p.spent) .. ".\n\n" ..
            "They arrive in your mailbox: use Collect AH mail there, " .. where)
    else
        ns.CloseDialog()
    end
    if ns.RefreshPanel then ns.RefreshPanel() end
end

---------------------------------------------------------------------------
-- Buying
---------------------------------------------------------------------------

function ns.StartBuy(entry)
    if not ns.ahOpen then
        ns.Print("Open the Auction House first.")
        return
    end
    pending = { mode = "buy", entry = entry, itemID = entry.item_id, name = ItemName(entry.item_id, entry.name) }
    ns.OpenDialog({ title = "Buy " .. pending.name, body = "Checking current prices...", onHide = function()
        if pending and pending.stage == "quote" and API().CancelCommoditiesPurchase then
            API().CancelCommoditiesPurchase()
        end
        Clear()
    end })
    Search(entry.item_id)
end

local function ShowCommodityPlan(itemID)
    local p, api = pending, API()
    local limitQty, unitMax, room = Limits(p.entry)
    local rows, cheapest = {}, nil
    for i = 1, (api.GetNumCommoditySearchResults(itemID) or 0) do
        local r = api.GetCommoditySearchResultInfo(itemID, i)
        if r then
            local others = (r.quantity or 0) - (r.numOwnerItems or 0)
            if others > 0 then
                rows[#rows + 1] = { unit = r.unitPrice, qty = others }
                cheapest = cheapest and math.min(cheapest, r.unitPrice) or r.unitPrice
            end
        end
    end
    local _, qty, cost = ns.PlanBuy(rows, limitQty, unitMax, room)
    if qty == 0 then
        return Say("Nothing to buy", WhyNothing(cheapest, unitMax, room))
    end
    p.qty, p.estimate, p.stage = qty, cost, "planned"
    local body = "Buy " .. qty .. " x " .. p.name .. "\n" ..
        "About " .. ns.Money(math.floor(cost / qty + 0.5)) .. " each (this flip pays at most " ..
        ns.Money(unitMax) .. ")\n" ..
        "Estimated total: " .. ns.Money(cost) .. "\n" ..
        "Your gold: " .. ns.Money(Gold()) .. ", after: about " .. ns.Money(Gold() - cost) .. "\n\n" ..
        "Next, Blizzard quotes the exact total before anything is spent."
    if qty < limitQty then
        body = body .. "\n(Only " .. qty .. " of the " .. limitQty .. " units fit the price and gold limits.)"
    end
    ns.OpenDialog({ title = "Buy " .. p.name, body = body, primary = "Get exact price", onPrimary = function()
        if not pending or pending.stage ~= "planned" then return end
        pending.stage = "quote"
        ns.OpenDialog({ title = "Buy " .. pending.name, body = "Asking Blizzard for the exact total...",
            primary = "Buy", primaryEnabled = false, onHide = function()
                if pending and pending.stage == "quote" and API().CancelCommoditiesPurchase then
                    API().CancelCommoditiesPurchase()
                end
                Clear()
            end })
        API().StartCommoditiesPurchase(pending.itemID, pending.qty)
    end, onHide = Clear })
end

local function OnCommodityQuote(unitPrice, totalPrice)
    local p = pending
    if not p or p.stage ~= "quote" then return end
    local _, unitMax, room = Limits(p.entry)
    local limit = math.min(p.qty * unitMax, room)
    if not totalPrice or totalPrice > limit then
        p.stage = "cancelled"
        if API().CancelCommoditiesPurchase then API().CancelCommoditiesPurchase() end
        return Say("Price went up", "Blizzard's total is " .. ns.Money(totalPrice or 0) .. " for " .. p.qty ..
            ", over this flip's limit of " .. ns.Money(limit) .. ". Nothing was bought.")
    end
    p.stage = "quoted"
    p.total = totalPrice
    local body = "Buy " .. p.qty .. " x " .. p.name .. "\n" ..
        "Price each: " .. ns.Money(unitPrice) .. "\n" ..
        "|cffffd700Total: " .. ns.Money(totalPrice, true) .. "|r\n" ..
        "Your gold after: " .. ns.Money(Gold() - totalPrice)
    ns.OpenDialog({ title = "Confirm purchase", body = body, primary = "Buy for " .. ns.Money(totalPrice, true),
        onPrimary = function()
            if not pending or pending.stage ~= "quoted" then return end
            pending.stage = "buying"
            ns.OpenDialog({ title = "Buying " .. pending.name, body = "Buying...", secondary = "Close" })
            API().ConfirmCommoditiesPurchase(pending.itemID, pending.qty)
        end,
        onHide = function()
            if pending and pending.stage == "quoted" and API().CancelCommoditiesPurchase then
                API().CancelCommoditiesPurchase()
            end
            if pending and pending.stage ~= "buying" then Clear() end
        end })
end

local function ShowItemStep()
    local p = pending
    local step = p.plan[p.index]
    if not step then return FinishBuy() end
    if Gold() < step.cost then
        return Say("Not enough gold", "The next listing costs " .. ns.Money(step.cost) .. " and you have " ..
            ns.Money(Gold()) .. ".")
    end
    local remaining = 0
    for i = p.index, #p.plan do remaining = remaining + p.plan[i].cost end
    local body = "Listing " .. p.index .. " of " .. #p.plan .. ": " .. step.qty .. " x " .. p.name .. "\n" ..
        "|cffffd700Price: " .. ns.Money(step.cost, true) .. "|r (" .. ns.Money(step.unit) .. " each)\n" ..
        "Left to buy in this flip: " .. ns.Money(remaining) .. "\n" ..
        "Your gold after this one: " .. ns.Money(Gold() - step.cost)
    if (p.boughtQty or 0) > 0 then
        body = body .. "\nBought so far: " .. p.boughtQty .. " for " .. ns.Money(p.spent)
    end
    p.stage = "item_ready"
    ns.OpenDialog({ title = "Buy " .. p.name, body = body, primary = "Buy for " .. ns.Money(step.cost, true),
        secondary = "Stop", onPrimary = function()
            if not pending or pending.stage ~= "item_ready" then return end
            pending.stage = "placing"
            API().PlaceBid(step.auctionID, step.cost)
        end, onHide = function()
            if pending and pending.stage ~= "placing" then
                local done = pending
                Clear()
                if (done.boughtQty or 0) > 0 and ns.RefreshPanel then ns.RefreshPanel() end
            end
        end })
end

local function ShowItemPlan(itemKey)
    local p, api = pending, API()
    local limitQty, unitMax, room = Limits(p.entry)
    local rows, cheapest = {}, nil
    for i = 1, (api.GetNumItemSearchResults(itemKey) or 0) do
        local r = api.GetItemSearchResultInfo(itemKey, i)
        if r and r.buyoutAmount and r.buyoutAmount > 0 and not r.containsOwnerItem and (r.quantity or 0) > 0 then
            local unit = math.ceil(r.buyoutAmount / r.quantity)
            rows[#rows + 1] = { unit = unit, qty = r.quantity, whole = true, auctionID = r.auctionID,
                buyout = r.buyoutAmount }
            cheapest = cheapest and math.min(cheapest, unit) or unit
        end
    end
    local chosen = ns.PlanBuy(rows, limitQty, unitMax, room)
    if #chosen == 0 then
        return Say("Nothing to buy", WhyNothing(cheapest, unitMax, room))
    end
    p.plan = {}
    for _, c in ipairs(chosen) do
        p.plan[#p.plan + 1] = { auctionID = c.row.auctionID, cost = c.row.buyout, qty = c.qty, unit = c.unit }
    end
    p.index = 1
    ShowItemStep()
end

local function OnItemBought(auctionID)
    local p = pending
    if not p or p.stage ~= "placing" then return end
    local step = p.plan[p.index]
    if auctionID and step.auctionID ~= auctionID then return end
    RecordBuy(p.itemID, step.qty, step.cost)
    p.index = p.index + 1
    ShowItemStep()
end

local function OnCommodityBought()
    local p = pending
    if not p or p.stage ~= "buying" then return end
    RecordBuy(p.itemID, p.qty, p.total or p.estimate)
    FinishBuy()
end

---------------------------------------------------------------------------
-- Listing
---------------------------------------------------------------------------

local function BagCount(itemID)
    if C_Item and C_Item.GetItemCount then return C_Item.GetItemCount(itemID) or 0 end
    if GetItemCount then return GetItemCount(itemID) or 0 end
    return 0
end

-- Bag stacks of an item: { {bag, slot, count}, ... }
function ns.FindStacks(itemID)
    local out = {}
    if not C_Container then return out end
    local lastBag = (NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4)
    for bag = 0, lastBag do
        for slot = 1, (C_Container.GetContainerNumSlots(bag) or 0) do
            local info = C_Container.GetContainerItemInfo(bag, slot)
            if info and info.itemID == itemID and not info.isLocked and not info.isBound then
                out[#out + 1] = { bag = bag, slot = slot, count = info.stackCount or 1 }
            end
        end
    end
    return out
end

local function Location(stack)
    if ItemLocation and ItemLocation.CreateFromBagAndSlot then
        return ItemLocation:CreateFromBagAndSlot(stack.bag, stack.slot)
    end
    return { bagID = stack.bag, slotIndex = stack.slot }
end

-- Rows for the Sell tab: flip items you bought through the panel that are in your bags.
function ns.SellList()
    local out = {}
    for itemID, rec in pairs(WoWFlipDB.bought) do
        if not rec.vendor and (rec.qty or 0) > 0 then
            local have = BagCount(itemID)
            if have > 0 then
                local flip = ns.flipsByItem[itemID] or (ns.snapshotByItem and ns.snapshotByItem[itemID])
                out[#out + 1] = {
                    item_id = itemID,
                    name = rec.name or ItemName(itemID),
                    quantity = math.min(have, rec.qty),
                    paid_each = math.floor(rec.cost / rec.qty + 0.5),
                    relist = (flip and flip.relist) or rec.relist or 0,
                    sell = true,
                }
            end
        end
    end
    table.sort(out, function(a, b) return a.name < b.name end)
    return out
end

-- The lowest price that still covers what you paid, the deposit and the cut.
function ns.BreakEven(paidEach, depositEach, cut)
    return math.ceil((paidEach + depositEach) / (1 - cut))
end

function ns.StartList(entry)
    if not ns.ahOpen then
        ns.Print("Open the Auction House first.")
        return
    end
    local stacks = ns.FindStacks(entry.item_id)
    if #stacks == 0 then
        ns.Print("No unlocked " .. entry.name .. " in your bags. Collect it from the mailbox first.")
        return
    end
    pending = { mode = "sell", entry = entry, itemID = entry.item_id, name = ItemName(entry.item_id, entry.name),
        stacks = stacks }
    ns.OpenDialog({ title = "List " .. pending.name, body = "Checking current prices...", onHide = Clear })
    Search(entry.item_id)
end

local function Deposit(commodity, stack, qty)
    local api = API()
    local ok, value
    if commodity and api.CalculateCommodityDeposit then
        ok, value = pcall(api.CalculateCommodityDeposit, pending.itemID, Duration(), qty)
    elseif not commodity and api.CalculateItemDeposit then
        ok, value = pcall(api.CalculateItemDeposit, Location(stack), Duration(), qty)
    end
    if ok and type(value) == "number" then return value end
    -- Fallback: the faction AH's rates, as a share of the vendor price.
    local rate = DEPOSIT_RATE[ListHours()] or 0.60
    local vendor = 0
    if C_Item and C_Item.GetItemInfo then
        vendor = select(11, C_Item.GetItemInfo(pending.itemID)) or 0
    end
    return math.floor(rate * vendor * qty + 0.5)
end

local function ShowListStep()
    local p = pending
    local commodity = p.commodity
    local stack, qty
    if commodity then
        stack, qty = p.stacks[1], math.min(p.entry.quantity, BagCount(p.itemID))
    else
        stack = p.stacks[p.index]
        if not stack or (p.postedQty or 0) >= p.entry.quantity then
            return Say("Listed " .. p.name, "Posted " .. (p.postedQty or 0) .. " for " .. ListHours() .. " hours. " ..
                "Sale gold arrives by mail about an hour after each sale.")
        end
        qty = math.min(stack.count, p.entry.quantity - (p.postedQty or 0))
        if qty < stack.count then
            return Say("Split the stack first", "This stack has " .. stack.count .. " but the flip has " .. qty ..
                " left to list. Split it in your bags, then press List again.")
        end
    end
    local cut = Cut()
    local deposit = Deposit(commodity, stack, qty)
    local floor = ns.BreakEven(p.entry.paid_each, deposit / qty, cut)
    local price = p.entry.relist
    local note = ""
    if p.lowest and p.lowest < price then
        local undercut = math.max(p.lowest - 1, floor)
        note = "\nLowest listed now: " .. ns.Money(p.lowest) .. ", so priced at " .. ns.Money(undercut) ..
            (undercut > p.lowest - 1 and " (your break-even; it may sell slowly)" or "")
        price = undercut
    elseif p.lowest then
        note = "\nLowest listed now: " .. ns.Money(p.lowest)
    end
    if price < floor then price = floor end
    local gross = price * qty
    local fee = math.floor(gross * cut + 0.5)
    local receive = gross - fee
    local paid = p.entry.paid_each * qty
    local profit = receive - deposit - paid
    p.price, p.qty, p.stack, p.stage = price, qty, stack, "list_ready"
    local hours = ListHours()
    local body = "List " .. qty .. " x " .. p.name .. " for " .. hours .. " hours" ..
        (commodity and "" or (" (auction " .. p.index .. " of " .. #p.stacks .. ")")) .. "\n" ..
        "Price each: " .. ns.Money(price) .. note .. "\n" ..
        "Total if it all sells: " .. ns.Money(gross) .. "\n" ..
        "Deposit now: " .. ns.Money(deposit) .. " (kept by the AH if it doesn't sell)\n" ..
        "AH cut " .. math.floor(cut * 100 + 0.5) .. "%: " .. ns.Money(fee) .. "\n" ..
        "You receive: " .. ns.Money(receive) .. "\n" ..
        "|cffffd700Profit vs the " .. ns.Money(paid, true) .. " you paid: " .. ns.Money(profit, true) .. "|r\n" ..
        "|cff9d9d9dSame price: the newest listing sells first, so relist when you're back to stay in front.|r"
    ns.OpenDialog({ title = "List " .. p.name, body = body, primary = "Post (" .. ns.Money(deposit, true) .. " deposit)",
        primaryEnabled = Gold() >= deposit,
        extra = "Length: " .. hours .. "h (change)", onExtra = function()
            if not pending or pending.stage ~= "list_ready" then return end
            pending.hours = NEXT_HOURS[ListHours()] or 24
            WoWFlipDB.settings.hours = pending.hours -- remembered for the next listing
            ShowListStep()
        end,
        onPrimary = function()
            if not pending or pending.stage ~= "list_ready" then return end
            pending.stage = "posting"
            local api = API()
            if pending.commodity then
                api.PostCommodity(Location(pending.stack), Duration(), pending.qty, pending.price)
            else
                api.PostItem(Location(pending.stack), Duration(), pending.qty, nil, pending.price * pending.qty)
            end
        end, onHide = function()
            if pending and pending.stage ~= "posting" then Clear() end
        end })
end

local function OnPosted()
    local p = pending
    if not p or p.stage ~= "posting" then return end
    local rec = WoWFlipDB.bought[p.itemID]
    if rec then
        local each = rec.qty > 0 and rec.cost / rec.qty or 0
        rec.qty = math.max(0, rec.qty - p.qty)
        rec.cost = math.max(0, math.floor(each * rec.qty + 0.5))
        if rec.qty == 0 then WoWFlipDB.bought[p.itemID] = nil end
    end
    p.postedQty = (p.postedQty or 0) + p.qty
    if p.commodity then
        Say("Listed " .. p.name, "Posted " .. p.qty .. " at " .. ns.Money(p.price) .. " each for " .. ListHours() ..
            " hours. Sale gold arrives by mail about an hour after each sale.")
    else
        p.index = p.index + 1
        ShowListStep()
    end
    if ns.RefreshPanel then ns.RefreshPanel() end
end

---------------------------------------------------------------------------
-- Events
---------------------------------------------------------------------------

local function OnResults(commodity, itemID, itemKey)
    local p = pending
    if not p or p.stage ~= "search" or itemID ~= p.itemID then return end
    p.commodity = commodity
    if p.mode == "buy" then
        if commodity then ShowCommodityPlan(itemID) else ShowItemPlan(itemKey) end
        return
    end
    -- Listing: find the cheapest price other players ask.
    local api, lowest = API(), nil
    if commodity then
        for i = 1, (api.GetNumCommoditySearchResults(itemID) or 0) do
            local r = api.GetCommoditySearchResultInfo(itemID, i)
            if r and (r.quantity or 0) > (r.numOwnerItems or 0) then
                lowest = lowest and math.min(lowest, r.unitPrice) or r.unitPrice
            end
        end
    else
        for i = 1, (api.GetNumItemSearchResults(itemKey) or 0) do
            local r = api.GetItemSearchResultInfo(itemKey, i)
            if r and r.buyoutAmount and not r.containsOwnerItem and (r.quantity or 0) > 0 then
                local unit = math.ceil(r.buyoutAmount / r.quantity)
                lowest = lowest and math.min(lowest, unit) or unit
            end
        end
    end
    p.lowest, p.index = lowest, 1
    ShowListStep()
end

local function ErrorText(code)
    if AuctionHouseUtil and AuctionHouseUtil.GetErrorText then
        local ok, text = pcall(AuctionHouseUtil.GetErrorText, code)
        if ok and text then return text end
    end
    return "The Auction House refused it (error " .. tostring(code) .. ")."
end

local events = CreateFrame("Frame")
for _, e in ipairs({
    "COMMODITY_SEARCH_RESULTS_UPDATED", "ITEM_SEARCH_RESULTS_UPDATED", "COMMODITY_PRICE_UPDATED",
    "COMMODITY_PRICE_UNAVAILABLE", "COMMODITY_PURCHASE_SUCCEEDED", "COMMODITY_PURCHASE_FAILED",
    "AUCTION_HOUSE_PURCHASE_COMPLETED", "AUCTION_HOUSE_AUCTION_CREATED", "AUCTION_HOUSE_SHOW_ERROR",
    "AUCTION_HOUSE_POST_WARNING", "AUCTION_HOUSE_CLOSED",
}) do
    events:RegisterEvent(e)
end
events:SetScript("OnEvent", function(_, event, a, b)
    if not pending then return end
    if event == "COMMODITY_SEARCH_RESULTS_UPDATED" then
        OnResults(true, a, nil)
    elseif event == "ITEM_SEARCH_RESULTS_UPDATED" then
        OnResults(false, type(a) == "table" and a.itemID or nil, a)
    elseif event == "COMMODITY_PRICE_UPDATED" then
        OnCommodityQuote(a, b)
    elseif event == "COMMODITY_PRICE_UNAVAILABLE" then
        Say("Price unavailable", "Blizzard could not quote a price for " .. pending.name .. ". Nothing was bought.")
    elseif event == "COMMODITY_PURCHASE_SUCCEEDED" then
        OnCommodityBought()
    elseif event == "COMMODITY_PURCHASE_FAILED" then
        Say("Purchase failed", "Nothing was bought; the listings may have just sold. Press Buy to check again.")
    elseif event == "AUCTION_HOUSE_PURCHASE_COMPLETED" then
        OnItemBought(a)
    elseif event == "AUCTION_HOUSE_AUCTION_CREATED" then
        OnPosted()
    elseif event == "AUCTION_HOUSE_POST_WARNING" then
        local p = pending
        if p.stage ~= "posting" then return end
        local api = API()
        p.stage = "post_warning"
        ns.OpenDialog({ title = "Blizzard asks to confirm", body = "Blizzard flagged this price as unusual. " ..
            "Post " .. p.qty .. " x " .. p.name .. " at " .. ns.Money(p.price) .. " each anyway?",
            primary = "Post anyway", onPrimary = function()
                if not pending or pending.stage ~= "post_warning" then return end
                pending.stage = "posting"
                if pending.commodity and api.ConfirmPostCommodity then
                    api.ConfirmPostCommodity(Location(pending.stack), Duration(), pending.qty, pending.price)
                elseif api.ConfirmPostItem then
                    api.ConfirmPostItem(Location(pending.stack), Duration(), pending.qty, nil,
                        pending.price * pending.qty)
                end
            end, onHide = function()
                if pending and pending.stage ~= "posting" then Clear() end
            end })
    elseif event == "AUCTION_HOUSE_SHOW_ERROR" then
        local p = pending
        if p.stage == "placing" then
            -- That listing is gone or changed: skip it and offer the next one.
            p.index = p.index + 1
            ns.Print(ErrorText(a) .. " Skipping that listing.")
            ShowItemStep()
        elseif p.stage == "posting" or p.stage == "buying" or p.stage == "quote" then
            Say("Not done", ErrorText(a))
        end
    elseif event == "AUCTION_HOUSE_CLOSED" then
        ns.CloseDialog()
        Clear()
    end
end)

function ns.TradePending()
    return pending
end
