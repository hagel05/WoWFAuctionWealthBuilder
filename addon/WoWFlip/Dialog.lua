-- WoWFlip: the confirm window used by Buy and List.
--
-- Every purchase and every posting goes through a button in this window, so
-- the player's own click is what spends gold (Blizzard requires that).
local ADDON, ns = ...

local dialog
local WIDTH = 340

local function Build()
    dialog = CreateFrame("Frame", "WoWFlipConfirm", UIParent, "BackdropTemplate")
    dialog:SetSize(WIDTH, 220)
    dialog:SetFrameStrata("DIALOG")
    dialog:SetClampedToScreen(true)
    dialog:SetPoint("CENTER", UIParent, "CENTER", 0, 120)
    dialog:EnableMouse(true)
    dialog:SetMovable(true)
    dialog:RegisterForDrag("LeftButton")
    dialog:SetScript("OnDragStart", dialog.StartMoving)
    dialog:SetScript("OnDragStop", dialog.StopMovingOrSizing)
    if dialog.SetBackdrop then
        dialog:SetBackdrop({
            bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
            edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
            tile = true, tileSize = 32, edgeSize = 32,
            insets = { left = 11, right = 12, top = 12, bottom = 11 },
        })
    end
    dialog:Hide()

    dialog.title = dialog:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    dialog.title:SetPoint("TOP", 0, -18)
    dialog.title:SetWidth(WIDTH - 40)

    dialog.body = dialog:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    dialog.body:SetPoint("TOPLEFT", 22, -46)
    dialog.body:SetWidth(WIDTH - 44)
    dialog.body:SetJustifyH("LEFT")
    dialog.body:SetJustifyV("TOP")

    local function Button(x)
        local b = CreateFrame("Button", nil, dialog, "UIPanelButtonTemplate")
        b:SetSize(140, 24)
        b:SetPoint("BOTTOM", x, 18)
        return b
    end
    dialog.extra = CreateFrame("Button", nil, dialog, "UIPanelButtonTemplate")
    dialog.extra:SetSize(150, 20)
    dialog.extra:SetPoint("BOTTOM", 0, 48)
    dialog.extra:SetScript("OnClick", function()
        local fn = dialog.onExtra
        if fn then fn() end
    end)
    dialog.primary = Button(-74)
    dialog.secondary = Button(74)
    dialog.primary:SetScript("OnClick", function()
        local fn = dialog.onPrimary
        if fn then fn() end
    end)
    dialog.secondary:SetScript("OnClick", function()
        local fn = dialog.onSecondary
        ns.CloseDialog()
        if fn then fn() end
    end)
    if UISpecialFrames then table.insert(UISpecialFrames, "WoWFlipConfirm") end -- Escape closes it
    dialog:SetScript("OnHide", function()
        local fn = dialog.onHide
        dialog.onHide = nil
        if fn then fn() end
    end)
end

-- opts: title, body, primary (label), onPrimary, primaryEnabled (default true),
-- secondary (label, default "Cancel"), onSecondary, onHide,
-- extra (label of a small option button above the others), onExtra
function ns.OpenDialog(opts)
    if not dialog then Build() end
    dialog.onHide = nil
    dialog.title:SetText(opts.title or "")
    dialog.body:SetText(opts.body or "")
    local lines = 1
    for _ in (opts.body or ""):gmatch("\n") do lines = lines + 1 end
    dialog:SetHeight(math.max(160, 110 + lines * 15 + (opts.extra and 28 or 0)))
    dialog.onExtra = opts.onExtra
    if opts.extra then
        dialog.extra:SetText(opts.extra)
        dialog.extra:Show()
    else
        dialog.extra:Hide()
    end
    dialog.onPrimary = opts.onPrimary
    dialog.onSecondary = opts.onSecondary
    if opts.primary then
        dialog.primary:SetText(opts.primary)
        dialog.primary:SetEnabled(opts.primaryEnabled ~= false)
        dialog.primary:Show()
        dialog.secondary:ClearAllPoints()
        dialog.secondary:SetPoint("BOTTOM", 74, 18)
    else
        dialog.primary:Hide()
        dialog.secondary:ClearAllPoints()
        dialog.secondary:SetPoint("BOTTOM", 0, 18)
    end
    dialog.secondary:SetText(opts.secondary or "Cancel")
    dialog:Show()
    dialog.onHide = opts.onHide
    return dialog
end

-- Press a dialog button from code (tests only; in game the player clicks).
function ns.DialogPress(which)
    if not dialog or not dialog:IsShown() then return end
    local b = dialog[which]
    local fn = b and b:GetScript("OnClick")
    if fn then fn(b) end
end

function ns.CloseDialog()
    if dialog then dialog:Hide() end
end

function ns.DialogShown()
    return dialog ~= nil and dialog:IsShown()
end

-- For tests and for the trade code: what the window currently says.
function ns.DialogState()
    if not dialog or not dialog:IsShown() then return nil end
    return {
        title = dialog.title:GetText(),
        body = dialog.body:GetText(),
        primary = dialog.primary:IsShown() and dialog.primary:GetText() or nil,
        primaryEnabled = (dialog.primary:IsShown() and dialog.primary:IsEnabled()) and true or false,
        extra = dialog.extra:IsShown() and dialog.extra:GetText() or nil,
    }
end
