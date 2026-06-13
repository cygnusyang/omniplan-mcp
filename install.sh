#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────
# omniplan-mcp  —  One-click Installer
# ──────────────────────────────────────────────────────────
# This script checks prerequisites and guides you through
# setting up the OmniPlan MCP server.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/cygnusyang/omniplan-mcp/main/install.sh | bash
#   # or
#   ./install.sh
# ──────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { printf "${BLUE}ℹ${NC} %s\n" "$*"; }
ok()    { printf "${GREEN}✓${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}⚠${NC} %s\n" "$*"; }
err()   { printf "${RED}✗${NC} %s\n" "$*"; }

echo ""
echo "╔═══════════════════════════════════════════╗"
echo "║     omniplan-mcp — Installer              ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# ── Step 1: OS check ────────────────────────────────────
info "Checking operating system..."
if [[ "$(uname)" != "Darwin" ]]; then
    err "omniplan-mcp requires macOS (for OmniPlan AppleScript bridge)."
    err "Detected: $(uname)"
    exit 1
fi
ok "macOS detected: $(sw_vers -productVersion 2>/dev/null || echo 'unknown')"

# ── Step 2: Python check ────────────────────────────────
info "Checking Python..."
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        major=${ver%.*}
        minor=${ver#*.}
        if [[ "$major" -ge 3 && "$minor" -ge 10 ]]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    err "Python 3.10+ is required but not found."
    err "Install it from https://www.python.org/downloads/ or via Homebrew:"
    err "  brew install python@3.12"
    exit 1
fi
ok "$($PYTHON --version) found at $(command -v "$PYTHON")"

# ── Step 3: uv check / install ──────────────────────────
info "Checking uv (Python package installer)..."
if command -v uv &>/dev/null; then
    ok "uv $($PYTHON -m uv --version 2>/dev/null || uv --version 2>/dev/null || echo 'installed')"
else
    warn "uv is not installed. Installing now..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Source it for the current shell
    if [[ -f "$HOME/.cargo/env" ]]; then
        source "$HOME/.cargo/env"
    fi
    if command -v uv &>/dev/null; then
        ok "uv installed successfully"
    else
        warn "uv installer finished but 'uv' command not found in PATH."
        warn "You may need to restart your terminal or add ~/.cargo/bin to PATH."
        warn "Continuing with pip fallback..."
    fi
fi

# ── Step 4: OmniPlan check (optional) ──────────────────
info "Checking OmniPlan..."
if [ -d "/Applications/OmniPlan.app" ] || [ -d "$HOME/Applications/OmniPlan.app" ]; then
    ok "OmniPlan is installed"
else
    warn "OmniPlan not found. .mpp files require OmniPlan."
    warn "Install it via: brew install --cask omniplan"
    warn "(.oplx files can be read without OmniPlan.)"
fi

# ── Step 5: Clone or update project ────────────────────
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/omniplan-mcp}"

if [[ -d "$INSTALL_DIR" ]]; then
    info "Project already exists at $INSTALL_DIR"
    info "Updating..."
    cd "$INSTALL_DIR"
    git pull --ff-only 2>/dev/null || warn "Could not git pull (you may need to update manually)"
else
    info "Cloning project to $INSTALL_DIR..."
    git clone https://github.com/cygnusyang/omniplan-mcp.git "$INSTALL_DIR" 2>/dev/null || {
        err "Failed to clone repository."
        err "Check your internet connection or clone manually:"
        err "  git clone https://github.com/cygnusyang/omniplan-mcp.git"
        exit 1
    }
    ok "Project cloned successfully"
fi

cd "$INSTALL_DIR"

# ── Step 6: Install dependencies ────────────────────────
info "Installing Python dependencies..."
if command -v uv &>/dev/null; then
    $PYTHON -m uv sync 2>/dev/null || $PYTHON -m pip install -e . 2>/dev/null || {
        warn "uv sync failed, falling back to pip..."
        $PYTHON -m pip install -e .
    }
else
    $PYTHON -m pip install -e .
fi
ok "Dependencies installed"

# ── Step 7: Verify ──────────────────────────────────────
info "Verifying installation..."
if $PYTHON -c "from omniplan_mcp import __version__; print(__version__)" 2>/dev/null; then
    ok "omniplan-mcp is ready!"
else
    err "Verification failed. Try running:"
    err "  cd $INSTALL_DIR && $PYTHON -m pip install -e ."
    exit 1
fi

# ── Step 8: Claude Desktop config guidance ──────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Next Steps                                                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Add this to your Claude Code settings.json (~/.claude/settings.json):"
echo ""
echo "  {"
echo "    \"mcpServers\": {"
echo "      \"omniplan\": {"
echo "        \"command\": \"uv\","
echo "        \"args\": ["
echo "          \"run\","
echo "          \"--directory\", \"$INSTALL_DIR\","
echo "          \"omniplan-mcp\""
echo "        ],"
echo "        \"env\": {}"
echo "      }"
echo "    }"
echo "  }"
echo ""
echo "Or if you prefer pip (after publishing to PyPI):"
echo ""
echo "  {"
echo "    \"mcpServers\": {"
echo "      \"omniplan\": {"
echo "        \"command\": \"uvx\","
echo "        \"args\": [\"omniplan-mcp\"],"
echo "        \"env\": {}"
echo "      }"
echo "    }"
echo "  }"
echo ""
echo "Then restart Claude Code. The tools will be available automatically."
echo ""
echo "For VS Code users, add to your .vscode/mcp.json:"
echo ""
echo "  {"
echo "    \"servers\": {"
echo "      \"omniplan\": {"
echo "        \"command\": \"uv\","
echo "        \"args\": [\"run\", \"--directory\", \"$INSTALL_DIR\", \"omniplan-mcp\"],"
echo "        \"type\": \"stdio\""
echo "      }"
echo "    }"
echo "  }"
echo ""
echo "🚀 Installation complete!"
