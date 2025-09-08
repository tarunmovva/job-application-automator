#!/usr/bin/env python3
"""
Prerequisites checker for Job Application Automator
Verifies all requirements before installation
"""

import subprocess
import sys
import shutil
import platform
from pathlib import Path

def check_python():
    """Check Python version and installation."""
    print("🐍 Checking Python...")
    try:
        version = sys.version_info
        version_str = f"{version.major}.{version.minor}.{version.micro}"
        
        if version >= (3, 10):
            print(f"✅ Python {version_str} - OK")
            return True
        else:
            print(f"❌ Python {version_str} - Requires Python 3.10+")
            print("   Download from: https://python.org/downloads/")
            return False
    except Exception as e:
        print(f"❌ Python check failed: {e}")
        return False

def check_pip():
    """Check pip installation."""
    print("📦 Checking pip...")
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "--version"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            pip_version = result.stdout.split()[1]
            print(f"✅ pip {pip_version} - OK")
            return True
        else:
            print("❌ pip not available")
            return False
    except Exception as e:
        print(f"❌ pip check failed: {e}")
        return False

def check_git():
    """Check git installation."""
    print("🔧 Checking git...")
    git_path = shutil.which("git")
    if git_path:
        try:
            result = subprocess.run(["git", "--version"], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                git_version = result.stdout.strip().split()[-1]
                print(f"✅ git {git_version} - OK")
                return True
        except Exception:
            pass
    
    print("⚠️  git not found - needed for cloning repository")
    print("   Download from: https://git-scm.com/downloads")
    return False

def check_node():
    """Check Node.js installation (optional)."""
    print("🟢 Checking Node.js (optional)...")
    try:
        # Try different node commands based on platform
        node_cmd = "node"
        if platform.system() == "Windows":
            # Try node.exe first
            if not shutil.which("node"):
                node_cmd = "node.exe"
        
        result = subprocess.run([node_cmd, "--version"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            node_version = result.stdout.strip()
            print(f"✅ Node.js {node_version} - OK")
            
            # Check npm
            npm_cmd = "npm"
            if platform.system() == "Windows":
                npm_cmd = "npm.cmd"
            
            npm_result = subprocess.run([npm_cmd, "--version"], 
                                      capture_output=True, text=True, timeout=10)
            if npm_result.returncode == 0:
                npm_version = npm_result.stdout.strip()
                print(f"✅ npm {npm_version} - OK")
                return True
            else:
                print("⚠️  npm not found")
                return False
        else:
            print("⚠️  Node.js not found - some features will be limited")
            return False
    except Exception:
        print("⚠️  Node.js not found - some features will be limited")
        return False

def check_claude_desktop():
    """Check if Claude Desktop is likely installed."""
    print("🤖 Checking Claude Desktop...")
    
    system = platform.system()
    claude_paths = []
    
    if system == "Windows":
        # Common Windows installation paths
        claude_paths = [
            Path.home() / "AppData" / "Local" / "Claude" / "Claude.exe",
            Path.home() / "AppData" / "Roaming" / "Claude",
            Path("C:") / "Program Files" / "Claude",
            Path("C:") / "Program Files (x86)" / "Claude"
        ]
    elif system == "Darwin":  # macOS
        claude_paths = [
            Path("/Applications/Claude.app"),
            Path.home() / "Applications" / "Claude.app"
        ]
    else:  # Linux
        claude_paths = [
            Path.home() / ".local" / "share" / "applications" / "claude.desktop",
            Path("/usr/share/applications/claude.desktop"),
            Path.home() / "Applications" / "Claude"
        ]
    
    for path in claude_paths:
        if path.exists():
            print(f"✅ Claude Desktop found at: {path}")
            return True
    
    print("⚠️  Claude Desktop not detected")
    print("   Download from: https://claude.ai/desktop")
    return False

def check_network():
    """Check internet connectivity."""
    print("🌐 Checking network connectivity...")
    try:
        import urllib.request
        urllib.request.urlopen('https://pypi.org', timeout=10)
        print("✅ Internet connection - OK")
        return True
    except Exception:
        print("❌ Internet connection failed")
        print("   Required for downloading dependencies")
        return False

def check_permissions():
    """Check write permissions in current directory."""
    print("🔐 Checking permissions...")
    try:
        test_file = Path("test_permissions.tmp")
        test_file.write_text("test")
        test_file.unlink()
        print("✅ Write permissions - OK")
        return True
    except Exception:
        print("❌ Write permissions insufficient")
        print("   Run with appropriate permissions or choose different directory")
        return False

def show_installation_summary(results):
    """Show summary and installation recommendations."""
    print("\n" + "="*60)
    print("📋 Prerequisites Summary")
    print("="*60)
    
    # Critical requirements
    critical = ["python", "pip", "network", "permissions"]
    critical_passed = all(results.get(req, False) for req in critical)
    
    # Optional requirements
    optional = ["git", "node", "claude_desktop"]
    optional_passed = sum(results.get(req, False) for req in optional)
    
    print(f"\n🔥 Critical Requirements: {'✅ PASSED' if critical_passed else '❌ FAILED'}")
    for req in critical:
        status = "✅" if results.get(req, False) else "❌"
        print(f"   {status} {req.replace('_', ' ').title()}")
    
    print(f"\n⭐ Optional Requirements: {optional_passed}/{len(optional)} met")
    for req in optional:
        status = "✅" if results.get(req, False) else "⚠️ "
        print(f"   {status} {req.replace('_', ' ').title()}")
    
    print(f"\n🎯 Installation Readiness:")
    if critical_passed:
        if optional_passed >= 2:
            print("🟢 EXCELLENT - All systems ready for full installation")
        elif optional_passed >= 1:
            print("🟡 GOOD - Ready for installation with some limitations")
        else:
            print("🟠 BASIC - Core functionality will work")
    else:
        print("🔴 NOT READY - Fix critical requirements first")
    
    return critical_passed

def main():
    """Run all prerequisite checks."""
    print("🚀 Job Application Automator - Prerequisites Check")
    print("="*60)
    print()
    
    # Run all checks
    results = {
        "python": check_python(),
        "pip": check_pip(),
        "git": check_git(),
        "node": check_node(),
        "claude_desktop": check_claude_desktop(),
        "network": check_network(),
        "permissions": check_permissions()
    }
    
    # Show summary
    ready = show_installation_summary(results)
    
    print(f"\n📝 Next Steps:")
    if ready:
        print("✅ Run the installation: python scripts/quick_setup.py")
    else:
        print("❌ Fix the critical requirements above, then run this check again")
        
    print(f"\n📚 For help with installation:")
    print("• See INSTALL.md for detailed instructions")
    print("• Check platform-specific setup guides")
    
    return 0 if ready else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n❌ Check cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        sys.exit(1)