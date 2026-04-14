# 3GPP Rel-19 下载脚本 (v4 - 配置化)
$ErrorActionPreference = 'SilentlyContinue'

# 从 config.json 读取配置
$configPath = Join-Path $PSScriptRoot 'config\config.json'
if (-not (Test-Path $configPath)) {
    Write-Host "ERROR: config.json not found at $configPath" -ForegroundColor Red
    exit 1
}
$config = Get-Content $configPath -Raw | ConvertFrom-Json

$protocolBase = $config.paths.protocol_base
$defaultRelease = $config.database.default_release
$requiredSubdir = $config.protocol_structure.required_subdir

# 从配置推断 Release URL 路径（如 Rel-19 → 2026-03/Rel-19）
$releaseMap = @{
    'Rel-19' = '2026-03/Rel-19'
    'Rel-20' = '2026-06/Rel-20'
}
$releasePath = if ($releaseMap[$defaultRelease]) { $releaseMap[$defaultRelease] } else { $defaultRelease }

$baseUrl = "https://www.3gpp.org/ftp/Specs/$releasePath"
$baseDir = Join-Path $protocolBase $defaultRelease
$baseDir = Join-Path $baseDir $requiredSubdir
$series = @('22_series','23_series','24_series','25_series','26_series','27_series',
            '28_series','29_series','31_series','32_series','33_series','34_series',
            '35_series','36_series','37_series','38_series')

$totalDl = 0; $totalSkip = 0; $totalErr = 0
$failed = @()
$visited = @{}

# Known file extensions (directories will NOT end with these)
$fileExts = @('.pdf','.doc','.docx','.xls','.xlsx','.zip','.tar.gz','.tgz','.rtf','.cdf')

if (-not (Test-Path $baseDir)) {
    New-Item -ItemType Directory -Path $baseDir -Force | Out-Null
}

$wc = New-Object System.Net.WebClient
$wc.Headers.Add('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

function Is-RealDir($url) {
    # A "directory" URL from 3gpp.org will NOT end with a file extension
    $low = $url.ToLower()
    foreach ($ext in $fileExts) {
        if ($low.EndsWith($ext)) { return $false }
    }
    return $true
}

function Get-FileLinks($html, $base) {
    $links = @()
    $re = [regex] 'href="(https://www\.3gpp\.org/ftp/Specs/[^"?\s]+\.(?:pdf|doc|docx|xls|xlsx|zip|tar\.gz|tgz|rtf|cdf))"'
    $matches = $re.Matches($html)
    foreach ($m in $matches) {
        $url = $m.Groups[1].Value
        if ($url.StartsWith($base + '/') -and -not $url.EndsWith('/') -and $url.Length -gt ($base.Length + 1)) {
            $links += $url
        }
    }
    return $links
}

function Get-SubDirs($html, $base) {
    $dirs = @()
    $re = [regex] 'href="(https://www\.3gpp\.org/ftp/Specs/[^"?]+)"'
    $matches = $re.Matches($html)
    foreach ($m in $matches) {
        $url = $m.Groups[1].Value.TrimEnd('/')
        $fullUrl = $url + '/'
        if ($fullUrl.StartsWith($base + '/') -and $fullUrl.Length -gt ($base.Length + 1) -and $fullUrl.IndexOf('?') -eq -1) {
            # Filter out file-like URLs (end with extension)
            if ($url -ne $base -and (Is-RealDir $url)) {
                $dirs += $url
            }
        }
    }
    return $dirs
}

function Process-Folder($url, $localDir) {
    if (-not (Test-Path $localDir)) {
        New-Item -ItemType Directory -Path $localDir -Force | Out-Null
    }
    if ($visited.ContainsKey($url)) { return }
    $visited[$url] = $true

    Write-Host "[SCAN] $url"
    $html = $wc.DownloadString($url)

    $files = Get-FileLinks $html $baseUrl
    foreach ($furl in $files) {
        $fname = [System.IO.Path]::GetFileName($furl)
        $relF = $furl.Substring($baseUrl.Length + 1).Replace('/', '\')
        $local = Join-Path $baseDir $relF
        $dir = Split-Path $local -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        if (Test-Path $local) {
            Write-Host "  [SKIP] $fname"
            $script:totalSkip++
        } else {
            try {
                Write-Host "  [DOWN] $fname"
                $wc.DownloadFile($furl, $local)
                $script:totalDl++
            } catch {
                Write-Host "  [ERR]  $fname : $($_.Exception.Message)" -ForegroundColor Red
                $script:totalErr++
                $script:failed += $furl
            }
        }
    }

    $dirs = Get-SubDirs $html $baseUrl
    foreach ($sub in $dirs) {
        $relSub = $sub.Substring($baseUrl.Length + 1).Replace('/', '\')
        $subLocal = Join-Path $baseDir $relSub
        Process-Folder ($sub + '/') $subLocal
    }
}

Write-Host "=== 3GPP $defaultRelease Downloader v4 ===" -ForegroundColor Cyan
Write-Host "Output: $baseDir"
Write-Host ""

# Root files
Write-Host "[ROOT]" -ForegroundColor Yellow
try {
    $htmlRoot = $wc.DownloadString($baseUrl)
    $rootFiles = Get-FileLinks $htmlRoot $baseUrl
    foreach ($furl in $rootFiles) {
        $fname = [System.IO.Path]::GetFileName($furl)
        $local = Join-Path $baseDir $fname
        if (Test-Path $local) {
            Write-Host "  [SKIP] $fname"
            $totalSkip++
        } else {
            try {
                Write-Host "  [DOWN] $fname"
                $wc.DownloadFile($furl, $local)
                $totalDl++
            } catch {
                Write-Host "  [ERR]  $fname : $($_.Exception.Message)" -ForegroundColor Red
                $totalErr++
                $failed += $furl
            }
        }
    }
} catch {
    Write-Host "  [ROOT ERR] $($_.Exception.Message)" -ForegroundColor Red
}

# Each series
foreach ($s in $series) {
    Write-Host ""
    Write-Host "=== $s ===" -ForegroundColor Cyan
    $url = $baseUrl + '/' + $s
    $local = Join-Path $baseDir $s
    Process-Folder ($url + '/') $local
}

$wc.Dispose()

Write-Host ""
Write-Host "========================================"
Write-Host "DONE!  Downloaded=$totalDl  Skipped=$totalSkip  Errors=$totalErr" -ForegroundColor Green
Write-Host "Output: $baseDir"
if ($failed.Count -gt 0) {
    Write-Host "Failed files:"
    foreach ($f in $failed) { Write-Host "  $f" -ForegroundColor Red }
}
