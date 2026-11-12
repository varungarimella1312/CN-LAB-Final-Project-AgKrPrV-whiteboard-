#!/usr/bin/env bash
# ==============================================================================
# Build script to generate standalone executables for macOS and Linux.
# Uses PyInstaller as a build-time packager.
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================================="
echo " Building LAN Collaborative Whiteboard Executables (Unix) "
echo "=========================================================="

# 1. Verify PyInstaller is installed
if ! command -v pyinstaller &> /dev/null; then
    echo "Error: PyInstaller command not found in PATH."
    echo "Install it using: pip install pyinstaller"
    exit 1
fi

# 2. Build Server Executable (CLI console application)
echo ""
echo "[1/3] Building whiteboard-server..."
pyinstaller --clean --noconfirm --onefile \
    --name whiteboard-server \
    whiteboard/server.py

# 3. Build Client Executable (Windowed GUI application)
echo ""
echo "[2/3] Building whiteboard-client..."
pyinstaller --clean --noconfirm --onefile --windowed \
    --name whiteboard-client \
    whiteboard/client.py

# 4. Copy distribution documentation
echo ""
echo "[3/3] Preparing dist folder..."
mkdir -p dist
if [ -f "dist/README.txt" ]; then
    echo "Distribution README present in dist/README.txt"
fi

echo ""
echo "=========================================================="
echo " Build Succeeded! Executables generated in dist/:"
echo "   - dist/whiteboard-server"
echo "   - dist/whiteboard-client"
echo "   - dist/README.txt"
echo "=========================================================="

