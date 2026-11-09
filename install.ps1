# ─────────────────────────────────────────────────────────────
#  My Work Log — one-command install for Windows 10 / 11
#    Double-click install.bat   (or:  powershell -ExecutionPolicy Bypass -File install.ps1)
#    install.bat -Yes           no questions (use detected values)
#    install.bat -Uninstall     remove the automation (your data stays)
# ─────────────────────────────────────────────────────────────
param([switch]$Yes, [switch]$Uninstall, [switch]$LogoffScript, [switch]$RemoveLogoffScript, [string]$Python)

$ErrorActionPreference = 'Continue'   # native tools write warnings to stderr; exit codes are checked instead
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Dir
$TaskPrefix = 'MyWorkLog '                # tasks: 'MyWorkLog Dashboard', 'MyWorkLog Catch-up', 'MyWorkLog Fallback'
$GpUser = Join-Path $env:SystemRoot 'System32\GroupPolicy\User'
$ScriptsIni = Join-Path $GpUser 'Scripts\scripts.ini'
$GptIni = Join-Path $env:SystemRoot 'System32\GroupPolicy\gpt.ini'
$LogoffCmd = Join-Path $Dir 'worklog_logoff.cmd'
# Client-side extension + snap-in for user logon/logoff scripts
$ScriptsCse = '[{42B5FAAE-6536-11D2-AE5A-0000F87571E3}{40B66650-4972-11D1-A7CA-0000F87571E3}]'

function Ok($m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Step($m) { Write-Host "`n$m" -ForegroundColor Cyan }
function IsAdmin  { ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }

# ── sign-out script (local Group Policy, needs administrator) ──────────────
# Windows has no reliable "on shutdown" hook for normal programs, but a sign-out script runs
# (as me, with the network still up) whenever I sign out, restart or shut down.
function Read-Ini($path) { if (Test-Path $path) { return (Get-Content -LiteralPath $path -Encoding Unicode -ErrorAction SilentlyContinue) } return @() }

function Set-LogoffScript([bool]$add) {
    New-Item -ItemType Directory -Force -Path (Split-Path $ScriptsIni) | Out-Null
    $lines = @(Read-Ini $ScriptsIni)
    # keep every section except our own entries; rebuild [Logoff] with consecutive numbers
    $sections = [ordered]@{}; $cur = ''
    foreach ($l in $lines) {
        if ($l -match '^\s*\[(.+)\]\s*$') { $cur = $Matches[1]; if (-not $sections.Contains($cur)) { $sections[$cur] = New-Object System.Collections.ArrayList }; continue }
        if ($cur -and $l.Trim()) { [void]$sections[$cur].Add($l) }
    }
    $pairs = @()
    if ($sections.Contains('Logoff')) {
        $cmds = @{}; $pars = @{}
        foreach ($l in $sections['Logoff']) {
            if ($l -match '^(\d+)CmdLine=(.*)$') { $cmds[[int]$Matches[1]] = $Matches[2] }
            elseif ($l -match '^(\d+)Parameters=(.*)$') { $pars[[int]$Matches[1]] = $Matches[2] }
        }
        foreach ($k in ($cmds.Keys | Sort-Object)) { if ($cmds[$k] -ne $LogoffCmd) { $pairs += ,@($cmds[$k], $pars[$k]) } }
    }
    if ($add) { $pairs += ,@($LogoffCmd, '') }
    $out = New-Object System.Collections.ArrayList
    foreach ($name in $sections.Keys) { if ($name -ne 'Logoff') { [void]$out.Add("[$name]"); $sections[$name] | ForEach-Object { [void]$out.Add($_) }; [void]$out.Add('') } }
    if ($pairs.Count) { [void]$out.Add('[Logoff]'); $i = 0; foreach ($p in $pairs) { [void]$out.Add("${i}CmdLine=$($p[0])"); [void]$out.Add("${i}Parameters=$($p[1])"); $i++ } }
    if (Test-Path $ScriptsIni) { attrib -h $ScriptsIni 2>$null }
    Set-Content -LiteralPath $ScriptsIni -Value $out -Encoding Unicode
    attrib +h $ScriptsIni 2>$null

    # gpt.ini: register the scripts extension for users and bump the user policy version
    $g = @(); if (Test-Path $GptIni) { $g = @(Get-Content -LiteralPath $GptIni) }
    if (-not ($g -match '^\[General\]')) { $g = @('[General]') + $g }
    $ver = 0; $names = ''
    foreach ($l in $g) { if ($l -match '^Version=(\d+)') { $ver = [int64]$Matches[1] }; if ($l -match '^gPCUserExtensionNames=(.*)$') { $names = $Matches[1] } }
    if ($add -and $names -notlike "*$ScriptsCse*") {
        $groups = @([regex]::Matches($names, '\[[^\]]+\]') | ForEach-Object { $_.Value }) + $ScriptsCse
        $names = ($groups | Sort-Object -Unique) -join ''
    }
    $ver = $ver + 65536                         # high word = user policy version
    $g = @($g | Where-Object { $_ -notmatch '^(Version|gPCUserExtensionNames)=' })
    $g += "gPCUserExtensionNames=$names"; $g += "Version=$ver"
    Set-Content -LiteralPath $GptIni -Value $g -Encoding ASCII
    gpupdate /target:user /force | Out-Null
}

if ($LogoffScript)       { Set-LogoffScript $true;  exit 0 }   # called elevated from the main install
if ($RemoveLogoffScript) { Set-LogoffScript $false; exit 0 }

function Run-Elevated($argsLine) {
    if (IsAdmin) { & powershell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath @($argsLine -split ' '); return $LASTEXITCODE -eq 0 }
    try {
        $p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" $argsLine"
        return $p.ExitCode -eq 0
    } catch { return $false }
}

# ── uninstall ─────────────────────────────────────────────────────────────
if ($Uninstall) {
    Step 'Removing My Work Log automation'
    Get-ScheduledTask -TaskName "$TaskPrefix*" -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
    Ok 'scheduled tasks removed'
    if (Select-String -LiteralPath $ScriptsIni -SimpleMatch $LogoffCmd -Encoding Unicode -Quiet -ErrorAction SilentlyContinue) {
        if (Run-Elevated '-RemoveLogoffScript') { Ok 'sign-out script removed' } else { Warn 'could not remove the sign-out script (needs administrator)' }
    }
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -like "*$Dir*server.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    $pyx = (Get-Content -LiteralPath (Join-Path $Dir '.python') -ErrorAction SilentlyContinue); if ($pyx) { & $pyx (Join-Path $Dir 'desktop_app.py') --remove }
    Ok "done - your data (raw\, output\, config.yaml ...) is still in $Dir"
    exit 0
}

Write-Host '==============================================='
Write-Host '  My Work Log - installer (Windows)'
Write-Host '==============================================='

# 1. Python ───────────────────────────────────────────────────────────────
Step '1/6  Python'
function Find-Python {
    if ($Python -and (Test-Path $Python)) { return $Python }
    foreach ($c in @('py -3', 'python', 'python3')) {
        $parts = @($c -split ' ')
        try {
            $exe = & $parts[0] @($parts | Select-Object -Skip 1) -c "import sys; print(sys.executable) if sys.version_info >= (3, 9) else None" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe.Trim())) { return $exe.Trim() }
        } catch {}
    }
    return $null
}
$py = Find-Python
if (-not $py) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host '  Installing Python 3.12 with winget ...'
        winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Null
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $py = Find-Python
    }
    if (-not $py) { Write-Host '  Python 3.9+ is required: https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run install.bat again.' -ForegroundColor Red; exit 1 }
}
& $py -c "import yaml" 2>$null
if ($LASTEXITCODE -ne 0) { & $py -m pip install --user --quiet --disable-pip-version-check pyyaml }
& $py -c "import yaml"; if ($LASTEXITCODE -ne 0) { Write-Host '  Could not install PyYAML.' -ForegroundColor Red; exit 1 }
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'; if (-not (Test-Path $pyw)) { $pyw = $py }
Set-Content -LiteralPath (Join-Path $Dir '.python') -Value $py -Encoding ASCII
Ok "$(& $py --version) ($py)"

# 2. Tools on this PC ─────────────────────────────────────────────────────
Step '2/6  Detecting tools'
if (Get-Command git -ErrorAction SilentlyContinue) { Ok 'git' } else { Warn 'git not found - commits will not be logged (winget install Git.Git)' }
$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) { $claude = Get-Item "$env:APPDATA\npm\claude.cmd", "$env:USERPROFILE\.local\bin\claude.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 }
if ($claude) { Ok 'Claude Code - AI summaries on' } else {
    Warn 'Claude Code not found - summaries use a simple built-in draft. For AI summaries:'
    Warn '  npm install -g @anthropic-ai/claude-code   then run:  claude   (sign in once)'
}
$browsers = @{ 'Chrome' = "$env:LOCALAPPDATA\Google\Chrome\User Data"; 'Edge' = "$env:LOCALAPPDATA\Microsoft\Edge\User Data";
               'Brave' = "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\User Data"; 'Firefox' = "$env:APPDATA\Mozilla\Firefox\Profiles" }
foreach ($b in $browsers.Keys) { if (Test-Path $browsers[$b]) { Ok "browser: $b" } }
if (Test-Path "$env:APPDATA\Code\User") { Ok 'VS Code' }

# 3. Settings ─────────────────────────────────────────────────────────────
Step '3/6  Your settings'
$a = @('setup_config.py'); if ($Yes) { $a += '--yes' }
& $py @a
if ($LASTEXITCODE -ne 0) { exit 1 }

# 4. Scheduled tasks (no administrator needed) ──────────────────────────────
Step '4/6  Automation'
$user = "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 0)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
function Add-Task($name, $trigger, $script, $arg) {
    $action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$Dir\$script`" $arg" -WorkingDirectory $Dir
    Register-ScheduledTask -TaskName "$TaskPrefix$name" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
}
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
Add-Task 'Dashboard' $logon 'server.py' ''
$logon2 = New-ScheduledTaskTrigger -AtLogOn -User $user; $logon2.Delay = 'PT1M'
Add-Task 'Catch-up' $logon2 'session.py' 'boot'
$fallback = (& $py -c "import sys; sys.path.insert(0, r'$Dir'); from common import cfg; print(cfg()['automation'].get('fallback_at', '23:50'))").Trim()
Add-Task 'Fallback' (New-ScheduledTaskTrigger -Daily -At $fallback) 'session.py' 'fallback'
Ok "dashboard starts when I sign in; catch-up after sign-in; $fallback safety run"

# 5. Save my day when I sign out / shut down ───────────────────────────────
Step '5/6  Save my day when the PC shuts down'
Set-Content -LiteralPath $LogoffCmd -Encoding ASCII -Value @(
    '@echo off',
    'rem My Work Log: save my day when I sign out, restart or shut down (local Group Policy sign-out script)',
    "cd /d `"$Dir`"",
    "`"$py`" `"$Dir\session.py`" shutdown >> `"$Dir\daily.log`" 2>&1")
Write-Host '  Windows asks for administrator permission once (it adds a sign-out script).'
if (Run-Elevated '-LogoffScript') { Ok 'installed - signing out or shutting down saves my day first' }
else { Warn 'skipped - your day is still saved by the sign-in catch-up and the late-night run. Re-run install.bat as administrator to add it.' }

# 6. Dashboard ────────────────────────────────────────────────────────────
Step '6/6  Dashboard'
& $py (Join-Path $Dir 'desktop_app.py')
$running = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if (-not $running) { Start-Process -FilePath $pyw -ArgumentList "`"$Dir\server.py`"" -WorkingDirectory $Dir -WindowStyle Hidden; Start-Sleep -Seconds 2 }
Start-Process 'http://127.0.0.1:8765'
Write-Host "`n  Done. Open http://127.0.0.1:8765  ->  Settings & help  ->  connect your Google Sheet (2 minutes).`n"
