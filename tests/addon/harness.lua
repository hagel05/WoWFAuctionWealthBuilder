-- Loads the WoWFlip addon in plain Lua 5.1 with a stubbed WoW API and runs checks.
-- Usage: lua5.1 harness.lua <addon dir> <Data.lua path>
local addonDir, dataPath = arg[1], arg[2]

local function Obj()
    local o = { _shown = false, _scripts = {}, _events = {}, _lines = false }
    return setmetatable(o, { __index = function(t, k)
        return function(self, ...)
            local a = { ... }
            if k == "Show" then self._shown = true
            elseif k == "Hide" then self._shown = false
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
