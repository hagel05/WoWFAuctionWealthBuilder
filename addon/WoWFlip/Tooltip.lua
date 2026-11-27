-- WoWFlip: flip prices on item tooltips.
local ADDON, ns = ...

local GREEN, GREY, ORANGE = "|cff40ff40", "|cff9d9d9d", "|cffffa040"

-- Lines to add for an item id, as a list of strings (used by tests too).
function ns.TooltipLines(itemID)
    local lines = {}
    if not itemID or not ns.feed then return lines end
    local f = ns.flipsByItem[itemID]
    if f then
        lines[#lines + 1] = GREEN .. (f.kind == "early" and "Flip (early):|r" or "Flip:|r") .. " buy up to " .. ns.Money(f.buy_max) .. " each (" .. f.quantity ..
            "), relist at " .. ns.Money(f.relist)
        local speed = f.days_to_sell and (", sells in ~" .. f.days_to_sell .. " days") or ""
        lines[#lines + 1] = GREY .. "Profit about " .. ns.Money(f.profit, true) .. " after fees" .. speed .. "|r"
    end
    local s = ns.snapshotByItem[itemID]
    if s and not f then
        lines[#lines + 1] = ORANGE .. "Snapshot flip (riskier):|r buy up to " .. ns.Money(s.buy_max) .. " each (" ..
            s.quantity .. "), relist at " .. ns.Money(s.relist)
        lines[#lines + 1] = GREY .. "Others list at " .. ns.Money(s.reference or 0, true) ..
            "; no sales history yet, so it may sell slowly|r"
    end
    local v = ns.vendorByItem[itemID]
    if v then
        lines[#lines + 1] = GREEN .. "Vendor flip:|r anything under " .. ns.Money(v.vendor_price) ..
            " (vendor pays that)"
    end
    local p = ns.feed.prices[itemID]
    if p then
        lines[#lines + 1] = GREY .. "Market value " .. ns.Money(p[1], true) .. ", about " .. p[2] .. " sold a day|r"
    end
    return lines
end

local function AddLines(tooltip, itemID)
    if not WoWFlipDB or not WoWFlipDB.settings.tooltip then return end
    if not tooltip or not tooltip.AddLine then return end
    local lines = ns.TooltipLines(itemID)
    if #lines == 0 then return end
    for _, line in ipairs(lines) do tooltip:AddLine(line, 1, 1, 1) end
    if tooltip.Show then tooltip:Show() end
end

-- Modern clients (WoW Forever uses the Mainline API) route every item
-- tooltip through TooltipDataProcessor; older ones fire OnTooltipSetItem.
if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType then
    TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(tooltip, data)
        local id = type(data) == "table" and type(data.id) == "number" and data.id or nil
        if not id and tooltip and tooltip.GetItem then
            local _, link = tooltip:GetItem()
            id = ns.ItemIDFromLink(link)
        end
        AddLines(tooltip, id)
    end)
elseif GameTooltip and GameTooltip.HookScript then
    local function OnSetItem(tooltip)
        local _, link = tooltip:GetItem()
        AddLines(tooltip, ns.ItemIDFromLink(link))
    end
    GameTooltip:HookScript("OnTooltipSetItem", OnSetItem)
    if ItemRefTooltip then ItemRefTooltip:HookScript("OnTooltipSetItem", OnSetItem) end
end
