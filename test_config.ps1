# Test setup.ps1 config loading
$cfgJson = py -3 "C:\myfile\qclaw\3gpp_rag_work\src\read_config.py" 2>&1
Write-Host "Raw output: $cfgJson"
$cfg = $cfgJson | ConvertFrom-Json
Write-Host "protocol_base: $($cfg.protocol_base)"
Write-Host "embed: $($cfg.embed)"
Write-Host "rerank: $($cfg.rerank)"
Write-Host "log_dir: $($cfg.log_dir)"
