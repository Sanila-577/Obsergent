"""Lets you run `python -m agenttrace ...` (the SDK starts the proxy this way)."""
import sys

from agenttrace.cli import main

sys.exit(main())
