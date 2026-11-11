<#
.SYNOPSIS
    One-command security scan for RollCall AI.

.DESCRIPTION
    Runs the same checks as CI plus the adversarial suite:

      1. Bandit         - Python static analysis (medium/high fail the build)
      2. pip-audit      - known CVEs in backend requirements
      3. gitleaks       - committed secrets
      4. npm audit      - frontend dependency advisories
      5. pytest         - backend regression suite (includes security tests)
      6. attack suite   - black-box adversarial probes (isolated database)

    Missing optional tools are reported, not silently skipped, and the script
    exits non-zero when any executed check fails.

.EXAMPLE
    pwsh -File scripts/security-scan.ps1
    pwsh -File scripts/security-scan.ps1 -SkipTests
    # CI: the pytest job is separate, still run the adversarial suite
    pwsh -File scripts/security-scan.ps1 -SkipPytest
#>

[CmdletBinding()]
param(
    # Skip both the pytest suite and the adversarial suite.
    [switch]$SkipTests,
    # Skip only pytest (CI runs it in its own job).
    [switch]$SkipPytest,
    # Skip only the adversarial suite.
    [switch]$SkipAttack,
    [switch]$SkipFrontend
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

$results = [System.Collections.Generic.List[object]]::new()
$failed = $false

function Invoke-Check {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    try {
        & $Command
        $code = $LASTEXITCODE
    }
    catch {
        Write-Warning "$Name could not run: $($_.Exception.Message)"
        $code = 127
    }

    $status = if ($code -eq 0) { 'PASS' } elseif ($code -eq 127) { 'SKIPPED' } else { 'FAIL' }
    if ($status -eq 'FAIL') { $script:failed = $true }
    $results.Add([pscustomobject]@{ Check = $Name; Status = $status; ExitCode = $code })
}

Invoke-Check 'Bandit (medium/high)' {
    python -m bandit -r backend/app backend/tools -ll
}

Invoke-Check 'pip-audit (backend requirements)' {
    python -m pip_audit -r backend/requirements.txt
}

Invoke-Check 'gitleaks (committed secrets)' {
    gitleaks detect --source . --config .gitleaks.toml --redact --no-banner
}

if (-not $SkipFrontend) {
    Invoke-Check 'npm audit (frontend)' {
        Push-Location frontend-react
        try { npm audit --audit-level=high } finally { Pop-Location }
    }
}

if (-not $SkipTests) {
    if (-not $SkipPytest) {
        Invoke-Check 'Backend test suite' {
            Push-Location backend
            try { python -m pytest tests -q } finally { Pop-Location }
        }
    }

    if (-not $SkipAttack) {
        Invoke-Check 'Adversarial attack suite' {
            $env:PYTHONPATH = 'backend'
            try { python scripts/person1_attack_suite.py }
            finally { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
        }
    }
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
$results | Format-Table -AutoSize | Out-String | Write-Host

$summaryPath = Join-Path $repoRoot 'reports/security-scan-summary.json'
$results | ConvertTo-Json | Set-Content -Path $summaryPath -Encoding UTF8
Write-Host "Summary written to $summaryPath"

Pop-Location
if ($failed) {
    Write-Error 'Security scan failed: see the failing checks above.'
    exit 1
}
exit 0
