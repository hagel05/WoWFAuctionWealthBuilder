# Builds dist\WoWFlipSync.exe, the sync helper for PCs without Python.
# Run from the repository folder:
#   powershell -ExecutionPolicy Bypass -File scripts\build_sync_exe.ps1
$ErrorActionPreference = "Stop"
python -m pip install --quiet pyinstaller .
python -m PyInstaller --onefile --console --name WoWFlipSync --clean scripts\wowflip_sync.py
Write-Host "Built dist\WoWFlipSync.exe. Put it in a folder with a config.toml that has an [addon] section."
