#!/usr/bin/env python3
"""
Setup script for Form Automation MCP Server
This script installs dependencies and configures the MCP server for use with Claude Desktop
"""

import subprocess
import sys
import os
import json
import shutil
import platform
import argparse
from pathlib import Path

# Fix Windows encoding issues
if sys.platform == "win32":
    # Ensure UTF-8 encoding for Windows
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    # Set environment variable for child processes
    os.environ['PYTHONIOENCODING'] = 'utf-8'

# Safe emoji printing for cross-platform compatibility
def safe_print(text):
    """Print text with emoji fallback for Windows console issues."""
    try:
        print(text)
    except UnicodeEncodeError:
        # Replace common emojis with text equivalents for Windows compatibility
        fallback_text = text
        emoji_replacements = {
            "🚀": "[*]",
            "📦": "[+]", 
            "✅": "[OK]",
            "❌": "[FAIL]",
            "⚠️": "[WARN]",
            "🔧": "[TOOL]",
            "🎉": "[SUCCESS]",
            "📋": "[INFO]",
            "🟢": "[GOOD]",
            "🟡": "[OK]",
            "🟠": "[BASIC]", 
            "🔴": "[ERROR]",
            "💡": "[TIP]",
            "🔄": "[UPDATE]",
            "📁": "[FOLDER]",
            "🐍": "[PYTHON]",
            "🤖": "[BOT]",
            "🌐": "[NET]",
            "🔐": "[SECURE]",
            "🎭": "[BROWSER]",
            "🟢": "[GOOD]"
        }
        for emoji, replacement in emoji_replacements.items():
            fallback_text = fallback_text.replace(emoji, replacement)
        print(fallback_text)

def run_command(command, description):
    """Run a shell command and handle errors."""
    safe_print(f"📦 {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        safe_print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        safe_print(f"❌ {description} failed: {e}")
        safe_print(f"Error output: {e.stderr}")
        return False

def check_python():
    """Check Python installation."""
    try:
        python_version = sys.version_info
        if python_version >= (3, 10):
            safe_print(f"✅ Python {python_version.major}.{python_version.minor}.{python_version.micro} - OK")
            return True
        else:
            safe_print(f"❌ Python {python_version.major}.{python_version.minor}.{python_version.micro} - Requires Python 3.10+")
            return False
    except Exception as e:
        safe_print(f"❌ Python check failed: {e}")
        return False

def check_nodejs():
    """Check Node.js and npm/npx installation."""
    safe_print("🔧 Checking Node.js prerequisites...")
    
    # Check Node.js
    node_version = None
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True, check=True, timeout=10)
        node_version = result.stdout.strip()
        safe_print(f"✅ Node.js {node_version} - OK")
        node_ok = True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        safe_print(f"❌ Node.js - MISSING (Error: {e})")
        node_ok = False
    
    # Check npm (Windows-specific handling)
    npm_version = None
    if node_ok:
        npm_cmd = "npm.cmd" if platform.system().lower() == "windows" else "npm"
        try:
            result = subprocess.run([npm_cmd, "--version"], capture_output=True, text=True, check=True, timeout=10)
            npm_version = result.stdout.strip()
            safe_print(f"✅ npm {npm_version} - OK")
            npm_ok = True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            safe_print(f"❌ npm - MISSING (Error: {e})")
            npm_ok = False
    else:
        npm_ok = False
    
    # Check npx (Windows-specific handling)
    npx_ok = False
    if npm_ok:
        npx_cmd = "npx.cmd" if platform.system().lower() == "windows" else "npx"
        try:
            result = subprocess.run([npx_cmd, "--version"], capture_output=True, text=True, check=True, timeout=10)
            npx_version = result.stdout.strip()
            safe_print(f"✅ npx {npx_version} - OK")
            npx_ok = True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            safe_print(f"❌ npx - MISSING (Error: {e})")
    
    return node_ok and npm_ok and npx_ok

def show_nodejs_installation_guide():
    """Display platform-specific Node.js installation instructions."""
    safe_print("\n" + "="*60)
    safe_print("📋 Node.js Installation Required")
    safe_print("="*60)
    safe_print("")
    safe_print("To enable job matching features, please install Node.js:")
    safe_print("")
    
    system = platform.system().lower()
    
    if system == "windows":
        safe_print("🪟 Windows Installation:")
        safe_print("  1. Visit https://nodejs.org/")
        safe_print("  2. Download the 'LTS' version (recommended)")
        safe_print("  3. Run the installer with default settings")
        safe_print("  4. Restart your terminal/command prompt")
        safe_print("")
        safe_print("Alternative (if you have Chocolatey):")
        safe_print("  choco install nodejs")
        safe_print("")
        safe_print("Alternative (if you have winget):")
        safe_print("  winget install OpenJS.NodeJS")
        
    elif system == "darwin":
        safe_print("🍎 macOS Installation:")
        safe_print("  Option 1 (Recommended - if you have Homebrew):")
        safe_print("    brew install node")
        safe_print("")
        safe_print("  Option 2 (Manual):")
        safe_print("    1. Visit https://nodejs.org/")
        safe_print("    2. Download the 'LTS' version")
        safe_print("    3. Run the installer")
        safe_print("")
        safe_print("  Option 3 (if you have MacPorts):")
        safe_print("    sudo port install nodejs18")
        
    else:  # Linux and others
        safe_print("🐧 Linux Installation:")
        safe_print("  Ubuntu/Debian:")
        safe_print("    sudo apt update && sudo apt install nodejs npm")
        safe_print("")
        safe_print("  RHEL/CentOS/Fedora:")
        safe_print("    sudo dnf install nodejs npm")
        safe_print("    # or: sudo yum install nodejs npm")
        safe_print("")
        safe_print("  Arch Linux:")
        safe_print("    sudo pacman -S nodejs npm")
        safe_print("")
        safe_print("  From official website:")
        safe_print("    1. Visit https://nodejs.org/")
        safe_print("    2. Download the 'LTS' version for Linux")
        safe_print("    3. Follow installation instructions")
    
    safe_print("")
    safe_print("📝 After installation, verify with:")
    safe_print("  node --version")
    safe_print("  npm --version")
    safe_print("  npx --version")
    safe_print("")
    safe_print("🔄 Then run this setup command again:")
    safe_print("  job-automator-setup")
    safe_print("")
    safe_print("="*60)

def setup_claude_desktop_config():
    """Set up Claude Desktop configuration."""
    safe_print("\n🔧 Configuring Claude Desktop...")
    
    # Claude Desktop config paths
    if os.name == 'nt':  # Windows
        config_dir = Path.home() / "AppData" / "Roaming" / "Claude"
    else:  # macOS/Linux
        config_dir = Path.home() / "Library" / "Application Support" / "Claude"
    
    config_file = config_dir / "claude_desktop_config.json"
    
    # Create config directory if it doesn't exist
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # Find the job-automator-mcp executable
    mcp_command = None
    
    # Method 1: Try to find using shutil.which (works for global installs)
    mcp_command = shutil.which("job-automator-mcp")
    
    if not mcp_command:
        # Method 2: Check in same directory as current Python executable
        python_dir = Path(sys.executable).parent
        if os.name == 'nt':  # Windows
            potential_path = python_dir / "job-automator-mcp.exe"
        else:  # macOS/Linux
            potential_path = python_dir / "job-automator-mcp"
        
        if potential_path.exists():
            mcp_command = str(potential_path)
    
    if not mcp_command:
        # Method 3: Check in Scripts subdirectory (Windows virtual env)
        scripts_dir = Path(sys.executable).parent / "Scripts"
        if scripts_dir.exists():
            if os.name == 'nt':
                potential_path = scripts_dir / "job-automator-mcp.exe"
            else:
                potential_path = scripts_dir / "job-automator-mcp"
            
            if potential_path.exists():
                mcp_command = str(potential_path)
    
    if not mcp_command:
        # Fallback: use just the command name and hope it's in PATH
        mcp_command = "job-automator-mcp"
        safe_print("⚠️  Could not find job-automator-mcp executable, using command name only")
    else:
        safe_print(f"✅ Found job-automator-mcp at: {mcp_command}")
    
    return mcp_command, config_file

def setup_job_automator_server(mcp_command, config_file):
    """Set up the job-automator (local) MCP server."""
    safe_print("🔧 Setting up job-automator MCP server...")
    
    # Read existing config if it exists
    existing_config = {}
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                existing_config = json.load(f)
        except json.JSONDecodeError:
            safe_print("⚠️  Existing Claude config file is invalid, creating new one")
    
    # Ensure mcpServers section exists
    if "mcpServers" not in existing_config:
        existing_config["mcpServers"] = {}
    
    # Add job-automator server
    existing_config["mcpServers"]["job-automator"] = {
        "command": mcp_command
    }
    
    # Write the updated config
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, indent=2)
        safe_print("✅ job-automator MCP server configured")
        return True
    except Exception as e:
        safe_print(f"❌ Failed to configure job-automator MCP server: {e}")
        return False

def setup_job_matcher_server(config_file):
    """Set up the job-matcher (remote) MCP server."""
    safe_print("🔧 Setting up job-matcher MCP server...")
    
    # Read existing config
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            existing_config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        safe_print("❌ Could not read Claude config file")
        return False
    
    # Add job-matcher server
    existing_config["mcpServers"]["job-matcher"] = {
        "command": "npx",
        "args": [
            "mcp-remote",
            "https://mcp-job-matcher.stmovva.workers.dev"
        ]
    }
    
    # Write the updated config
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, indent=2)
        safe_print("✅ job-matcher MCP server configured")
        return True
    except Exception as e:
        safe_print(f"❌ Failed to configure job-matcher MCP server: {e}")
        return False

def test_mcp_server():
    """Test the MCP server installation."""
    safe_print("🧪 Testing MCP server...")
    
    server_path = Path(__file__).parent / "form_automation_server.py"
    
    # Test that the server can be imported
    try:
        # Add the project directory to Python path for testing
        project_dir = Path(__file__).parent.parent
        sys.path.insert(0, str(project_dir))
        
        # Try to import the server modules
        from simple_form_extractor import SimpleFormExtractor
        from simple_form_filler import SimpleFormFiller
        safe_print("✅ Form automation modules imported successfully")
        
        # Validate server exists
        try:
            import job_application_automator.mcp_server
            safe_print("✅ MCP server module found")
        except ImportError:
            safe_print("❌ MCP server module not found")
            return False
        
        return True
    except Exception as e:
        safe_print(f"❌ Validation failed: {e}")
        return False
    
    # Setup Claude Desktop config
    if not setup_claude_desktop_config():
        safe_print("❌ Claude Desktop configuration failed")
        sys.exit(1)
    
    safe_print("\n🎉 Setup completed successfully!")
    safe_print("\n📋 Next steps:")
    safe_print("1. Restart Claude Desktop application")
    safe_print("2. Look for the form automation tools in Claude Desktop")
    safe_print("3. Test with: 'Extract form data from [URL]'")
    safe_print("\n🔧 Available tools:")
    safe_print("- simple_form_extraction: Extract form fields from any URL")
    safe_print("- simple_form_filling: Fill forms with provided data")
    safe_print("- health_check: Check server status")
    
    safe_print(f"\n📁 Server location: {Path(__file__).parent / 'form_automation_server.py'}")
    safe_print(f"📁 Config location: {Path.home() / 'Library/Application Support/Claude/claude_desktop_config.json' if os.name != 'nt' else Path.home() / 'AppData/Roaming/Claude/claude_desktop_config.json'}")

def show_success_message(config_file):
    """Show brief success message after successful setup."""
    safe_print("\n" + "="*60)
    safe_print("🎉 Setup completed successfully!")
    safe_print("="*60)
    safe_print("")
    safe_print("✅ Both MCP servers configured:")
    safe_print("   • job-automator: Form extraction, filling, cover letters")
    safe_print("   • job-matcher: Resume-based job matching")
    safe_print("")
    safe_print("📋 Next steps:")
    safe_print("1. Restart Claude Desktop application")
    safe_print("2. Look for the job automation tools in Claude Desktop")
    safe_print("3. Test with: 'Extract form data from [job posting URL]'")
    safe_print("4. Test job matching with: 'Find jobs matching my resume'")
    safe_print("")
    safe_print(f"📁 Config location: {config_file}")
    safe_print("="*60)

def show_success_message(config_file):
    """Show brief success message after successful setup."""
    safe_print("\n" + "="*60)
    safe_print("🎉 Setup completed successfully!")
    safe_print("="*60)
    safe_print("")
    safe_print("✅ Both MCP servers configured:")
    safe_print("   • job-automator: Form extraction, filling, cover letters")
    safe_print("   • job-matcher: Resume-based job matching")
    safe_print("")
    safe_print("📋 Next steps:")
    safe_print("1. Restart Claude Desktop application")
    safe_print("2. Look for the job automation tools in Claude Desktop")
    safe_print("3. Test with: 'Extract form data from [job posting URL]'")
    safe_print("4. Test job matching with: 'Find jobs matching my resume'")
    safe_print("")
    safe_print(f"📁 Config location: {config_file}")
    safe_print("="*60)

def main():
    """Main entry point for Claude Desktop setup."""
    parser = argparse.ArgumentParser(description='Job Application Automator - Claude Desktop Setup')
    parser.add_argument('--check-only', action='store_true', 
                       help='Only check prerequisites without performing setup')
    args = parser.parse_args()
    
    safe_print("🚀 Job Application Automator - Claude Desktop Setup")
    safe_print("=" * 60)
    
    # Phase 1: Check prerequisites
    safe_print("\n🔧 Checking prerequisites...")
    
    python_ok = check_python()
    if not python_ok:
        safe_print("\n❌ SETUP FAILED: Python 3.10+ is required")
        safe_print("Please install Python 3.10 or higher from https://python.org/")
        sys.exit(1)
    
    nodejs_ok = check_nodejs()
    
    # If only checking prerequisites, show results and exit
    if args.check_only:
        safe_print("\n" + "="*60)
        safe_print("📋 Prerequisite Check Results")
        safe_print("="*60)
        safe_print(f"✅ Python 3.10+: {'PASSED' if python_ok else 'FAILED'}")
        safe_print(f"{'✅' if nodejs_ok else '❌'} Node.js + npm + npx: {'PASSED' if nodejs_ok else 'FAILED'}")
        
        if python_ok and nodejs_ok:
            safe_print("\n🎉 All prerequisites satisfied! You can run 'job-automator-setup' to complete installation.")
        elif not nodejs_ok:
            safe_print("\n⚠️  Node.js is required for full functionality.")
            show_nodejs_installation_guide()
        
        sys.exit(0 if (python_ok and nodejs_ok) else 1)
    
    # For full setup, all prerequisites must be satisfied
    if not nodejs_ok:
        safe_print("\n❌ SETUP STOPPED: Node.js is required for MCP server functionality")
        safe_print("\nThe job application automator requires Node.js to set up MCP servers in Claude Desktop.")
        show_nodejs_installation_guide()
        safe_print("\n💡 After installing Node.js, run this command again:")
        safe_print("   job-automator-setup")
        sys.exit(1)
    
    # Phase 2: Install playwright browsers if needed
    safe_print("\n🎭 Installing Playwright browsers...")
    try:
        run_command("playwright install chromium", "Installing Playwright browser")
    except:
        safe_print("⚠️  Playwright browser installation skipped (may already be installed)")
    
    # Phase 3: Set up Claude Desktop configuration
    safe_print("\n🔧 Configuring Claude Desktop MCP servers...")
    
    mcp_command, config_file = setup_claude_desktop_config()
    
    # Set up job-automator (core functionality)
    automator_success = setup_job_automator_server(mcp_command, config_file)
    
    if not automator_success:
        safe_print("\n❌ SETUP FAILED: Could not configure job-automator MCP server")
        sys.exit(1)
    
    # Set up job-matcher (enhanced functionality)
    matcher_success = setup_job_matcher_server(config_file)
    
    if not matcher_success:
        safe_print("\n❌ SETUP FAILED: Could not configure job-matcher MCP server")
        sys.exit(1)
    
    # Phase 4: Show success message
    show_success_message(config_file)

if __name__ == "__main__":
    main()
