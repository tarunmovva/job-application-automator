#!/usr/bin/env python3
"""
Quick setup script for Job Application Automator MCP Server
Cross-platform installer that handles everything automatically
"""

import subprocess
import sys
import os
import platform
from pathlib import Path

def run_command(command, description, shell=False):
    """Run a command and handle errors."""
    print(f"📦 {description}...")
    try:
        if isinstance(command, str) and not shell:
            command = command.split()
        
        result = subprocess.run(
            command, 
            shell=shell, 
            check=True, 
            capture_output=True, 
            text=True,
            timeout=300  # 5 minute timeout
        )
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed: {e}")
        if e.stderr:
            print(f"Error output: {e.stderr}")
        return False
    except subprocess.TimeoutExpired:
        print(f"❌ {description} timed out")
        return False
    except Exception as e:
        print(f"❌ {description} failed with unexpected error: {e}")
        return False

def check_python():
    """Check Python version."""
    try:
        version = sys.version_info
        if version >= (3, 10):
            print(f"✅ Python {version.major}.{version.minor}.{version.micro} - OK")
            return True
        else:
            print(f"❌ Python {version.major}.{version.minor}.{version.micro} - Requires Python 3.10+")
            return False
    except Exception as e:
        print(f"❌ Python check failed: {e}")
        return False

def check_node():
    """Check Node.js availability (optional)."""
    try:
        result = subprocess.run(
            ["node", "--version"], 
            capture_output=True, 
            text=True, 
            timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"✅ Node.js {version} - OK")
            return True
    except Exception:
        pass
    
    print("⚠️  Node.js not found - some features may be limited")
    return False

def main():
    """Main setup function."""
    print("🚀 Job Application Automator - Quick Setup")
    print("=" * 60)
    print()
    
    # Check prerequisites
    print("🔧 Checking prerequisites...")
    
    if not check_python():
        print("\n❌ SETUP FAILED: Python 3.10+ is required")
        print("Please install Python 3.10 or higher from https://python.org/")
        sys.exit(1)
    
    node_available = check_node()
    
    print()
    
    # Step 1: Install package and dependencies
    print("📦 Installing package and dependencies...")
    
    # Upgrade pip first
    if not run_command([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], "Upgrading pip"):
        print("⚠️  Pip upgrade failed, continuing anyway...")
    
    # Get the project root directory (parent of scripts/)
    project_root = Path(__file__).parent.parent
    
    # Install the package from the project directory
    if not run_command([sys.executable, "-m", "pip", "install", str(project_root)], "Installing job-application-automator"):
        print("❌ Package installation failed")
        print(f"❌ Tried to install from: {project_root}")
        print("❌ Make sure you're running this from the project directory")
        sys.exit(1)
    
    # Step 2: Install Playwright browsers
    print("\n🎭 Installing Playwright browsers...")
    playwright_success = run_command(
        [sys.executable, "-m", "playwright", "install", "chromium"], 
        "Installing Chromium browser"
    )
    
    if not playwright_success:
        print("⚠️  Playwright installation failed - you may need to install manually:")
        print("   playwright install chromium")
    
    # Step 3: Configure Claude Desktop
    print("\n🔧 Configuring Claude Desktop...")
    
    # Try using the installed script first
    claude_setup_success = False
    
    try:
        # Method 1: Use installed command
        claude_setup_success = run_command(
            ["job-automator-setup"], 
            "Configuring Claude Desktop MCP server"
        )
    except Exception:
        pass
    
    if not claude_setup_success:
        try:
            # Method 2: Run setup script directly
            setup_script = Path(__file__).parent.parent / "job_application_automator" / "setup_claude.py"
            if setup_script.exists():
                claude_setup_success = run_command(
                    [sys.executable, str(setup_script)], 
                    "Configuring Claude Desktop MCP server (direct)"
                )
        except Exception:
            pass
    
    if not claude_setup_success:
        print("⚠️  Claude Desktop configuration may need manual setup")
        print("   Run: job-automator-setup")
    
    # Step 4: Success message
    print("\n" + "=" * 60)
    print("🎉 Setup Complete!")
    print("=" * 60)
    
    print("\n📋 What was installed:")
    print("✅ Job Application Automator MCP Server")
    if playwright_success:
        print("✅ Playwright browser automation")
    else:
        print("⚠️  Playwright browsers (may need manual install)")
    
    if claude_setup_success:
        print("✅ Claude Desktop MCP configuration")
    else:
        print("⚠️  Claude Desktop configuration (may need manual setup)")
    
    print(f"\n🔧 Available tools:")
    print("• simple_form_extraction - Extract form fields from job URLs")
    print("• simple_form_filling - Automatically fill job application forms")
    print("• create_cover_letter - Generate personalized cover letters")
    print("• get_applied_jobs - View dashboard of applied jobs")
    print("• health_check - Check MCP server status")
    
    print(f"\n📋 Next steps:")
    print("1. Restart Claude Desktop application completely")
    print("2. Look for job automation tools in Claude Desktop")
    print("3. Test with: 'Extract form data from [job posting URL]'")
    
    if not claude_setup_success:
        print("\n🔧 If tools don't appear in Claude Desktop:")
        print("   Run: job-automator-setup")
    
    if not playwright_success:
        print("\n🎭 If browser automation fails:")
        print("   Run: playwright install chromium")
    
    print("\n📚 Documentation:")
    print("• Installation guide: INSTALL.md")
    print("• Detailed setup: MCP_SERVER_GUIDE.md")
    print("• Project info: README.md")
    
    print("\n✨ Happy job hunting!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Setup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error during setup: {e}")
        print("Please check the installation guide (INSTALL.md) for manual setup")
        sys.exit(1)