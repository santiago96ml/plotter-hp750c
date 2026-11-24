"""Entry point used by OpenCode's MCP client."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from plotter.mcp_server import main

if __name__ == "__main__":
    main()
