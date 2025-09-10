# Installation Guide

## 🚀 Quick Setup (Recommended)

### Prerequisites
- Python 3.10 or higher
- Node.js and npm (for enhanced features)

### One-Command Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/username/job-application-automator.git
   cd job-application-automator
   ```

2. **Run the setup script:**
   ```bash
   # Cross-platform Python setup (recommended)
   python scripts/quick_setup.py
   
   # Alternative platform-specific scripts:
   # Linux/macOS: ./scripts/install.sh
   # Windows: scripts\install.bat
   ```

3. **Restart Claude Desktop**
   - Close and reopen Claude Desktop application
   - The MCP server will be automatically available

## 🔧 Manual Installation

If you prefer manual installation or the quick setup fails:

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### Step 2: Install Package
```bash
pip install .
# or for development:
pip install -e .
```

### Step 3: Configure Claude Desktop
```bash
job-automator-setup
# or manually run:
python job_application_automator/setup_claude.py
```

## 🧪 Verify Installation

Test that everything is working:

```bash
# Check if package is installed
python -c "import job_application_automator; print('✅ Package installed')"

# Check MCP server
python job_application_automator/mcp_server.py
```

## 🎯 Available Tools

After successful installation, you'll have access to:

1. **`simple_form_extraction`** - Extract form fields from job posting URLs
2. **`simple_form_filling`** - Automatically fill forms with your data
3. **`create_cover_letter`** - Generate personalized cover letter files
4. **`get_applied_jobs`** - View dashboard of all applied jobs
5. **`health_check`** - Check MCP server status

## 🔧 Configuration

### Claude Desktop Config Location
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

### Example Configuration
See `examples/claude_config_example.json` for a sample configuration.

## 🐛 Troubleshooting

### Common Issues

1. **Python version error**: Ensure Python 3.10+
   ```bash
   python --version
   ```

2. **Playwright browser not found**:
   ```bash
   playwright install chromium
   ```

3. **MCP server not appearing in Claude**:
   - Restart Claude Desktop completely
   - Check Claude config file syntax
   - Run `job-automator-setup` again

4. **Permission errors on Windows**:
   - Run terminal as Administrator
   - Or use `--user` flag: `pip install --user .`

### Getting Help

1. Check the [MCP_SERVER_GUIDE.md](MCP_SERVER_GUIDE.md) for detailed documentation
2. Verify prerequisites: `python scripts/check_prerequisites.py`
3. Run health check: Use the `health_check` tool in Claude Desktop

## 🔄 Updating

To update to the latest version:

```bash
git pull origin main
pip install --upgrade .
job-automator-setup
```

---

*For detailed documentation and advanced usage, see [MCP_SERVER_GUIDE.md](MCP_SERVER_GUIDE.md)*