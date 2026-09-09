param(
    [string]$PythonPath = ''
)

$ErrorActionPreference = 'Stop'
# Keep native exit-code handling consistent in Windows PowerShell 5.1 and PowerShell 7.
$PSNativeCommandUseErrorActionPreference = $false
Set-Location (Split-Path $PSScriptRoot -Parent)

function Get-PythonInfo([string]$Executable) {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $probe = 'import json,platform,struct,sys,sysconfig; print(json.dumps(dict(executable=sys.executable,version=platform.python_version(),major=sys.version_info.major,minor=sys.version_info.minor,bits=struct.calcsize(''P'')*8,machine=platform.machine(),implementation=platform.python_implementation(),free_threaded=bool(sysconfig.get_config_var(''Py_GIL_DISABLED'')))))'
        $output = & $Executable -c $probe 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $info = ($output -join "`n") | ConvertFrom-Json -ErrorAction Stop
        return $info
    }
    catch { return $null }
    finally { $ErrorActionPreference = $previousPreference }
}

function Test-CompatiblePython($Info) {
    return ($null -ne $Info -and $Info.major -eq 3 -and
        $Info.minor -ge 11 -and $Info.minor -le 13 -and $Info.bits -eq 64 -and
        $Info.machine -match '^(AMD64|x86_64)$' -and
        $Info.implementation -eq 'CPython' -and -not $Info.free_threaded)
}

$candidates = @()
if ($PythonPath) {
    # An explicit path is authoritative: don't silently select a different installation.
    $candidates += $PythonPath
}
else {
    foreach ($name in @('python.exe', 'python3.exe')) {
        $commands = @(Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue)
        foreach ($command in $commands) {
            # Do not open the Microsoft Store application-execution alias during detection.
            if ($command.Source -notmatch '\\Microsoft\\WindowsApps\\') {
                $candidates += $command.Source
            }
        }
    }
    $launchers = @(Get-Command py.exe -CommandType Application -All -ErrorAction SilentlyContinue)
    foreach ($launcher in $launchers) {
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $launcherPath = [string]$launcher.Source
            $installed = & $launcherPath -0p 2>$null
            foreach ($line in $installed) {
                if ($line -match '^\s*-(?:V:)?\S+\s+\*?\s*(.+?python(?:[0-9.]*)?\.exe)\s*$') {
                    $candidates += $Matches[1].Trim()
                }
            }
        }
        catch { Write-Host 'Skipping an unavailable Python launcher.' }
        finally { $ErrorActionPreference = $previousPreference }
    }
}

$selected = $null
$detected = @()
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    $info = Get-PythonInfo $candidate
    if ($null -ne $info) {
        $detected += ('Python {0}, {1}-bit, {2}: {3}' -f $info.version, $info.bits, $info.machine, $info.executable)
        if (Test-CompatiblePython $info) {
            $selected = $info
            break
        }
    }
}
if ($null -eq $selected) {
    foreach ($description in $detected) { Write-Host "Detected: $description" }
    throw 'No supported Python found. This build needs regular CPython 3.11, 3.12 or 3.13 for Windows x64 (not 32-bit, ARM64 or free-threaded). Python 3.14+ is not yet supported. If already installed, rerun with -PythonPath "C:\full\path\to\python.exe". The py launcher is optional.'
}

Write-Host ('Using Python {0} ({1}-bit): {2}' -f $selected.version, $selected.bits, $selected.executable)
$venvPython = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $venvInfo = Get-PythonInfo $venvPython
    if (-not (Test-CompatiblePython $venvInfo)) {
        throw 'Existing .venv is incompatible or damaged. Close Stenograph, rename .venv to .venv-old, then rerun. Meeting data is stored separately.'
    }
    Write-Host ('Reusing existing .venv: Python {0}' -f $venvInfo.version)
}
else {
    & $selected.executable -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        throw 'Python was found, but virtual environment creation failed. See the original error above; check permissions, disk space and the Python venv component.'
    }
}
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip update failed. See the network/proxy or package error above.' }
& $venvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. See the package error above.' }
Write-Host 'Installed. Start using Start-Stenograph.cmd. Prepare local models as described in README.md.'
