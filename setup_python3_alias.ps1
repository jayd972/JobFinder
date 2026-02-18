# Setup Script - Add Python to Your PowerShell Session
# This script adds Python to your current session and creates a python3 alias

# Add Python to PATH for this session
$pythonPath = "C:\Users\darji\AppData\Local\Programs\Python\Python312"
$pythonScripts = "C:\Users\darji\AppData\Local\Programs\Python\Python312\Scripts"

# Add to current session PATH
$env:Path = "$pythonPath;$pythonScripts;$env:Path"

# Create python3 alias
function global:python3 { python $args }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Python Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "✓ Python added to PATH (this session only)" -ForegroundColor Green
Write-Host "✓ 'python3' alias created" -ForegroundColor Green
Write-Host ""
Write-Host "You can now use:" -ForegroundColor Yellow
Write-Host "  - python app.py" -ForegroundColor White
Write-Host "  - python3 app.py" -ForegroundColor White
Write-Host ""
Write-Host "To make this permanent, see QUICK_START.md" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
