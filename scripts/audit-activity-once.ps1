$ErrorActionPreference = 'Continue'
Set-Location 'e:\langChain_langGraph'

$now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'
$total  = (git log --pretty=oneline | Measure-Object).Count
$d30    = (git log --since='30 days ago' --pretty=oneline | Measure-Object).Count
$d90    = (git log --since='90 days ago' --pretty=oneline | Measure-Object).Count
$d365   = (git log --since='365 days ago' --pretty=oneline | Measure-Object).Count
$top    = git log --since='90 days ago' --pretty=format:'%an' | Group-Object | Sort-Object Count -Descending | Select-Object -First 5

$out = 'e:\langChain_langGraph\output\2026-10-20\audit-activity.md'
$sb  = [System.Text.StringBuilder]::new()
[void]$sb.AppendLine('# audit-activity')
[void]$sb.AppendLine('---')
[void]$sb.AppendLine("generated_at: $now")
[void]$sb.AppendLine('')
[void]$sb.AppendLine('## 提交量')
[void]$sb.AppendLine('')
[void]$sb.AppendLine('| window | count |')
[void]$sb.AppendLine('| --- | ---: |')
[void]$sb.AppendLine(('| total | {0} |' -f $total))
[void]$sb.AppendLine(('| last 30 days | {0} |' -f $d30))
[void]$sb.AppendLine(('| last 90 days | {0} |' -f $d90))
[void]$sb.AppendLine(('| last 365 days | {0} |' -f $d365))
[void]$sb.AppendLine('')
[void]$sb.AppendLine('## 近 90 天作者 Top-5')
[void]$sb.AppendLine('')
[void]$sb.AppendLine('| author | commits |')
[void]$sb.AppendLine('| --- | ---: |')
foreach ($a in $top) {
    [void]$sb.AppendLine(('| {0} | {1} |' -f $a.Name, $a.Count))
}
[void]$sb.AppendLine('')
[void]$sb.AppendLine('## 风险面汇总（基于前面 3 份报告）')
[void]$sb.AppendLine('')
[void]$sb.AppendLine('- 详见 [audit-fs](audit-fs.md) / [audit-deps](audit-deps.md) / [audit-evals](audit-evals.md)')
[void]$sb.AppendLine('')
[void]$sb.AppendLine('_摸排口径：`git log` 计数按 HEAD 可达；作者按 `git log --pretty=format:"%an"`。_')

Set-Content -Path $out -Value $sb.ToString() -Encoding UTF8
Write-Host ('wrote {0} bytes={1}' -f $out, (Get-Item $out).Length)
