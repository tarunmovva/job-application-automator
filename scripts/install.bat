@echo off
REM Job Application Automator - Windows Setup Script

echo 🚀 Job Application Automator - Setup for Windows
echo ============================================================

REM Check Python version
echo 🔧 Checking Python version...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python not found. Please install Python 3.10+ from https://python.org/
    pause
    exit /b 1
)

REM Check if python version is adequate (basic check)
python -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ❌ Python 3.10+ required. Please upgrade your Python installation.
    pause
    exit /b 1
)

echo ✅ Python version - OK

REM Check if we're in a virtual environment
if defined VIRTUAL_ENV (
    echo ✅ Virtual environment detected: %VIRTUAL_ENV%
) else (
    echo ⚠️  No virtual environment detected. Consider using one:
    echo    python -m venv venv
    echo    venv\Scripts\activate
    echo.
)

REM Install package
echo 📦 Installing Job Application Automator...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo ❌ Failed to upgrade pip
    pause
    exit /b 1
)

python -m pip install .
if errorlevel 1 (
    echo ❌ Failed to install package
    pause
    exit /b 1
)

REM Install Playwright browsers
echo 🎭 Installing Playwright browsers...
python -m playwright install chromium
if errorlevel 1 (
    echo ⚠️  Playwright installation failed - you may need to install manually
    echo    python -m playwright install chromium
)

REM Configure Claude Desktop
echo 🔧 Configuring Claude Desktop...
job-automator-setup >nul 2>&1
if errorlevel 1 (
    REM Fallback to direct script execution
    python job_application_automator\setup_claude.py
    if errorlevel 1 (
        echo ⚠️  Claude Desktop configuration may need manual setup
        echo    Run: job-automator-setup
    )
)

echo.
echo ============================================================
echo 🎉 Setup Complete!
echo ============================================================
echo.
echo 📋 Next steps:
echo 1. Restart Claude Desktop application
echo 2. Look for job automation tools in Claude Desktop
echo 3. Test with: 'Extract form data from [job URL]'
echo.
echo 📚 Documentation:
echo • Installation guide: INSTALL.md
echo • Setup guide: MCP_SERVER_GUIDE.md
echo.
echo ✨ Happy job hunting!
pause