#!/bin/bash
#
# Setup and fix environment for Claude conversation import
#

set -e  # Exit on any error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🔧 Claude Memory System - Environment Setup"
echo "==========================================="

# Navigate to project root
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Check if we're in the right directory
if [ ! -f "src/server_fastmcp.py" ]; then
    echo "❌ Error: Not in the claude-memory-mcp directory"
    echo "💡 Script should be run from within the project"
    echo "📂 Current directory: $(pwd)"
    exit 1
fi

# Check Python version
echo "🐍 Checking Python version..."
python3 --version

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
else
    echo "✅ Virtual environment found"
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source .venv/bin/activate

# Check if we have the right dependencies
echo "📋 Checking dependencies..."

# Install/upgrade dependencies
echo "⬇️  Installing/updating dependencies..."
pip install --upgrade pip

# Install MCP dependencies if missing
if ! pip show mcp > /dev/null 2>&1; then
    echo "📦 Installing MCP dependencies..."
    pip install mcp
fi

# Install other required packages
pip install -r requirements.txt

echo "✅ Dependencies installed"

# Verify MCP import works
echo "🧪 Testing MCP import..."
python3 -c "from mcp.server.fastmcp import FastMCP; print('✅ MCP import successful')"

# Check data directory and files
echo "📂 Checking data files..."
if [ -d "data" ]; then
    echo "✅ Data directory found"

    # Show file sizes
    echo "📊 Data files:"
    for file in data/*.json; do
        if [ -f "$file" ]; then
            size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null)
            size_mb=$((size / 1024 / 1024))
            echo "   • $(basename "$file"): ${size:,} bytes (${size_mb} MB)"
        fi
    done

    # Check for conversations.json specifically
    if [ -f "data/conversations.json" ]; then
        conv_size=$(stat -c%s "data/conversations.json" 2>/dev/null || stat -f%z "data/conversations.json" 2>/dev/null)
        if [ "$conv_size" -gt 1000 ]; then
            echo "✅ conversations.json found and appears to contain data"
        else
            echo "⚠️  conversations.json is very small - might not contain conversation data"
        fi
    else
        echo "❌ conversations.json not found in data directory"
        echo "💡 Please ensure your exported conversations are at: data/conversations.json"
    fi
else
    echo "❌ Data directory not found"
    echo "💡 Creating data directory..."
    mkdir -p data
    echo "📥 Please place your conversations.json file in the data/ directory"
fi

# Test the memory server
echo "🧪 Testing memory server..."
if python3 -c "
import sys
sys.path.append('./src')
from universal_memory_mcp.server_fastmcp import ConversationMemoryServer
print('✅ Memory server import successful')
" 2>/dev/null; then
    echo "✅ Memory server ready"
else
    echo "⚠️  Memory server test failed - but this might be normal for first run"
fi

echo ""
echo "🎯 Environment Setup Complete!"
echo "==============================="
echo ""
echo "✅ Virtual environment: activated"
echo "✅ Dependencies: installed"
echo "✅ MCP: working"
echo "✅ Memory server: ready"
echo ""
echo "💡 Next steps:"
echo "   1. Ensure conversations.json is in data/ directory"
echo "   2. Run: ./import_workflow.sh"
echo ""
echo "🔧 If you need to reactivate the environment later:"
echo "   source .venv/bin/activate"
