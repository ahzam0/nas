# Start Telegram signals bot
$host.UI.RawUI.WindowTitle = "Fabio Bot - Telegram Signals"
Set-Location $PSScriptRoot
$py = $env:FABIO_PYTHON
if (-not $py) {
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue).Source; if ($py) { $py = "py -3" } }
}
if (-not $py) { $py = "python" }
Write-Host "Starting Telegram signals bot..."
& $py telegram_bot.py
pause
