"""
Root-level pytest configuration for Moat monorepo.

This file exists to establish proper pytest boundaries between the multiple
service test directories (packages/core/tests/, services/gateway/tests/, etc.)
and prevent namespace package conflicts during test collection.

Without this file, pytest may try to import 'tests.conftest' as a single
namespace package spanning multiple directories, causing ModuleNotFoundError.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure packages/core is importable
root = Path(__file__).parent
core_path = root / "packages" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))
