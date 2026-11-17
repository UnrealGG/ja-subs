# One-time setup: register the local service launcher with Edge/Chrome.
$root = Split-Path -Parent $PSScriptRoot
$extDir = Join-Path $root 'ext'
$hostExe = Join-Path $root 'native\ja_host.exe'
$hostManifest = Join-Path $root 'native\com.jasubs.launcher.json'

if (-not (Test-Path $hostExe)) { Write-Output "ERROR: missing $hostExe"; exit 1 }

# 1) find the real extension id from the browser profile
$extId = $null
foreach ($p in @("$env:LOCALAPPDATA\Microsoft\Edge\User Data", "$env:LOCALAPPDATA\Google\Chrome\User Data")) {
  if (-not (Test-Path $p)) { continue }
  foreach ($f in @("$p\Default\Secure Preferences", "$p\Default\Preferences")) {
    if (-not (Test-Path $f)) { continue }
    try {
      $j = Get-Content $f -Raw -Encoding UTF8 | ConvertFrom-Json
      foreach ($prop in $j.extensions.settings.PSObject.Properties) {
        if ($prop.Value.path -and ($prop.Value.path -eq $extDir)) { $extId = $prop.Name; break }
      }
    } catch { }
    if ($extId) { break }
  }
  if ($extId) { break }
}
if (-not $extId) { $extId = 'eadedfandpclapegekglgjmmikdkofkd' }
Write-Output "extension id : $extId"

# 2) rewrite host manifest (UTF-8 without BOM)
$obj = [ordered]@{ name = 'com.jasubs.launcher'; description = 'launch local ja-sub service'; path = $hostExe; type = 'stdio'; allowed_origins = @("chrome-extension://$extId/") }
$json = $obj | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText($hostManifest, $json, (New-Object Text.UTF8Encoding $false))
Write-Output "manifest : $hostManifest"

# 3) register for Edge and Chrome
foreach ($k in @('HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\com.jasubs.launcher',
                 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.jasubs.launcher')) {
  try {
    New-Item -Path $k -Force | Out-Null
    Set-ItemProperty -Path $k -Name '(default)' -Value $hostManifest
    $v = (Get-ItemProperty -Path $k).'(default)'
    if ($v) { Write-Output "registered : $k" } else { Write-Output "FAILED     : $k" }
  } catch {
    Write-Output "FAILED     : $k  ($($_.Exception.Message))"
  }
}
Write-Output ""
Write-Output "Done. Go to edge://extensions and click Reload on this extension."
