# ============================================================
# synthetix-alpha — Institutional Benchmark Suite
# ============================================================
# Runs all strategies, verifies robustness, tests OOS,
# dry-runs the pipeline, and aggregates results into a
# timestamped Markdown + JSON report.
#
# Prerequisites:
#   pip install -e .[dev]
#   dolt clone post-no-preference/options datasets/options
#   cp .env.example .env (fill in API keys if using live pipeline)
# ============================================================

param(
    [switch]$SkipTests,
    [switch]$SkipKaggle,
    [switch]$SkipDolt,
    [switch]$SkipVerify,
    [switch]$SkipPipeline,
    [switch]$SkipAggregate
)

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot | Split-Path -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"
$doltBin = Join-Path $env:LOCALAPPDATA "Dolt\bin\dolt-windows-amd64\bin\dolt.exe"
if (-not (Test-Path $doltBin)) {
    $doltBin = "dolt"
}
$env:DOLT_BIN = $doltBin
$ts = Get-Date -Format "yyyy-MM-dd_HHmmss"
$resultsDir = Join-Path $root "results"
$reportDir = Join-Path $resultsDir $ts
New-Item -ItemType Directory -Force $reportDir | Out-Null

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " SYNTHETIX-ALPHA INSTITUTIONAL BENCHMARK SUITE" -ForegroundColor Cyan
Write-Host " Run: $ts" -ForegroundColor Cyan
Write-Host " Output: $reportDir" -ForegroundColor Cyan
Write-Host "============================================================`n" -ForegroundColor Cyan

$totalStart = Get-Date
$phase = 0

function Phase($name, $script) {
    $script:phase++
    Write-Host "`n--- PHASE $phase : $name ---" -ForegroundColor Yellow
    $start = Get-Date
    try {
        & $script
        $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds, 1)
        Write-Host "    [$phase] $name : OK ($elapsed s)" -ForegroundColor Green
    } catch {
        $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds, 1)
        Write-Host "    [$phase] $name : FAILED ($elapsed s) - $_" -ForegroundColor Red
    }
}

# ============================================================
# PHASE 1: Test Suite
# ============================================================
if (-not $SkipTests) {
    Phase "Test Suite" {
        & $python -m pytest $root\tests\ -v --tb=short 2>&1 | Tee-Object -FilePath (Join-Path $reportDir "test_suite.log")
    }
}

# ============================================================
# PHASE 2: Kaggle Backtests (all specs)
# ============================================================
if (-not $SkipKaggle) {
    $specs = @(
        "put_vertical_ivrv",
        "put_vertical_ivrv_chainonly",
        "put_vertical_singlename",
        "put_vertical_multi_index",
        "put_vertical_multi_singlename",
        "put_vertical_ivrv_tail",
        "put_diagonal_ivrv",
        "put_diagonal_ivrv_robust",
        "index_condor_trend"
    )
    foreach ($spec in $specs) {
        Phase "Backtest: $spec (Kaggle)" {
            $out = Join-Path $reportDir "$spec.json"
            & $python -m synthetix_alpha.strategy.run (Join-Path $root "strategies\$spec.json") --out $out 2>&1 | Tee-Object -FilePath (Join-Path $reportDir "$spec.log")
        }
    }
}
# ============================================================
# PHASE 3: Dolt OOS Backtests (2019-2026)
# ============================================================
if (-not $SkipDolt) {
    $doltSpecs = @(
        @{name="put_vertical_ivrv"; underlyings="SPY"; start="2019-01-01"},
        @{name="put_vertical_multi_index"; underlyings="SPY"; start="2019-01-01"}
    )
    foreach ($s in $doltSpecs) {
        Phase "Backtest: $($s.name) (dolt OOS)" {
            $out = Join-Path $reportDir "$($s.name)_dolt.json"
            & $python -m synthetix_alpha.strategy.run (Join-Path $root "strategies\$($s.name).json") `
                --source dolt --underlyings $s.underlyings --start $s.start --out $out 2>&1 | Tee-Object -FilePath (Join-Path $reportDir "$($s.name)_dolt.log")
        }
    }
}

# ============================================================
# PHASE 4: Verify (fragility + OOS)
# ============================================================
if (-not $SkipVerify) {
    $verifySpecs = @(
        @{name="put_vertical_ivrv"; oos="AAPL,NVDA,TSLA"},
        @{name="put_vertical_multi_index"; oos="AAPL"},
        @{name="put_vertical_multi_singlename"; oos="SPY"}
    )
    foreach ($s in $verifySpecs) {
        Phase "Verify: $($s.name)" {
            $out = Join-Path $reportDir "verify_$($s.name).json"
            & $python -m synthetix_alpha.strategy.verify (Join-Path $root "strategies\$($s.name).json") `
                --oos $s.oos --out $out 2>&1 | Tee-Object -FilePath (Join-Path $reportDir "verify_$($s.name).log")
        }
    }
}

# ============================================================
# PHASE 5: Pipeline Dry-Runs
# ============================================================
if (-not $SkipPipeline) {
    $pipelineSpecs = @("put_vertical_ivrv", "put_vertical_multi_index", "put_vertical_multi_singlename")
    foreach ($spec in $pipelineSpecs) {
        Phase "Pipeline dry-run: $spec" {
            & $python -m synthetix_alpha.pipeline.orchestrator `
                --spec (Join-Path $root "strategies\$spec.json") `
                --mock-llm --dry-run --confidence 70 2>&1 | Tee-Object -FilePath (Join-Path $reportDir "pipeline_$spec.log")
        }
    }
}

# ============================================================
# PHASE 6: Aggregate
# ============================================================
if (-not $SkipAggregate) {
    Phase "Aggregate benchmark report" {
        & $python (Join-Path $root "scripts\aggregate_benchmarks.py") $reportDir 2>&1 | Tee-Object -FilePath (Join-Path $reportDir "aggregate.log")
    }
}

# ============================================================
# SUMMARY
# ============================================================
$totalElapsed = [math]::Round(((Get-Date) - $totalStart).TotalSeconds, 1)
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " BENCHMARK SUITE COMPLETE" -ForegroundColor Cyan
Write-Host " Total time: $totalElapsed s" -ForegroundColor Cyan
Write-Host " Report: $reportDir\benchmark_report.md" -ForegroundColor Cyan
Write-Host "============================================================`n" -ForegroundColor Cyan
