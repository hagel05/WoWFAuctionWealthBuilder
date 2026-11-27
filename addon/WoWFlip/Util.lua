-- WoWFlip: shared helpers.
local ADDON, ns = ...

ns.GOLD, ns.SILVER = 10000, 100

local GOLD_C, SILVER_C, COPPER_C = "|cffffd700", "|cffc7c7cf", "|cffeda55f"

-- "1g 23s 45c" with coin colours. GetCoinText is missing on WoW Forever, so
-- this is done by hand.
function ns.Money(copper, plain)
    copper = math.floor((tonumber(copper) or 0) + 0.5)
    local sign = ""
    if copper < 0 then
        sign, copper = "-", -copper
    end
    local g = math.floor(copper / ns.GOLD)
    local s = math.floor((copper % ns.GOLD) / ns.SILVER)
    local c = copper % ns.SILVER
    local parts = {}
    if plain then
        if g > 0 then parts[#parts + 1] = g .. "g" end
        if g > 0 or s > 0 then parts[#parts + 1] = s .. "s" end
        parts[#parts + 1] = c .. "c"
    else
        if g > 0 then parts[#parts + 1] = GOLD_C .. g .. "g|r" end
        if g > 0 or s > 0 then parts[#parts + 1] = SILVER_C .. s .. "s|r" end
        parts[#parts + 1] = COPPER_C .. c .. "c|r"
    end
    return sign .. table.concat(parts, " ")
end

-- "34 min ago", "3 h ago".
function ns.Ago(seconds)
    seconds = math.max(0, seconds or 0)
    if seconds < 90 then return "just now" end
    if seconds < 90 * 60 then return math.floor(seconds / 60 + 0.5) .. " min ago" end
    if seconds < 48 * 3600 then return math.floor(seconds / 3600 + 0.5) .. " h ago" end
    return math.floor(seconds / 86400 + 0.5) .. " days ago"
end

function ns.Print(msg)
    local frame = DEFAULT_CHAT_FRAME
    if frame and frame.AddMessage then
        frame:AddMessage("|cff33ff99WoWFlip|r: " .. tostring(msg))
    end
end

-- Item id from a hyperlink such as "|cff...|Hitem:2447::...|h[Peacebloom]|h|r".
function ns.ItemIDFromLink(link)
    if type(link) ~= "string" then return nil end
    local id = link:match("item:(%d+)")
    return id and tonumber(id) or nil
end

function ns.CharacterKey()
    local name = UnitName and UnitName("player") or "?"
    local realm = GetRealmName and GetRealmName() or "?"
    return name .. " - " .. realm
end
