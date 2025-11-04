## Continuous Monitor for PDF Extraction
## Watches for Worker to start and detects hallucination issues

$ErrorActionPreference = "SilentlyContinue"
$runDir = Get-ChildItem -Path "runs" -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1

Write-Host "`n=== ANTI-HALLUCINATION MONITOR ===" -ForegroundColor Cyan
Write-Host "Run: $($runDir.Name)" -ForegroundColor Gray
Write-Host "Watching for PDF extraction..." -ForegroundColor Yellow

$lastCount = 0
$extractionStarted = $false

while ($true) {
    Start-Sleep -Seconds 5
    
    $p2Log = "$($runDir.FullName)\phase2\logs\phase2_execution.log"
    
    if (Test-Path $p2Log) {
        $content = Get-Content $p2Log -Raw
        
        # Check if extraction started
        if (-not $extractionStarted) {
            if ($content -match "Starting PARALLEL extraction of (\d+) PDFs") {
                $count = $matches[1]
                $extractionStarted = $true
                Write-Host "`n[$(Get-Date -Format 'HH:mm:ss')] PDF EXTRACTION STARTED!" -ForegroundColor Green
                Write-Host "  Processing $count PDFs in parallel" -ForegroundColor Cyan
                
                if ($count -eq "24") {
                    Write-Host "  ✅ CORRECT COUNT - Matches manifest!" -ForegroundColor Green
                } else {
                    Write-Host "  ⚠️  WARNING: Expected 24, got $count!" -ForegroundColor Red
                }
            }
        }
        
        # Check for validation errors
        $errors = $content | Select-String -Pattern "(INVALID PATH|No such file)" -AllMatches
        if ($errors) {
            Write-Host "`n[$(Get-Date -Format 'HH:mm:ss')] ❌ VALIDATION ERRORS DETECTED!" -ForegroundColor Red
            $errors | Select-Object -First 3 | ForEach-Object {
                Write-Host "  $($_.Line.Substring(0, [Math]::Min(100, $_.Line.Length)))" -ForegroundColor Gray
            }
            break
        }
        
        # Count successful extractions
        $successes = ($content | Select-String -Pattern "Successfully extracted" | Measure-Object).Count
        if ($successes -gt $lastCount) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Progress: $successes PDFs extracted" -ForegroundColor Green
            $lastCount = $successes
        }
        
        # Check if complete
        if ($extractionStarted -and $successes -eq 24) {
            Write-Host "`n[$(Get-Date -Format 'HH:mm:ss')] ✅ ALL 24 PDFs EXTRACTED SUCCESSFULLY!" -ForegroundColor Green
            Write-Host "  No hallucination errors detected!" -ForegroundColor Green
            break
        }
    }
}

Write-Host "`nMonitoring complete." -ForegroundColor Cyan

