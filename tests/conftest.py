"""Shared test configuration: never touch the network from the test-suite."""

import os

os.environ.setdefault("NELSON_SIEGEL_OFFLINE", "1")
# A developer's FRED key would bypass the offline switch (create_app reads it
# from the environment) and make the API tests hit live data.
os.environ.pop("FRED_API_KEY", None)
