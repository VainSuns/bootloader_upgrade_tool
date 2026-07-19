"""Process-wide pytest configuration for deterministic headless Qt tests."""

from __future__ import annotations

import os


# This must execute before pytest imports any test module that can create
# QApplication. Once QApplication exists, the Qt platform plugin cannot be
# changed for that process.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
