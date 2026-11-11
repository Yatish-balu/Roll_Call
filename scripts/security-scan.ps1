#requires -Version 5.1
<#
.SYNOPSIS
    Runs the Person 2 dependency/security scans locally.

.DESCRIPTION
    * Python dependency audit (pip-audit) against backend/requirements.txt
    * Installed dependency consistency (pip check)
    * Optional static analysis (bandit) when installed
    * Frontend dependency audit (npm audit) and type-check/lint/build

    The script fails (exit 1) when a high/critical finding is reported. Review
    and remediate findings before deploying; do not silence them silently.

.EXAMPLE
    pwsh ./scripts/security-scan.ps1
#>
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$SkipFrontend,
    [switch]$SkipPython
)

$ErrorActionPreference = "Continue"
$failures = @()

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor Cyan
}

Push-Location $RepoRoot
try {
    if (-not $SkipPython) {
        Write-Section "Python dependency audit (pip-audit)"
        $req = Join-Path $RepoRoot "backend\requirements.txt"
        python -m pip_audit -r $req --progress-spinner off
        if ($LASTEXITCODE -ne 0) { $failures += "pip-audit reported findings or failed" }

        Write-Section "Python dependency consistency (pip check)"
        python -m pip check
        if ($LASTEXITCODE -ne 0) { $failures += "pip check reported inconsistent dependencies" }

        Write-Section "Python static analysis (bandit, optional)"
        python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('bandit') else 1)"
        if ($LASTEXITCODE -eq 0) {
            Push-Location (Join-Path $RepoRoot "backend")
            try {
                python -m bandit -r app tools -ll
                if ($LASTEXITCODE -ne 0) { $failures += "bandit reported medium/high findings" }
            }
            finally { Pop-Location }
        }
        else {
            Write-Host "bandit is not installed; skipping (pip install bandit to enable)."
        }
    }

    if (-not $SkipFrontend) {
        $frontend = Join-Path $RepoRoot "frontend-react"
        if (Test-Path $frontend) {
            Push-Location $frontend
            try {
                Write-Section "Frontend dependency audit (npm audit)"
                npm audit --audit-level=high
                if ($LASTEXITCODE -ne 0) { $failures += "npm audit reported high/critical findings" }

                Write-Section "Frontend type-check"
                npx tsc -b --pretty false
                if ($LASTEXITCODE -ne 0) { $failures += "TypeScript compilation failed" }

                Write-Section "Frontend lint"
                npm run lint
                if ($LASTEXITCODE -ne 0) { $failures += "ESLint failed" }

                Write-Section "Frontend production build"
                npm run build
                if ($LASTEXITCODE -ne 0) { $failures += "Vite build failed" }
            }
            finally { Pop-Location }
        }
        else {
            Write-Host "frontend-react not found; skipping frontend checks."
        }
    }
}
finally {
    Pop-Location
}

Write-Host ""
if ($failures.Count -gt 0) {
    Write-Host "Security scan failed:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
    exit 1
}

Write-Host "Security scan completed with no blocking findings." -ForegroundColor Green
