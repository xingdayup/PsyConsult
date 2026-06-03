"""
Pytest conftest.py - placed at the agent/ root so that:
1. pytest adds this directory to sys.path automatically
2. IDEs (PyCharm, VSCode) recognize agent/ as the source root
3. All absolute imports like `from core.graph import ...` resolve correctly
"""
import sys
from pathlib import Path

# Ensure agent/ is always on sys.path regardless of how the test is invoked
_root = str(Path(__file__).parent)
if _root not in sys.path:
    sys.path.insert(0, _root)
