#!/usr/bin/env python3
"""
Setup script for the control plane.
"""

import subprocess
import sys
from pathlib import Path

def main():
    """Setup the control plane environment."""
    
    print("Setting up Control Plane v2...")
    print("=" * 40)
    
    # Install requirements
    print("Installing Python dependencies...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    
    # Check for env_info.json
    if not Path("env_info.json").exists():
        print("\nCreating env_info.json from template...")
        shutil.copy2("env_info.json.example", "env_info.json")
        print("\nIMPORTANT: Please edit env_info.json with your API keys and database credentials!")
        print("\nRequired configuration:")
        print("- Azure OpenAI API key and endpoint")
        print("- AWS Bedrock credentials for Claude")
        print("- Database connection strings (if using database tasks)")
    else:
        print("\nenv_info.json already exists.")
    
    print("\nSetup complete!")
    print("\nNext steps:")
    print("1. Configure your API keys in env_info.json")
    print("2. Run: python run_example.py")

if __name__ == "__main__":
    import shutil
    main()
