$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$out = "e:\langChain_langGraph\ai_agent\docs\screenshot_index_settings.png"
$target = "http://127.0.0.1:8765/web-static/preview_index_wrap.html"
$args = @(
    "--headless",
    "--disable-gpu",
    "--hide-scrollbars",
    "--window-size=1400,900",
    "--screenshot=$out",
    "--no-sandbox",
    "--virtual-time-budget=8000",
    $target
)
& $chrome $args 2>&1 | Select-Object -First 10
Write-Host "Saved to $out"