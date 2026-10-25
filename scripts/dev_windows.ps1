# Teste no PC de desenvolvimento (Windows): sobe o backend numa janela e abre o Chrome
# (janela normal, não quiosque) na página com o painel de debug.
# Uso, na pasta do projeto:  powershell -ExecutionPolicy Bypass -File scripts\dev_windows.ps1

$root = Split-Path -Parent $PSScriptRoot
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
if (-not (Test-Path $uv)) { Write-Error "uv não encontrado. Instale: irm https://astral.sh/uv/install.ps1 | iex"; exit 1 }

if (-not (Test-Path (Join-Path $root ".env"))) {
  Write-Error "Falta o arquivo .env (copie .env.example para .env e preencha OPENAI_API_KEY)."; exit 1
}

Start-Process powershell -WorkingDirectory $root -ArgumentList "-NoExit", "-Command", "& '$uv' run python -m iara"

$url = "http://localhost:8000"
for ($i = 0; $i -lt 60; $i++) {
  try { Invoke-WebRequest -UseBasicParsing "$url/healthz" -TimeoutSec 2 | Out-Null; break }
  catch { Start-Sleep -Seconds 1 }
}

$chrome = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { Write-Error "Chrome não encontrado; abra $url/?debug=1 manualmente."; exit 1 }

& $chrome --user-data-dir="$env:LocalAppData\iara-chrome-profile" --autoplay-policy=no-user-gesture-required `
  --no-first-run --new-window "$url/?debug=1"
