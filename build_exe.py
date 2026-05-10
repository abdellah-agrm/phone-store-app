#!/usr/bin/env python3
"""
Build script for Phone Shop Management System
This script properly packages the application with PyInstaller
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

def clean_build_dirs():
    """Clean previous build directories"""
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"Cleaned {dir_name} directory")

def create_fresh_database():
    """Deprecated safety no-op. Runtime data lives in %APPDATA%/PhoneShopManager.

    Do not delete local database files during build; a developer might keep a
    real backup/test database beside the project.
    """
    print("Keeping existing database files; build does not delete user data.")

def create_fresh_barcode_folder():
    """Ensure the local barcode folder exists without deleting its contents."""
    barcode_dir = 'codes_barres'
    os.makedirs(barcode_dir, exist_ok=True)
    print(f"Ensured {barcode_dir} directory exists")

def build_executable():
    """Build the executable with PyInstaller"""
    
    # PyInstaller command with proper options
    cmd = [
        'pyinstaller',
        '--onefile',
        '--noconsole',
        '--icon=main.ico',
        '--name=main',
        '--add-data=main.ico;.',  # Include icon in the bundle
        '--hidden-import=PIL._tkinter_finder',
        '--hidden-import=sqlite3',
        '--hidden-import=_sqlite3',
        '--hidden-import=ttkbootstrap',
        '--hidden-import=barcode',
        '--hidden-import=barcode.writer',
        '--hidden-import=reportlab',
        '--hidden-import=pandas',
        '--hidden-import=tempfile',
        '--collect-all=ttkbootstrap',
        '--collect-all=barcode',
        'main.py'
    ]
    
    print("Building executable...")
    print(" ".join(cmd))
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✅ Build successful!")
        return True
    else:
        print("❌ Build failed!")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        return False

def post_build_setup():
    """Setup post-build files and folders"""
    dist_dir = Path('dist')
    
    if not dist_dir.exists():
        print("❌ Dist directory not found!")
        return
    
    # Copy icon to dist folder
    if os.path.exists('main.ico'):
        shutil.copy2('main.ico', dist_dir / 'main.ico')
        print("📁 Copied main.ico to dist folder")
    
    # Create codes_barres folder in dist
    barcode_dist_dir = dist_dir / 'codes_barres'
    barcode_dist_dir.mkdir(exist_ok=True)
    print("📁 Created codes_barres folder in dist")
    
    print(f"📦 Executable ready at: {dist_dir / 'main.exe'}")

def main():
    """Main build process"""
    print("🚀 Starting build process for Phone Shop Manager...")
    
    # Step 1: Clean previous builds
    clean_build_dirs()
    
    # Step 2: Never delete database/barcode data during build
    create_fresh_database()
    create_fresh_barcode_folder()
    
    # Step 4: Build executable
    if not build_executable():
        sys.exit(1)
    
    # Step 5: Post-build setup
    post_build_setup()
    
    print("\n✅ Build process completed successfully!")
    print("📋 Next steps:")
    print("   1. Navigate to the 'dist' folder")
    print("   2. Run 'main.exe'")
    print("   3. Login with admin/admin123 or vendeur/vendeur123")

if __name__ == "__main__":
    main()
