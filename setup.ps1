#!/usr/bin/env pwsh
# ============================================================
# 3GPP RAG Setup Script (V2.4 - Config Driven)
# ============================================================
# Usage:
#   .\setup.ps1                        # full init from config.json
#   .\setup.ps1 -Mode db               # db only (incremental)
#   .\setup.ps1 -Mode dl               # download only
#   .\setup.ps1 -ProtocolDir C:\xxx    # override config
#   .\setup.ps1 -EmbedModel C:\model   # override config
#   .\setup.ps1 -RerankModel C:\model  # override config
#   .\setup.ps1 -LogDir C:\log         # override config
#
# Priority: CLI > config.json > default
# Log: <LOG_DIR>/setup_YYYY-MM-DD.log
# ============================================================

param(
    [ValidateSet("full", "db", "dl")]
    [string]$Mode = "full",
    [string]$ProtocolDir,
    [string]$EmbedModel,
    [string]$RerankModel,
    [string]$LogDir
)

# ======================= Config =======================
$ErrorActionPreference = 'Continue'
$WORK_DIR = "C:\myfile\qclaw\3gpp_rag_work"

# Load via config_loader.py (handles empty fallback)
$cfgJson = py -3 (Join-Path $WORK_DIR "src\read_config.py") 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Error "config.json load failed: $cfgJson"
    exit 1
}

$cfg = $cfgJson | ConvertFrom-Json

# CLI > config.json
$PROTOCOL_BASE = if ($ProtocolDir) { $ProtocolDir } else { $cfg.protocol_base }
$EMBED_MODEL_PATH = if ($EmbedModel) { $EmbedModel } else { $cfg.embed }
$RERANK_MODEL_PATH = if ($RerankModel) { $RerankModel } else { $cfg.rerank }
$LOG_DIR = if ($LogDir) { $LogDir } else { $cfg.log_dir }

# ======================= Utils =======================

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

# ======================= Main =======================

$START = Get-Date
Write-Log ""
Write-Log "========================================" "INFO"
Write-Log (" 3GPP RAG Init " + (Get-Date -Format "yyyy-MM-dd HH:mm")) "INFO"
Write-Log (" Mode: " + $Mode) "INFO"
Write-Log "========================================" "INFO"

# Phase 0: Env Check
if ($Mode -eq "full") {
    Write-Log ""; Write-Log "=== [0/3] Env Check ===" "STEP"
    $pyVer = py -3 -c "import sys; print(sys.version)" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: Python 3 not found" "ERROR"; exit 1
    }
    Write-Log ("Python 3: " + $pyVer)

    $pkgs = @{
        "chromadb" = "chromadb"; "docx" = "python-docx";
        "sentence_transformers" = "sentence-transformers"; "rank_bm25" = "rank-bm25";
        "numpy" = "numpy"; "tqdm" = "tqdm"
    }
    $missing = @()
    foreach ($mod in $pkgs.Keys) {
        if (-not (Test-Pkg $mod)) { $missing += $pkgs[$mod] }
    }
    if ($missing.Count -eq 0) { Write-Log "Deps: OK" "OK" }
    else { Write-Log ("Missing: " + ($missing -join ", ")) "WARN" }
}

# Phase 1: Install Deps
if ($Mode -eq "full") {
    Write-Log ""; Write-Log "=== [1/3] Install Deps ===" "STEP"
    $req = Join-Path $WORK_DIR "requirements.txt"
    if (-not (Test-Path $req)) {
        Write-Log "ERROR: requirements.txt not found" "ERROR"; exit 1
    }
    Write-Log ("pip install -r " + $req)
    py -3 -m pip install -r $req --quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: pip install failed" "ERROR"; exit 1
    }
    Write-Log "Deps installed" "OK"
}

# Phase 2: Model Check
if ($Mode -eq "full") {
    Write-Log ""; Write-Log "=== [2/3] Model Check ===" "STEP"
    if (Test-Path $EMBED_MODEL_PATH)  { Write-Log ("Embedding: " + $EMBED_MODEL_PATH) "OK" }
    else { Write-Log "Embedding not found (auto-download)" "WARN" }
    if (Test-Path $RERANK_MODEL_PATH) { Write-Log ("Reranker:  " + $RERANK_MODEL_PATH) "OK" }
    else { Write-Log "Reranker not found (auto-download)" "WARN" }
}

# Phase 3: Download
if ($Mode -in @("full", "dl")) {
    Write-Log ""; Write-Log "=== [3/3] Download ===" "STEP"
    $dlScript = Join-Path $WORK_DIR "download_3gpp_r19.ps1"
    if (-not (Test-Path $dlScript)) {
        Write-Log ("ERROR: " + $dlScript + " not found") "ERROR"; exit 1
    }
    Write-Log ("pwsh " + $dlScript)
    pwsh -File $dlScript 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Download failed" "ERROR"
    } else {
        Write-Log "Download done" "OK"
    }
}

# DB Build
if ($Mode -in @("full", "db")) {
    Write-Log ""; Write-Log "=== DB Build ===" "STEP"

    $manageSpec = Join-Path $WORK_DIR "src\manage_spec.py"
    if (-not (Test-Path $manageSpec)) {
        Write-Log ("ERROR: " + $manageSpec + " not found") "ERROR"; exit 1
    }

    # Incremental: batch-add skips existing
    Write-Log ("py -3 manage_spec.py batch-add --release Rel-19")
    py -3 $manageSpec batch-add --release Rel-19 2>&1 | ForEach-Object { Write-Log $_ }

    Write-Log ""; Write-Log "=== DB Status ===" "STEP"
    py -3 $manageSpec status 2>&1 | ForEach-Object { Write-Log $_ }
}

# Done
$ELAPSED = [math]::Round(((Get-Date) - $START).TotalMinutes, 1)
Write-Log ""
Write-Log "========================================" "INFO"
Write-Log (" Done! " + $ELAPSED + " min") "INFO"
Write-Log (" Log: " + $LOG_FILE) "INFO"
Write-Log "========================================" "INFO"
