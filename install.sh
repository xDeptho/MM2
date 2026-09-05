#!/data/data/com.termux/files/usr/bin/bash
# AJ V2 installer - Termux
# Installs dependencies, downloads ajv2.py (nub.py) from the repo, and wires up
# an `ajv2` command so the manager can be launched from anywhere.
set -e

REPO_RAW="https://raw.githubusercontent.com/xDeptho/MM2/main"
INSTALL_DIR="$HOME/ajv2"
BIN_DIR="$PREFIX/bin"

echo "==> Updating packages..."
pkg upgrade -y >/dev/null
pkg install -y python git >/dev/null

echo "==> Installing Python packages..."
# purge the pip build cache first - a stale cache from a previous Python
# version (e.g. after Termux upgrades Python) can reference a python binary
# that no longer exists and break every build
pip cache purge >/dev/null 2>&1 || true
pip install --no-cache-dir requests pyfiglet colorama prettytable bypasstools discord.py

echo "==> Downloading ajv2.py..."
mkdir -p "$INSTALL_DIR"
curl -fsSL "$REPO_RAW/ajv2.py" -o "$INSTALL_DIR/ajv2.py"

echo "==> Installing the 'ajv2' command..."
cat > "$BIN_DIR/ajv2" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
cd "$INSTALL_DIR" && exec python ajv2.py "\$@"
EOF
chmod +x "$BIN_DIR/ajv2"

echo
echo "Done. Run it with:  ajv2"
echo "Installed at: $INSTALL_DIR/ajv2.py"
