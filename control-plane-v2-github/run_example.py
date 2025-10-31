#!/usr/bin/env python3
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
        choice = int(input("\nSelect a manifest (number): ")) - 1
        selected_manifest = manifests[choice]
    except (ValueError, IndexError):
        print("Invalid selection!")
        sys.exit(1)
    
    print(f"\nRunning control plane with: {selected_manifest}")
    print("=" * 50)
    
    # Run the control plane
    cmd = [sys.executable, "-m", "control_plane_v2.run_control_plane", "--manifest", str(selected_manifest)]
    subprocess.run(cmd)

if __name__ == "__main__":
    main()
