# Abre a página da IARA no Chrome em modo quiosque (tela cheia, sem barras).
# Usa um perfil dedicado: a permissão do microfone concedida na primeira vez fica salva.
# Uso: powershell -ExecutionPolicy Bypass -File scripts\run_kiosk.ps1 [-Url http://localhost:8000]

param([string]$Url = "http://localhost:8000")

$candidates = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
)
$chrome = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { Write-Error "Chrome não encontrado."; exit 1 }

$profileDir = Join-Path $env:LocalAppData "iara-chrome-profile"

# Espera o backend responder (útil quando os dois sobem juntos no boot).
for ($i = 0; $i -lt 60; $i++) {
  try { Invoke-WebRequest -UseBasicParsing "$Url/healthz" -TimeoutSec 2 | Out-Null; break }
  catch { Start-Sleep -Seconds 1 }
}

& $chrome `
  --kiosk `
  --user-data-dir="$profileDir" `
  --autoplay-policy=no-user-gesture-required `
  --no-first-run `
  --disable-session-crashed-bubble `
  --disable-features=Translate `
  $Url
