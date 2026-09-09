$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& python -m pip install '.[dev]'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& python -m PyInstaller --noconfirm Stenograph.spec
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
Compress-Archive -Path dist\Stenograph -DestinationPath dist\Stenograph-Windows-x64.zip -Force
