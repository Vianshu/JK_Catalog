$ErrorActionPreference = "Continue"

$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$OutDir = "audit_reports\$Timestamp"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Write-Host "Saving all reports to $OutDir\"

Write-Host "[1/6] ruff (lint / style / unused imports)..."
ruff check src main.py 2>&1 | Out-File -FilePath "$OutDir\ruff_report.txt" -Encoding utf8

Write-Host "[2/6] vulture (dead code)..."
vulture src main.py --min-confidence 70 2>&1 | Out-File -FilePath "$OutDir\vulture_report.txt" -Encoding utf8

Write-Host "[3/6] mypy (type checking)..."
mypy src main.py 2>&1 | Out-File -FilePath "$OutDir\mypy_report.txt" -Encoding utf8

Write-Host "[4/6] bandit (security)..."
bandit -r src main.py -f txt -o "$OutDir\bandit_report.txt"

Write-Host "[5/6] pip-audit (vulnerable dependencies)..."
pip-audit 2>&1 | Out-File -FilePath "$OutDir\pip_audit_report.txt" -Encoding utf8

Write-Host "[6/6] pytest + coverage..."
pytest --cov=src --cov-report=term-missing 2>&1 | Out-File -FilePath "$OutDir\pytest_coverage_report.txt" -Encoding utf8

Write-Host ""
Write-Host "Done. Reports saved in: $OutDir\"
Write-Host "Point the AI audit at this folder as context for Step 0."
