#!/usr/bin/env python3
"""
Script to prepare the control plane for GitHub upload.
This script creates a clean repository structure ready for upload.
"""

import os
import shutil
import json
from pathlib import Path

def create_github_repo():
    """Create a clean repository structure for GitHub upload."""
    
    # Create the repository directory
    repo_dir = Path("control-plane-v2-github")
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    repo_dir.mkdir()
    
    print(f"Creating repository structure in: {repo_dir}")
    
    # Copy control_plane_v2 folder
    print("Copying control_plane_v2 folder...")
    shutil.copytree("control_plane_v2", repo_dir / "control_plane_v2")
    
    # Copy essential files
    essential_files = [
        "README.md",
        "requirements.txt", 
        ".gitignore",
        "env_info.json.example"
    ]
    
    for file in essential_files:
        if Path(file).exists():
            print(f"Copying {file}...")
            shutil.copy2(file, repo_dir / file)
    
    # Copy example manifests
    print("Copying example manifests...")
    manifest_files = [
        "manifest_brca_analysis.json",
        "manifest_enmapper_migration.json", 
        "manifest_earthquake_synthetic.json"
    ]
    
    for manifest in manifest_files:
        if Path(manifest).exists():
            shutil.copy2(manifest, repo_dir / manifest)
    
    # Create a simple run script
    run_script = repo_dir / "run_example.py"
    with open(run_script, 'w') as f:
        f.write('''#!/usr/bin/env python3
"""
Example script to run the control plane.
"""

import subprocess
import sys
from pathlib import Path

def main():
    """Run the control plane with an example manifest."""
    
    # Check if env_info.json exists
    if not Path("env_info.json").exists():
        print("ERROR: env_info.json not found!")
        print("Please copy env_info.json.example to env_info.json and configure your API keys.")
        sys.exit(1)
    
    # List available manifests
    manifests = list(Path(".").glob("manifest_*.json"))
    if not manifests:
        print("ERROR: No manifest files found!")
        sys.exit(1)
    
    print("Available manifests:")
    for i, manifest in enumerate(manifests, 1):
        print(f"  {i}. {manifest.name}")
    
    # Let user choose
    try:
        choice = int(input("\\nSelect a manifest (number): ")) - 1
        selected_manifest = manifests[choice]
    except (ValueError, IndexError):
        print("Invalid selection!")
        sys.exit(1)
    
    print(f"\\nRunning control plane with: {selected_manifest}")
    print("=" * 50)
    
    # Run the control plane
    cmd = [sys.executable, "-m", "control_plane_v2.run_control_plane", "--manifest", str(selected_manifest)]
    subprocess.run(cmd)

if __name__ == "__main__":
    main()
''')
    
    # Create a simple setup script
    setup_script = repo_dir / "setup.py"
    with open(setup_script, 'w') as f:
        f.write('''#!/usr/bin/env python3
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
        print("\\nCreating env_info.json from template...")
        shutil.copy2("env_info.json.example", "env_info.json")
        print("\\nIMPORTANT: Please edit env_info.json with your API keys and database credentials!")
        print("\\nRequired configuration:")
        print("- Azure OpenAI API key and endpoint")
        print("- AWS Bedrock credentials for Claude")
        print("- Database connection strings (if using database tasks)")
    else:
        print("\\nenv_info.json already exists.")
    
    print("\\nSetup complete!")
    print("\\nNext steps:")
    print("1. Configure your API keys in env_info.json")
    print("2. Run: python run_example.py")

if __name__ == "__main__":
    import shutil
    main()
''')
    
    # Create a .gitattributes file for proper line endings
    gitattributes = repo_dir / ".gitattributes"
    with open(gitattributes, 'w') as f:
        f.write('''# Ensure proper line endings
*.py text eol=lf
*.md text eol=lf
*.json text eol=lf
*.txt text eol=lf

# Binary files
*.pkl binary
*.pickle binary
*.db binary
*.sqlite binary
''')
    
    print(f"\\nRepository prepared successfully!")
    print(f"Location: {repo_dir.absolute()}")
    print("\\nFiles included:")
    print("- control_plane_v2/ (complete source code)")
    print("- README.md (comprehensive documentation)")
    print("- requirements.txt (Python dependencies)")
    print("- .gitignore (excludes sensitive files)")
    print("- env_info.json.example (configuration template)")
    print("- Example manifest files")
    print("- setup.py (automated setup script)")
    print("- run_example.py (example runner script)")
    
    print("\\nTo upload to GitHub:")
    print(f"1. cd {repo_dir}")
    print("2. git init")
    print("3. git add .")
    print("4. git commit -m 'Initial commit: Control Plane v2'")
    print("5. Create repository on GitHub")
    print("6. git remote add origin <your-repo-url>")
    print("7. git push -u origin main")

if __name__ == "__main__":
    create_github_repo()
