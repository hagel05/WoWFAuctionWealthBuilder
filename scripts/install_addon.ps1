# Copies the WoWFlip addons into your WoW Forever AddOns folder.
# Run from the repository folder (or the unzipped download):
#   powershell -ExecutionPolicy Bypass -File scripts\install_addon.ps1
param([string]$WowDir = "C:\Program Files (x86)\World of Warcraft", [string]$Game = "_forever_")

$addons = Join-Path $WowDir "$Game\Interface\AddOns"
if (-not (Test-Path (Join-Path $WowDir $Game))) { throw "Not found: $(Join-Path $WowDir $Game). Pass -WowDir with your WoW folder." }
New-Item -ItemType Directory -Force -Path $addons | Out-Null
$src = Join-Path (Split-Path $PSScriptRoot) "addon"
Copy-Item -Recurse -Force (Join-Path $src "WoWFlip") $addons
# Always refresh the data addon's .toc, but keep its Data.lua if a scan already wrote one.
$data = Join-Path $addons "WoWFlipData"
New-Item -ItemType Directory -Force -Path $data | Out-Null
Copy-Item -Force (Join-Path $src "WoWFlipData\WoWFlipData.toc") $data
if (-not (Test-Path (Join-Path $data "Data.lua"))) {
    Copy-Item -Force (Join-Path $src "WoWFlipData\Data.lua") $data
}
Write-Host "Installed WoWFlip and WoWFlip Data into $addons."
Write-Host "If WoW is running, quit it completely and start it again (/reload does not find new addon folders)."
