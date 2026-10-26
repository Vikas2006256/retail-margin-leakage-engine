# =============================================================================
# setup_env.ps1  — Windows PowerShell Environment Setup Script
# Retail Margin & Inventory Leakage Project
# =============================================================================
# Usage: .\setup_env.ps1
# =============================================================================

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Retail Margin & Inventory Leakage — Environment Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Create virtual environment
Write-Host "[1/4] Creating Python virtual environment (.venv)..." -ForegroundColor Yellow
python -m venv .venv

# Step 2: Activate virtual environment
Write-Host "[2/4] Activating virtual environment..." -ForegroundColor Yellow
& ".venv\Scripts\Activate.ps1"

# Step 3: Upgrade pip and install dependencies
Write-Host "[3/4] Installing dependencies from requirements.txt..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# Step 4: Verify installation
Write-Host "[4/4] Verifying installation..." -ForegroundColor Yellow
python -c "import pandas, numpy, sqlalchemy; print(f'  pandas     : {pandas.__version__}'); print(f'  numpy      : {numpy.__version__}'); print(f'  sqlalchemy : {sqlalchemy.__version__}')"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Setup complete! Next steps:" -ForegroundColor Green
Write-Host ""
Write-Host "  1. Place your Superstore CSV at: data\raw\superstore.csv" -ForegroundColor White
Write-Host "  2. Run: python data_pipeline.py" -ForegroundColor White
Write-Host "  3. Run with verbose: python data_pipeline.py --verbose" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
