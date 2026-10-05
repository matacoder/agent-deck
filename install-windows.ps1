# Agent Deck for Windows 11, running in WSL2 (Ubuntu) with the regular Linux installer.
#
# Run in PowerShell opened with "Run as administrator":
#   irm https://raw.githubusercontent.com/matacoder/agent-deck/main/install-windows.ps1 | iex
# Options are environment variables set before the same command, e.g.:
#   $env:AGENT_DECK_LANGUAGE = 'ru'
# Rerunning the command updates an existing installation; settings and sessions are kept.
#
# Compatible with Windows PowerShell 5.1 (the Windows 11 default). Errors are thrown, never `exit`:
# under `irm | iex` exit would close the window together with the message.

$ErrorActionPreference = 'Stop'
$AgentDeck = @{
    Language   = if ($env:AGENT_DECK_LANGUAGE) { $env:AGENT_DECK_LANGUAGE } else { 'en' }
    Distro     = if ($env:AGENT_DECK_DISTRO) { $env:AGENT_DECK_DISTRO } else { 'Ubuntu-24.04' }
    Port       = if ($env:AGENT_DECK_PORT) { [int]$env:AGENT_DECK_PORT } else { 8790 }
    WithDocker = $env:AGENT_DECK_WITH_DOCKER -eq '1'
    GetSh      = 'https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh'
    MinBuild   = 22621   # mirrored WSL networking needs Windows 11 22H2
    TaskName   = 'Agent Deck'
    # Hyper-V firewall rules address WSL by this fixed VM creator id.
    WslCreator = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'
}

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

function Merge-WslConfig([string]$Text) {
    # Keep every other WSL setting; only make sure [wsl2] networkingMode=mirrored.
    $lines = @()
    if ($Text) { $lines = $Text -split "`r?`n" }
    $out = New-Object System.Collections.Generic.List[string]
    $inWsl2 = $false; $seenWsl2 = $false; $done = $false
    foreach ($line in $lines) {
        if ($line -match '^\s*\[(.+)\]\s*$') {
            if ($inWsl2 -and -not $done) { $out.Add('networkingMode=mirrored'); $done = $true }
            $inWsl2 = $Matches[1].Trim().ToLower() -eq 'wsl2'
            if ($inWsl2) { $seenWsl2 = $true }
            $out.Add($line)
            continue
        }
        if ($inWsl2 -and $line -match '^\s*networkingMode\s*=') {
            if (-not $done) { $out.Add('networkingMode=mirrored'); $done = $true }
            continue
        }
        $out.Add($line)
    }
    if ($inWsl2 -and -not $done) { $out.Add('networkingMode=mirrored'); $done = $true }
    if (-not $seenWsl2) {
        if ($out.Count -gt 0 -and $out[$out.Count - 1].Trim() -ne '') { $out.Add('') }
        $out.Add('[wsl2]')
        $out.Add('networkingMode=mirrored')
    }
    return (($out -join "`r`n").TrimEnd()) + "`r`n"
}

function Select-TailscaleIPv4([string[]]$Lines) {
    foreach ($line in $Lines) {
        $value = "$line".Trim()
        if ($value -match '^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}$') { return $value }
    }
    return $null
}

function Test-InstallOptions($Options) {
    # Values end up in a bash command line inside WSL: only accept plain, expected shapes.
    if ($Options.Language -notmatch '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$') { throw "AGENT_DECK_LANGUAGE must look like 'en' or 'pt-BR'." }
    if ($Options.Distro -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') { throw 'AGENT_DECK_DISTRO is not a valid WSL distribution name.' }
    if ($Options.Port -lt 1024 -or $Options.Port -gt 65535) { throw 'AGENT_DECK_PORT must be between 1024 and 65535.' }
}

function Get-LinuxCommand($Options, [string]$Address) {
    $docker = if ($Options.WithDocker) { '1' } else { '0' }
    return "curl -fsSL $($Options.GetSh) | BIND_HOST=$Address PANEL_PORT=$($Options.Port) PANEL_LANGUAGE=$($Options.Language) WITH_DOCKER=$docker bash"
}

function Invoke-Wsl([string[]]$Arguments) {
    $env:WSL_UTF8 = '1'   # wsl.exe prints UTF-16 otherwise, which breaks parsing.
    $output = & wsl.exe @Arguments 2>&1
    return @{ Code = $LASTEXITCODE; Output = (($output | ForEach-Object { "$_" }) -join "`n") -replace "`0", '' }
}

function Assert-Prerequisites($Options) {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Open PowerShell with "Run as administrator" (Start > type PowerShell > Run as administrator) and paste the command again.'
    }
    $build = [int](Get-CimInstance Win32_OperatingSystem).BuildNumber
    if ($build -lt $Options.MinBuild) {
        throw "Windows 11 22H2 or newer is required (build $($Options.MinBuild)+); this computer has build $build. Update Windows and run the command again."
    }
}

function Install-Wsl {
    # Returns $false when Windows must restart before WSL can be used.
    if ((Invoke-Wsl @('--status')).Code -ne 0) {
        Write-Step 'Installing WSL (Windows Subsystem for Linux)'
        & wsl.exe --install --no-distribution
        Write-Host ''
        Write-Host 'Restart Windows, then open PowerShell as administrator and run the same command again.' -ForegroundColor Yellow
        return $false
    }
    Write-Step 'Updating WSL'
    & wsl.exe --update | Out-Null
    return $true
}

function Get-TailscaleAddress {
    $tailscale = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    if (-not (Test-Path $tailscale)) {
        Write-Step 'Installing Tailscale'
        if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
            throw 'Install Tailscale from https://tailscale.com/download/windows, sign in, and run the command again.'
        }
        & winget.exe install --id Tailscale.Tailscale --exact --silent --accept-source-agreements --accept-package-agreements | Out-Host
        if (-not (Test-Path $tailscale)) { throw 'Tailscale was not installed. Install it from https://tailscale.com/download/windows and rerun.' }
    }
    $address = Select-TailscaleIPv4 (& $tailscale ip -4 2>$null)
    if (-not $address) {
        Write-Step 'Sign in to Tailscale (a browser window opens)'
        & $tailscale up | Out-Host
        $address = Select-TailscaleIPv4 (& $tailscale ip -4 2>$null)
    }
    if (-not $address) { throw 'Tailscale has no IPv4 address yet. Sign in from the Tailscale tray icon and rerun.' }
    return $address
}

function Set-WslNetworking {
    # Returns $true when WSL has to restart to apply the change.
    $path = Join-Path $env:USERPROFILE '.wslconfig'
    $old = ''
    if (Test-Path $path) { $old = [IO.File]::ReadAllText($path) }
    $new = Merge-WslConfig $old
    if ($new -eq $old) { return $false }
    if ($old) { Copy-Item $path "$path.agent-deck-backup" -Force }
    [IO.File]::WriteAllText($path, $new)
    return $true
}

function Install-Distribution($Options) {
    $distro = $Options.Distro
    $names = (Invoke-Wsl @('--list', '--quiet')).Output -split "`n" | ForEach-Object { $_.Trim() }
    if ($names -notcontains $distro) {
        Write-Step "Installing $distro"
        & wsl.exe --install -d $distro --no-launch | Out-Host
    }
    if ((Invoke-Wsl @('-d', $distro, '-u', 'root', '--', 'true')).Code -ne 0) {
        # Store-packaged distributions register on first launch; root setup avoids the interactive user prompt.
        $launcher = 'ubuntu' + ($distro -replace '[^0-9]', '') + '.exe'
        if (Get-Command $launcher -ErrorAction SilentlyContinue) { & $launcher install --root | Out-Host }
    }
    if ((Invoke-Wsl @('-d', $distro, '-u', 'root', '--', 'true')).Code -ne 0) {
        throw "Open '$distro' from the Start menu once, create a user when asked, close it, and run the command again."
    }
    # The Linux installer runs Agent Deck as systemd user services.
    if ((Invoke-Wsl @('-d', $distro, '-u', 'root', '--', 'sh', '-c', 'grep -qs "^systemd=true" /etc/wsl.conf')).Code -ne 0) {
        Invoke-Wsl @('-d', $distro, '-u', 'root', '--', 'sh', '-c', 'printf "\n[boot]\nsystemd=true\n" >> /etc/wsl.conf') | Out-Null
        return $true
    }
    return $false
}

function Set-Firewall($Options) {
    $port = $Options.Port
    # The panel listens only on the Tailscale address; allow nothing but the tailnet range.
    Remove-NetFirewallRule -Name 'AgentDeck-Tailscale' -ErrorAction SilentlyContinue
    New-NetFirewallRule -Name 'AgentDeck-Tailscale' -DisplayName 'Agent Deck (Tailscale)' -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $port -RemoteAddress '100.64.0.0/10' | Out-Null
    if (Get-Command New-NetFirewallHyperVRule -ErrorAction SilentlyContinue) {
        Remove-NetFirewallHyperVRule -Name 'AgentDeck-WSL' -ErrorAction SilentlyContinue
        New-NetFirewallHyperVRule -Name 'AgentDeck-WSL' -DisplayName 'Agent Deck (WSL)' -Direction Inbound -Action Allow `
            -VMCreatorId $Options.WslCreator -Protocol TCP -LocalPorts $port -RemoteAddresses '100.64.0.0/10' | Out-Null
    }
}

function Register-KeepAlive($Options) {
    # WSL stops an idle distribution; a hidden process started at sign-in keeps the panel running.
    $wsl = Join-Path $env:WINDIR 'System32\wsl.exe'
    $action = New-ScheduledTaskAction -Execute (Join-Path $env:WINDIR 'System32\conhost.exe') `
        -Argument "--headless `"$wsl`" -d $($Options.Distro) -u root --exec /bin/sleep infinity"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $Options.TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description 'Keeps the Agent Deck WSL distribution running while you are signed in.' -Force | Out-Null
    Start-ScheduledTask -TaskName $Options.TaskName
}

function Add-StartMenuShortcut([string]$Url) {
    $path = Join-Path ([Environment]::GetFolderPath('Programs')) 'Agent Deck.url'
    [IO.File]::WriteAllText($path, "[InternetShortcut]`r`nURL=$Url`r`n")
}

function Install-AgentDeck($Options) {
    Write-Step 'Agent Deck for Windows 11 (WSL2)'
    Test-InstallOptions $Options
    Assert-Prerequisites $Options
    if (-not (Install-Wsl)) { return }
    $address = Get-TailscaleAddress
    $restart = Set-WslNetworking
    $restart = (Install-Distribution $Options) -or $restart
    if ($restart) {
        Write-Step 'Restarting WSL to apply settings (Linux programs running in WSL will stop)'
        & wsl.exe --shutdown
    }
    Set-Firewall $Options
    Write-Step "Installing Agent Deck inside $($Options.Distro)"
    & wsl.exe -d $Options.Distro -u root -- bash -c (Get-LinuxCommand $Options $address)
    if ($LASTEXITCODE -ne 0) { throw 'The Linux installer inside WSL failed; the message above explains why. Fix it and run the command again.' }
    Register-KeepAlive $Options
    $url = "http://$($address):$($Options.Port)"
    Add-StartMenuShortcut $url
    Write-Host ''
    Write-Host "Agent Deck is running: $url" -ForegroundColor Green
    Write-Host 'Login and password are printed above. Open it from the Start menu (Agent Deck) or on your phone over Tailscale.'
    Start-Process $url
}

if (-not $env:AGENT_DECK_NO_MAIN) {
    try { Install-AgentDeck $AgentDeck }
    catch { Write-Host "xx $($_.Exception.Message)" -ForegroundColor Red }
}
