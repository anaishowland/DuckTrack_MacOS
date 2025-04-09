import shutil
import sys
from pathlib import Path
from platform import system
from subprocess import CalledProcessError, run
import time # Import time for sleep
import os # Import os for path operations

project_dir = Path(".")
assets_dir = project_dir / "assets"
main_py = project_dir / "main.py"
# Use .png for icon, PyInstaller handles conversion if needed for Windows
icon_file = assets_dir / "duck.png"
app_name = "DuckTrack"

def create_dmg(dist_path: Path, app_name: str):
    """Creates a DMG file for the macOS application bundle."""
    print("\nCreating DMG...")
    app_bundle = dist_path / f"{app_name}.app"
    dmg_path = dist_path / f"{app_name}.dmg"
    temp_mount_dir = Path(f"/Volumes/{app_name}")

    if not app_bundle.exists():
        print(f"Error: Application bundle not found at {app_bundle}")
        return False

    # Remove existing DMG if it exists
    if dmg_path.exists():
        print(f"Removing existing DMG: {dmg_path}")
        dmg_path.unlink()

    # Estimate size (add some buffer)
    try:
        app_size_bytes = sum(f.stat().st_size for f in app_bundle.glob('**/*') if f.is_file())
        dmg_size_mb = int(app_size_bytes / (1024 * 1024) * 1.2) + 50 # 20% buffer + 50MB
        print(f"Estimated app size: {app_size_bytes / (1024*1024):.2f} MB, DMG size: {dmg_size_mb} MB")
    except Exception as e:
        print(f"Warning: Could not accurately estimate app size: {e}. Using default size.")
        dmg_size_mb = 500 # Default size if estimation fails

    # Create a temporary writable DMG
    create_cmd = [
        "hdiutil", "create",
        "-ov",
        "-volname", app_name,
        "-fs", "HFS+",
        "-srcfolder", str(app_bundle),
        "-size", f"{dmg_size_mb}m", # Specify size
        str(dmg_path)
    ]
    print(f"Running: {' '.join(create_cmd)}")
    try:
        run(create_cmd, check=True, capture_output=True)
        print("DMG created successfully.")
        return True
    except CalledProcessError as e:
        print(f"Error creating DMG: {e}")
        print(f"hdiutil stdout: {e.stdout.decode()}")
        print(f"hdiutil stderr: {e.stderr.decode()}")
        return False
    except FileNotFoundError:
        print("Error: 'hdiutil' command not found. This script must be run on macOS.")
        return False

for dir_to_remove in ["dist", "build"]:
    dir_path = project_dir / dir_to_remove
    if dir_path.exists():
        shutil.rmtree(dir_path)

# Build the base PyInstaller command
pyinstaller_cmd = [
    "pyinstaller",
    "--windowed", # Create a GUI app (no console)
    # "--onefile", # Changed to --onedir (default) for better compatibility
    f"--add-data={assets_dir}:assets", # Bundle assets dir into 'assets' in bundle
    f"--name=DuckTrack",
    f"--icon={icon_file}",
]

# Add macOS specific options
if system() == "Darwin":
    pyinstaller_cmd.extend([
        "--osx-bundle-identifier=com.duckai.ducktrack"
    ])

# Add the main script
pyinstaller_cmd.append(str(main_py))

print(f"Running PyInstaller command: {' '.join(pyinstaller_cmd)}")

try:
    run(pyinstaller_cmd, check=True)
    print("Build successful! Application bundle created in 'dist' directory.")

    # Create DMG only on macOS
    if system() == "Darwin":
        dist_path = project_dir / "dist"
        if not create_dmg(dist_path, app_name):
            print("DMG creation failed.")
            sys.exit(1)
        else:
            print(f"DMG file created at: {dist_path / f'{app_name}.dmg'}")

except CalledProcessError as e:
    print(f"An error occurred while running PyInstaller: {e}")
    sys.exit(1)
except FileNotFoundError:
    print("Error: 'pyinstaller' command not found. Make sure PyInstaller is installed and in your PATH.")
    sys.exit(1)