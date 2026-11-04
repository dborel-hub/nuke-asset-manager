"""
Logging for Asset Manager.

Quiet by default: only warnings and errors reach Nuke's Script Editor.
For troubleshooting, set the environment variable ASSET_MANAGER_DEBUG=1
before launching Nuke to see everything.
"""

import os
import sys
import logging

log = logging.getLogger("AssetManager")

if not log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("[Asset Manager] %(message)s"))
    log.addHandler(_handler)
    log.propagate = False

log.setLevel(logging.DEBUG if os.environ.get("ASSET_MANAGER_DEBUG") else logging.WARNING)
