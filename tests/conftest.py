"""Shared test configuration: never touch the network from the test-suite."""

import os

os.environ.setdefault("NELSON_SIEGEL_OFFLINE", "1")
