"""
dashboard/serve.py
Lightweight HTTP server for the Retail Margin & Inventory Leakage Web Dashboard.
Usage:
    python dashboard/serve.py [--port 8080]
"""

import sys
import os
import argparse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

class DashboardRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        dashboard_dir = Path(__file__).resolve().parent
        super().__init__(*args, directory=str(dashboard_dir), **kwargs)

    def end_headers(self):
        # Enable CORS and disable cache during development
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

def run_server(port=8080):
    server_address = ("", port)
    try:
        httpd = HTTPServer(server_address, DashboardRequestHandler)
        print(f"============================================================")
        print(f"  RETAIL OPERATIONAL ANALYTICS WEB DASHBOARD")
        print(f"  Live at: http://localhost:{port}")
        print(f"  Serving directory: {Path(__file__).resolve().parent}")
        print(f"============================================================")
        httpd.serve_forever()
    except OSError as e:
        if port < 8090:
            print(f"Port {port} in use, trying {port + 1}...")
            run_server(port + 1)
        else:
            raise e

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serve the Retail Analytics Dashboard")
    parser.add_argument("--port", type=int, default=8080, help="Port to serve on (default: 8080)")
    args = parser.parse_args()
    run_server(args.port)
