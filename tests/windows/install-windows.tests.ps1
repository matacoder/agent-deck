# Unit checks for install-windows.ps1 helpers; runs on any PowerShell 7 (CI uses Linux pwsh).
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot '../../install-windows.ps1'
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($script, [ref]$null, [ref]$errors) | Out-Null
if ($errors.Count) { throw "Syntax errors: $($errors | ForEach-Object { $_.Message })" }
if ((Get-Content -Raw $script) -match '[^\x00-\x7F]') { throw 'install-windows.ps1 must stay ASCII: Windows PowerShell 5.1 misreads UTF-8 files without BOM' }
$env:AGENT_DECK_NO_MAIN = '1'
. $script
$failures = 0
function Check([string]$Name, [bool]$Ok) {
    if ($Ok) { Write-Host "ok   $Name" } else { Write-Host "FAIL $Name" -ForegroundColor Red; $script:failures++ }
}

Check 'empty .wslconfig gets a [wsl2] section and host loopback' ((Merge-WslConfig '') -eq "[wsl2]`r`nnetworkingMode=mirrored`r`n`r`n[experimental]`r`nhostAddressLoopback=true`r`n")
$existing = "[wsl2]`r`nmemory=8GB`r`nnetworkingMode=nat`r`n`r`n[experimental]`r`nautoMemoryReclaim=gradual`r`n"
$merged = Merge-WslConfig $existing
Check 'other settings are kept' ($merged -match 'memory=8GB' -and $merged -match 'autoMemoryReclaim=gradual' -and $merged -match '\[experimental\]')
Check 'host loopback joins the existing [experimental] section' ($merged -match "autoMemoryReclaim=gradual`r`nhostAddressLoopback=true" -and ([regex]::Matches($merged, '\[experimental\]')).Count -eq 1)
Check 'networking mode is replaced, not duplicated' (([regex]::Matches($merged, 'networkingMode')).Count -eq 1 -and $merged -match 'networkingMode=mirrored')
Check 'merging is idempotent' ((Merge-WslConfig $merged) -eq $merged)
$other = Merge-WslConfig "[experimental]`r`nsparseVhd=true"
Check 'a missing [wsl2] section is appended' ($other -eq "[experimental]`r`nsparseVhd=true`r`nhostAddressLoopback=true`r`n`r`n[wsl2]`r`nnetworkingMode=mirrored`r`n")
Check 'wsl2 section without the key gets it' ((Merge-WslConfig "[wsl2]`r`nmemory=4GB") -eq "[wsl2]`r`nmemory=4GB`r`nnetworkingMode=mirrored`r`n`r`n[experimental]`r`nhostAddressLoopback=true`r`n")
$forwarding = Merge-WslConfig "[wsl2]`r`nlocalhostForwarding=true"
Check 'localhostForwarding is commented out under mirrored networking' ($forwarding -eq "[wsl2]`r`n# localhostForwarding=true  (ignored with networkingMode=mirrored)`r`nnetworkingMode=mirrored`r`n`r`n[experimental]`r`nhostAddressLoopback=true`r`n")
Check 'commenting it is idempotent' ((Merge-WslConfig $forwarding) -eq $forwarding)

Check 'tailscale address is picked from CLI output' ((Select-TailscaleIPv4 @('', '100.101.12.7 ')) -eq '100.101.12.7')
Check 'non-tailnet addresses are ignored' ($null -eq (Select-TailscaleIPv4 @('192.168.1.5', '100.128.0.1', '100.63.1.1')))

$options = @{ Language = 'pt-BR'; Distro = 'Ubuntu-24.04'; Port = 8790; WithDocker = $false; GetSh = 'https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh' }
Test-InstallOptions $options
Check 'linux command carries only validated values' ((Get-LinuxCommand $options '100.64.0.9') -eq 'curl -fsSL https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh | BIND_HOST=100.64.0.9 PANEL_PORT=8790 PANEL_LANGUAGE=pt-BR WITH_DOCKER=0 bash')
foreach ($bad in @(@{ Language = 'en; rm -rf /' }, @{ Distro = 'Ubuntu; calc' }, @{ Port = 80 })) {
    $copy = $options.Clone(); foreach ($k in $bad.Keys) { $copy[$k] = $bad[$k] }
    $rejected = $false
    try { Test-InstallOptions $copy } catch { $rejected = $true }
    Check "rejects $($bad.Keys) = $($bad.Values)" $rejected
}
if ($failures) { throw "$failures check(s) failed" }
Write-Host 'all install-windows checks passed'
