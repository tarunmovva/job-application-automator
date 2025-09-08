#!/bin/bash
# Job Application Automator - Linux/macOS Setup Script

set -e  # Exit on any error

echo "🚀 Job Application Automator - Setup for Linux/macOS"
echo "============================================================"

# Check Python version
echo "🔧 Checking Python version..."
python_version=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
required_version="3.10"

if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
    echo "❌ Python 3.10+ required. Found: Python $python_version"
    echo "Please install Python 3.10 or higher"
    exit 1
fi

echo "✅ Python $python_version - OK"

# Check if we're in a virtual environment
if [[ "$VIRTUAL_ENV" != "" ]]; then
    echo "✅ Virtual environment detected: $VIRTUAL_ENV"
else
    echo "⚠️  No virtual environment detected. Consider using one:"
    echo "   python3 -m venv venv"
    echo "   source venv/bin/activate"
    echo ""
fi

# Install package
echo "📦 Installing Job Application Automator..."
python3 -m pip install --upgrade pip
python3 -m pip install .

# Install Playwright browsers
echo "🎭 Installing Playwright browsers..."
python3 -m playwright install chromium

# Configure Claude Desktop
echo "🔧 Configuring Claude Desktop..."
if command -v job-automator-setup &> /dev/null; then
    job-automator-setup
else
    python3 job_application_automator/setup_claude.py
fi

echo ""
echo "============================================================"
echo "🎉 Setup Complete!"
echo "============================================================"
echo ""
echo "📋 Next steps:"
echo "1. Restart Claude Desktop application"
echo "2. Look for job automation tools in Claude Desktop"
echo "3. Test with: 'Extract form data from [job URL]'"
echo ""
echo "📚 Documentation:"
echo "• Installation guide: INSTALL.md"
echo "• Setup guide: MCP_SERVER_GUIDE.md"
echo ""
echo "✨ Happy job hunting!"