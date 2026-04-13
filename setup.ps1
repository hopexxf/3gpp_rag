#!/usr/bin/env pwsh
# ============================================================
# 3GPP RAG 一键初始化脚本
# ============================================================
# 用法:
#   .\setup.ps1           # 全量初始化（依赖+模型+协议+数据库）
#   .\setup.ps1 -Mode db  # 仅重建数据库（假设其他已就绪）
#   .\setup.ps1 -Mode dl  # 仅下载协议
#
# 日志: C:\myfile\qclaw\log\setup_YYYY-MM-DD.log
# ============================================================

param(
    [ValidateSet("full", "db", "dl")]
    [string]$Mode = "full"
)

# ======================= 变量 =======================
$ErrorActionPreference = 'Continue'
$WORK_DIR   = "C:\myfile\qclaw\3gpp_rag_work"
$PROTOCOL   = "C:\myfile\project\3gpp_protocol"
$LOG_DIR    = "C:\myfile\qclaw\log"
$REL_DIR    = "$PROTOCOL\Rel-19\38_series"
$EMBED_MODEL_PATH  = "C:\myfile\project\all-MiniLM-L6-v2"
$RERANK_MODEL_PATH = "C:\myfile\project\ms-marco-MiniLM-L6-v2"

# 3GPP 下载源
$BASE_URL_3GPP = "https://www.3gpp.org/ftp/Specs/2026-03/Rel-19"
$SERIES_LIST    = @('22_series','23_series','24_series','25_series','26_series','27_series',
                    '28_series','29_series','31_series','32_series','33_series','34_series',
                    '35_series','36_series','37_series','38_series')

# ======================= 工具函数 =======================

function Get-LogFile {
    $d = $LOG_DIR
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    return Join-Path $d ("setup_" + (Get-Date -Format "yyyy-MM-dd") + ".log")
}
$LOG_FILE = Get-LogFile

function Write-Log {
    param([string]$Msg, [string]$Level = "INFO")
    $line = ("[" + (Get-Date -Format "HH:mm:ss") + "][" + $Level + "] " + $Msg)
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

function Test-Pkg {
    param([string]$Mod)
    $null = py -3 -c ("import " + $Mod) 2>&1
    return ($LASTEXITCODE -eq 0)
}

function New-Path-Create {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
        Write-Log ("Created: " + $Path)
    }
}

# ======================= 协议下载 =======================

function Invoke-DownloadSpecs {
    Write-Log "=== 开始下载 3GPP Rel-19 协议 ===" "STEP"

    $fileExts = @('.pdf','.doc','.docx','.xls','.xlsx','.zip','.tar.gz','.tgz','.rtf','.cdf')
    $visited  = @{}
    $totalDl = 0; $totalSkip = 0; $totalErr = 0
    $failed = @()

    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")

    function Is-RealDir($url) {
        $low = $url.ToLower()
        foreach ($ext in $fileExts) { if ($low.EndsWith($ext)) { return $false } }
        return $true
    }

    function Get-FileLinks($html, $base) {
        $links = @()
        $re = [regex] "href=""(https://www\.3gpp\.org/ftp/Specs/[^""?\s]+\.(?:pdf|doc|docx|xls|xlsx|zip|tar\.gz|tgz|rtf|cdf))"""
        $re.Matches($html) | ForEach-Object {
            $url = $_.Groups[1].Value
            if ($url.StartsWith($base + "/") -and -not $url.EndsWith("/") -and $url.Length -gt ($base.Length + 1)) {
                $links += $url
            }
        }
        return $links
    }

    function Get-SubDirs($html, $base) {
        $dirs = @()
        $re = [regex] "href=""(https://www\.3gpp\.org/ftp/Specs/[^""]+)"""
        $re.Matches($html) | ForEach-Object {
            $url = $_.Groups[1].Value.TrimEnd("/")
            if ($url -ne $base -and (Is-RealDir $url)) { $dirs += $url }
        }
        return $dirs
    }

    function Process-Folder {
        param($url, $localDir)
        if ($visited.ContainsKey($url)) { return }
        $visited[$url] = $true
        New-Path-Create $localDir

        Write-Log ("[SCAN] " + $url)
        $html = $wc.DownloadString($url)

        Get-FileLinks $html $BASE_URL_3GPP | ForEach-Object {
            $furl = $_; $fname = [System.IO.Path]::GetFileName($furl)
            $relF = $furl.Substring($BASE_URL_3GPP.Length + 1).Replace("/", "\")
            $local = Join-Path $PROTOCOL $relF
            $dir = Split-Path $local -Parent
            New-Path-Create $dir

            if (Test-Path $local) {
                Write-Log ("  [SKIP] " + $fname); $script:totalSkip++
            } else {
                try {
                    Write-Log ("  [DOWN] " + $fname)
                    $wc.DownloadFile($furl, $local); $script:totalDl++
                } catch {
                    Write-Log ("  [ERR]  " + $fname + " : " + $_.Exception.Message) "ERROR"
                    $script:totalErr++; $script:failed += $furl
                }
            }
        }

        Get-SubDirs $html $BASE_URL_3GPP | ForEach-Object {
            $sub = $_; $relSub = $sub.Substring($BASE_URL_3GPP.Length + 1).Replace("/", "\")
            Process-Folder -url ($sub + "/") -localDir (Join-Path $PROTOCOL $relSub)
        }
    }

    # 根目录
    Write-Log "[ROOT]" "STEP"
    try {
        Get-FileLinks ($wc.DownloadString($BASE_URL_3GPP)) $BASE_URL_3GPP | ForEach-Object {
            $furl = $_; $fname = [System.IO.Path]::GetFileName($furl)
            $local = Join-Path $PROTOCOL $fname
            if (Test-Path $local) { Write-Log ("  [SKIP] " + $fname); $totalSkip++ }
            else {
                try { Write-Log ("  [DOWN] " + $fname); $wc.DownloadFile($furl, $local); $totalDl++ }
                catch { Write-Log ("  [ERR]  " + $fname) "ERROR"; $totalErr++; $failed += $furl }
            }
        }
    } catch { Write-Log ("  [ROOT ERR] " + $_.Exception.Message) "ERROR" }

    # 各 series
    foreach ($s in $SERIES_LIST) {
        Write-Log ""; Write-Log ("=== " + $s + " ===") "STEP"
        Process-Folder -url ($BASE_URL_3GPP + "/" + $s + "/") -localDir (Join-Path $PROTOCOL $s)
    }

    $wc.Dispose()
    Write-Log ""
    Write-Log ("下载完成: Downloaded=" + $totalDl + "  Skipped=" + $totalSkip + "  Errors=" + $totalErr) "INFO"
    $failed | ForEach-Object { Write-Log ("  FAIL: " + $_) "WARN" }
}

# ======================= 数据库构建 =======================

function Invoke-BuildDatabase {
    Write-Log "=== 开始构建数据库 ===" "STEP"

    if (-not (Test-Path $REL_DIR)) {
        Write-Log ("ERROR: 协议目录不存在: " + $REL_DIR) "ERROR"
        exit 1
    }
    $allZips = Get-ChildItem $REL_DIR -Filter "*.zip" | Sort-Object Length
    Write-Log ("发现 " + $allZips.Count + " 个 zip 文件")

    # 去重
    $specMap = @{}
    foreach ($zf in $allZips) {
        if ($zf.BaseName -match "^(\d{2})(\d{3})") {
            $sn = ($Matches[1] + "." + $Matches[2])
            if (-not $specMap.ContainsKey($sn)) { $specMap[$sn] = $zf.FullName }
        }
    }
    $specList = @($specMap.Keys | Sort-Object)
    Write-Log ("去重后: " + $specList.Count + " 个协议")

    # 清理旧数据库
    $dbDir = ($WORK_DIR + "\data\chroma_db\rel19")
    if (Test-Path $dbDir) {
        Write-Log ("清空旧数据库: " + $dbDir)
        Remove-Item ($dbDir + "\*") -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        New-Path-Create $dbDir
    }

    # 写 Python 构建脚本（完全避免 PS 变量展开）
    $tmpPy = Join-Path $WORK_DIR "setup_build_db.py"
    $pyLines = @(
        "import sys, json, traceback",
        "from pathlib import Path",
        "",
        ("WORK_DIR = Path(r'" + $WORK_DIR + "').resolve()"),
        "sys.path.insert(0, str(WORK_DIR / 'src'))",
        "",
        "from config_loader import load_config",
        "from manage_spec import DatabaseManager, SpecManager",
        "",
        "load_config()",
        "db_mgr = DatabaseManager()",
        "spec_mgr = SpecManager(db_mgr)",
        "",
        ("specs = [" + ($specList | ForEach-Object { "'" + $_ + "'" }) -join ", " + "]"),
        "total = len(specs)",
        "done = 0; failed = []",
        "",
        "for i, spec in enumerate(specs):",
        "    pct = (i + 1) * 100 // total",
        "    sys.stdout.write('[{}%] {}/{}\n'.format(pct, i+1, total) + ' ' + spec + '\n')",
        "    sys.stdout.flush()",
        "    try:",
        "        ok = spec_mgr.add(spec, 'Rel-19', mode='auto')",
        "        if ok:",
        "            done += 1",
        "            sys.stdout.write('  OK: ' + spec + '\n')",
        "        else:",
        "            failed.append(spec)",
        "            sys.stdout.write('  FAIL: ' + spec + '\n')",
        "    except Exception as e:",
        "        failed.append(spec)",
        "        sys.stdout.write('  ERROR: ' + spec + ' ' + str(e) + '\n')",
        "        traceback.print_exc()",
        "    sys.stdout.flush()",
        "",
        "sys.stdout.write('DONE: {}/{} success, {} failed\n'.format(done, total, len(failed)))",
        "if failed: sys.stdout.write('Failed: ' + ', '.join(failed) + '\n')",
        "sys.stdout.flush()"
    )
    Set-Content -Path $tmpPy -Value $pyLines -Encoding UTF8
    Write-Log "执行 Python 构建脚本（耐心等待，大文件优先）..." "INFO"

    py -3 $tmpPy 2>&1 | ForEach-Object {
        if ($_ -match "^\[") { Write-Log $_ "PY" }
        elseif ($_ -match "^(OK|FAIL|ERROR|DONE|Failed:)") { Write-Log $_ "OK" }
        elseif ($_ -match "^\s+") { Write-Log $_ "PY" }
        else { Write-Log $_ }
    }
    Remove-Item $tmpPy -Force -ErrorAction SilentlyContinue

    # 读最终状态
    Write-Log ""; Write-Log "=== 数据库最终状态 ===" "STEP"
    $tmpStatus = Join-Path $WORK_DIR "setup_status.py"
    $statusLines = @(
        "from pathlib import Path",
        "import sys, json",
        "sys.path.insert(0, str(Path(__file__).parent / 'src'))",
        "from manage_spec import DatabaseManager, SpecManager",
        "st = SpecManager(DatabaseManager()).status()",
        "print(json.dumps(st))"
    )
    Set-Content -Path $tmpStatus -Value $statusLines -Encoding UTF8
    $statusOut = py -3 $tmpStatus 2>&1
    Remove-Item $tmpStatus -Force -ErrorAction SilentlyContinue
    try {
        $st = $statusOut | ConvertFrom-Json
        $st.releases.PSObject.Properties | ForEach-Object {
            $rel = $_.Name; $data = $_.Value
            Write-Log ($rel + " : " + $data.total + " docs, " + $data.specs + " specs") "OK"
        }
        Write-Log ("Total: " + $st.total + " docs") "OK"
    } catch {
        $statusOut | ForEach-Object { Write-Log $_ }
    }
}

# ======================= Search 验证 =======================

function Test-Search {
    Write-Log ""; Write-Log "=== Search 验证 ===" "STEP"
    $tmpFile = Join-Path $WORK_DIR "setup_test_search.py"
    $searchLines = @(
        "from pathlib import Path",
        "import sys",
        "sys.path.insert(0, str(Path(__file__).parent / 'src'))",
        "from search import HybridSearch",
        "hs = HybridSearch(release='Rel-19')",
        "r = hs.search('random access', top_k=3, mode='hybrid')",
        "print('Search OK:', len(r), 'results')",
        "for item in r:",
        "    spec = item.get('spec', '?')",
        "    clause = item.get('clause', '?')",
        "    title = (item.get('title', '') or '')[:50]",
        "    print('  [' + spec + '] ' + clause + ' ' + title)"
    )
    Set-Content -Path $tmpFile -Value $searchLines -Encoding UTF8
    py -3 $tmpFile 2>&1 | ForEach-Object { Write-Log $_ "OK" }
    Remove-Item $tmpFile -Force -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -eq 0) {
        Write-Log "3GPP RAG 已就绪，可以开始查询！" "OK"
    } else {
        Write-Log "Search 验证失败，请检查错误日志" "ERROR"
    }
}

# ======================= 主流程 =======================

$START = Get-Date
Write-Log ""
Write-Log "========================================" "INFO"
Write-Log (" 3GPP RAG 一键初始化 " + (Get-Date -Format "yyyy-MM-dd HH:mm")) "INFO"
Write-Log (" 模式: " + $Mode) "INFO"
Write-Log "========================================" "INFO"

# 阶段 0: 环境检查
if ($Mode -eq "full") {
    Write-Log ""; Write-Log "=== [0/4] 环境检查 ===" "STEP"
    $pyVer = py -3 -c "import sys; print(sys.version)" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: Python 3 未找到，请先安装 Python 3" "ERROR"
        exit 1
    }
    Write-Log ("Python 3: " + $pyVer)

    $pkgs = @{
        "chromadb"             = "chromadb";
        "docx"                 = "python-docx";
        "sentence_transformers" = "sentence-transformers";
        "rank_bm25"            = "rank-bm25";
        "numpy"                = "numpy";
        "tqdm"                 = "tqdm"
    }
    $missing = @()
    foreach ($mod in $pkgs.Keys) {
        if (-not (Test-Pkg $mod)) { $missing += $pkgs[$mod] }
    }
    if ($missing.Count -eq 0) { Write-Log "依赖包: 全部已安装" "OK" }
    else { Write-Log ("缺少依赖: " + ($missing -join ", ")) "WARN" }
}

# 阶段 1: 安装依赖
if ($Mode -eq "full") {
    Write-Log ""; Write-Log "=== [1/4] 安装依赖 ===" "STEP"
    $req = ($WORK_DIR + "\requirements.txt")
    if (-not (Test-Path $req)) {
        Write-Log "ERROR: requirements.txt 不存在" "ERROR"
        exit 1
    }
    Write-Log ("安装: py -3 -m pip install -r " + $req)
    $pipOut = py -3 -m pip install -r $req --quiet 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Log "pip install 失败（可能需要管理员权限），以管理员身份运行 PowerShell 重试" "ERROR"
        exit 1
    }
    $missing2 = @()
    foreach ($mod in $pkgs.Keys) {
        if (-not (Test-Pkg $mod)) { $missing2 += $pkgs[$mod] }
    }
    if ($missing2.Count -eq 0) { Write-Log "依赖安装验证: OK" "OK" }
    else {
        Write-Log ("仍有缺失: " + ($missing2 -join ", ") + "。尝试强制重装...") "WARN"
        py -3 -m pip install ($missing2 -join " ") --quiet 2>&1 | ForEach-Object { Write-Log $_ }
    }
}

# 阶段 2: 模型检查
if ($Mode -eq "full") {
    Write-Log ""; Write-Log "=== [2/4] 模型检查 ===" "STEP"
    if (Test-Path $EMBED_MODEL_PATH)  { Write-Log ("Embedding 模型存在: " + $EMBED_MODEL_PATH) "OK" }
    else { Write-Log "Embedding 模型不存在（将在首次查询时自动下载）" "WARN" }
    if (Test-Path $RERANK_MODEL_PATH) { Write-Log ("Reranker  模型存在: " + $RERANK_MODEL_PATH) "OK" }
    else { Write-Log "Reranker 模型不存在（将在首次查询时自动下载）" "WARN" }
}

# 阶段 3: 协议下载
if ($Mode -in @("full", "dl")) {
    Write-Log ""; Write-Log "=== [3/4] 协议下载 ===" "STEP"
    if (Test-Path $REL_DIR) {
        $cnt = (Get-ChildItem $REL_DIR -File -ErrorAction SilentlyContinue | Measure-Object).Count
        Write-Log ("已有文件: " + $cnt + " 个")
        if ($cnt -ge 50) {
            Write-Log "文件已齐全（>=50），跳过下载。如需重新下载请先删除 " + $REL_DIR "OK"
        } else {
            Invoke-DownloadSpecs | Out-Null
        }
    } else {
        New-Path-Create $REL_DIR
        Invoke-DownloadSpecs | Out-Null
    }
}

# 阶段 4: 数据库构建
if ($Mode -in @("full", "db")) {
    Write-Log ""; Write-Log "=== [4/4] 数据库构建 ===" "STEP"
    if (-not (Test-Path $REL_DIR)) {
        Write-Log "ERROR: 协议目录不存在，请先运行 .\setup.ps1 -Mode dl 下载协议" "ERROR"
        exit 1
    }
    Invoke-BuildDatabase
    Test-Search
}

# 完成
$ELAPSED = [math]::Round(((Get-Date) - $START).TotalMinutes, 1)
Write-Log ""
Write-Log "========================================" "INFO"
Write-Log (" 完成！耗时: " + $ELAPSED + " 分钟") "INFO"
Write-Log (" 日志: " + $LOG_FILE) "INFO"
Write-Log "========================================" "INFO"
