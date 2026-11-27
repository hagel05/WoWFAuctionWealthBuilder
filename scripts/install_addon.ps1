# Copies the WoWFlip addons into your WoW Forever AddOns folder.
# Run from the repository folder (or the unzipped download):
#   powershell -ExecutionPolicy Bypass -File scripts\install_addon.ps1
param([string]$WowDir = "C:\Program Files (x86)\World of Warcraft", [string]$Game = "_forever_")

$addons = Join-Path $WowDir "$Game\Interface\AddOns"
if (-not (Test-Path (Join-Path $WowDir $Game))) { throw "Not found: $(Join-Path $WowDir $Game). Pass -WowDir with your WoW folder." }
New-Item -ItemType Directory -Force -Path $addons | Out-Null
$src = Join-Path (Split-Path $PSScriptRoot) "addon"
Copy-Item -Recurse -Force (Join-Path $src "WoWFlip") $addons
# Keep the data addon's current Data.lua if the sync helper already wrote one.
if (-not (Test-Path (Join-Path $addons "WoWFlipData\Data.lua"))) {
    Copy-Item -Recurse -Force (Join-Path $src "WoWFlipData") $addons
}
Write-Host "Installed WoWFlip into $addons. Restart WoW or type /reload."
