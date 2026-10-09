"""Start TradeLab Pro's MCP server, for Claude Desktop or Claude Code.

    python C:\path\to\TradeLabPro\tradelab_mcp.py

An MCP client launches its servers from a working directory of its own
choosing, so this adds its own folder to the import path first.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tradelab.mcp_server.server import main  # noqa: E402

if __name__ == "__main__":
    main()
