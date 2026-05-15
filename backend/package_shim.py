"""Expose this directory as the `backend` package when Vercel uses backend/ as project root."""
import sys
import types
from pathlib import Path


def ensure_backend_package() -> None:
    try:
        import importlib.util

        spec = importlib.util.find_spec("backend")
        if spec is not None and spec.submodule_search_locations:
            return
    except (ImportError, AttributeError, ValueError):
        pass

    root = Path(__file__).resolve().parent
    if "backend" not in sys.modules:
        pkg = types.ModuleType("backend")
        pkg.__path__ = [str(root)]
        pkg.__package__ = "backend"
        sys.modules["backend"] = pkg
