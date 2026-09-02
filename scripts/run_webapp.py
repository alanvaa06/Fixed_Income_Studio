#!/usr/bin/env python
"""
Launch the Fixed Income Studio web UI.

Usage
-----
    python scripts/run_webapp.py                      # http://127.0.0.1:5000
    python scripts/run_webapp.py --port 8080
    python scripts/run_webapp.py --host 0.0.0.0 --debug

Environment variables
---------------------
    FRED_API_KEY               Optional. With a key the Treasury, TIPS and fed
                               funds series come from the FRED API.
    NELSON_SIEGEL_PUBLIC_DATA  Default 1: without a key, read treasury.gov, FRED's
                               public CSV export and the Fed's GSW zero curve.
    NELSON_SIEGEL_OFFLINE      Set to 1 to disable all network access (synthetic data).
    NELSON_SIEGEL_CACHE_DIR    Where the GSW table is cached (default ~/.cache/nelson_siegel).
"""

import argparse
import os
import sys
import webbrowser
from pathlib import Path
from threading import Timer

# Make the local src/ importable when running from a checkout.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))

from nelson_siegel.webapp import create_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Nelson-Siegel Studio web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode with auto-reload")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab on startup")
    parser.add_argument(
        "--fred-key",
        default=os.environ.get("FRED_API_KEY"),
        help="FRED API key (defaults to FRED_API_KEY env var)",
    )
    args = parser.parse_args()

    app = create_app(fred_api_key=args.fred_key)

    url = f"http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}"
    print(f"\n  Nelson-Siegel Studio")
    print(f"  Serving at: {url}")
    print(f"  FRED key:   {'detected' if args.fred_key else 'not set (using synthetic data)'}\n")

    if not args.no_browser and not os.environ.get("WERKZEUG_RUN_MAIN"):
        Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
