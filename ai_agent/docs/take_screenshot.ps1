$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$out = "e:\langChain_langGraph\ai_agent\docs\screenshot_stage_a_demo.png"
$url = "http://127.0.0.1:8765/web-static/preview_stage_a.html"
$args = @(
    "--headless",
    "--disable-gpu",
    "--hide-scrollbars",
    "--window-size=1280,1400",
    "--screenshot=$out",
    "--no-sandbox",
    "--virtual-time-budget=3000",
    $url
)
& $chrome $args 2>&1 | Select-Object -First 30
Write-Host "Saved to $out"