#!/usr/bin/env python3
"""Wrapper to launch weibo-idol MCP server with correct working directory."""
import os
import sys
import subprocess

server_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp-server")
server_py = os.path.join(server_dir, "server.py")

os.chdir(server_dir)
os.execv(sys.executable, [sys.executable, server_py])
