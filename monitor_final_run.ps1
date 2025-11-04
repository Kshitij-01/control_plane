## Monitor Final Optimized Run
## Tracks all fixes and success metrics

$runDir = "runs\run_20251102_143128"

Write-Host "`n=== MONITORING FINAL OPTIMIZED RUN ===" -ForegroundColor Green
Write-Host "Run: run_20251102_143128" -ForegroundColor Cyan
Write-Host "All fixes active: Token limit 65K, 4-layer JSON parsing, Anti-hallucination, Tool guide" -ForegroundColor White

Write-Host "`nWaiting for PDF extraction phase..." -ForegroundColor Yellow

$lastCheck = Get-Date
while ($true) {
    Start-Sleep -Seconds 5
    
    $p2Log = "$runDir\phase2\logs\phase2_execution.log"
    
    if (Test-Path $p2Log) {
        $content = Get-Content $p2Log -Raw
        
        # Check if PDF extraction started
        if ($content -match "Starting PARALLEL extraction of (\d+) PDFs") {
            Write-Host "`n✅ PDF EXTRACTION STARTED!" -ForegroundColor Green
            Write-Host "  Processing $($matches[1]) PDFs" -ForegroundColor Cyan
            
            # Monitor JSON parsing success
            Start-Sleep -Seconds 120  # Wait for extractions to complete
            
            $newContent = Get-Content $p2Log -Raw
            
            Write-Host "`n📊 JSON PARSING RESULTS:" -ForegroundColor Cyan
            
            # Count successes by parser type
            $strictSuccess = ($newContent | Select-String -Pattern "Successfully parsed JSON \(strict parser\)" -AllMatches).Matches.Count
            $pydanticSuccess = ($newContent | Select-String -Pattern "Successfully parsed JSON \(Pydantic\)" -AllMatches).Matches.Count
            $repairSuccess = ($newContent | Select-String -Pattern "Successfully parsed JSON \(json-repair\)" -AllMatches).Matches.Count
            $demjsonSuccess = ($newContent | Select-String -Pattern "Successfully parsed JSON \(demjson3\)" -AllMatches).Matches.Count
            $totalFailed = ($newContent | Select-String -Pattern "ALL JSON parsers failed" -AllMatches).Matches.Count
            
            Write-Host "  Layer 1 (strict): $strictSuccess PDFs" -ForegroundColor Green
            Write-Host "  Layer 2 (Pydantic): $pydanticSuccess PDFs" -ForegroundColor Green
            Write-Host "  Layer 3 (json-repair): $repairSuccess PDFs" -ForegroundColor Green
            Write-Host "  Layer 4 (demjson3): $demjsonSuccess PDFs" -ForegroundColor Green
            Write-Host "  Failed all layers: $totalFailed PDFs" -ForegroundColor Red
            
            $totalSuccess = $strictSuccess + $pydanticSuccess + $repairSuccess + $demjsonSuccess
            $successRate = if (24 -gt 0) { ($totalSuccess / 24 * 100) } else { 0 }
            
            Write-Host "`n🎯 SUCCESS RATE: $totalSuccess/24 ($($successRate.ToString('F1'))%)" -ForegroundColor $(if ($successRate -gt 90) { "Green" } elseif ($successRate -gt 70) { "Yellow" } else { "Red" })
            
            if ($successRate -gt 90) {
                Write-Host "`n🎉 EXCELLENT! Fixes working as expected!" -ForegroundColor Green
            } elseif ($successRate -gt 70) {
                Write-Host "`n✅ GOOD! Significant improvement!" -ForegroundColor Yellow
            } else {
                Write-Host "`n⚠️  Still issues - check logs" -ForegroundColor Red
            }
            
            break
        }
    }
    
    # Show progress every 30 seconds
    if (((Get-Date) - $lastCheck).TotalSeconds -gt 30) {
        Write-Host "." -NoNewline -ForegroundColor Gray
        $lastCheck = Get-Date
    }
}

Write-Host "`nMonitoring complete." -ForegroundColor Cyan

