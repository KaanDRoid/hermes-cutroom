"""Workspace locations owned by Cutroom."""

import os
from pathlib import Path


def studio_root():
    """Studio workspace: ``CUTROOM_WORKSPACE`` or Hermes' plugin data directory."""
    root = os.environ.get("CUTROOM_WORKSPACE")
    if root is None:
        try:
            from plugins.plugin_storage import plugin_data_dir

            root = plugin_data_dir("cutroom") / "studio"
        except ImportError:
            root = Path(__file__).resolve().parents[1] / "artifacts" / "studio"
    return Path(root).expanduser().resolve()


def plans_root():
    """Directory that holds plans created by the legacy draft/review/render tools."""
    return studio_root() / "plans"


def inside(path, root):
    """Resolve ``path`` (following links) and require it to stay under ``root``."""
    root = Path(root).resolve()
    resolved = Path(path).expanduser().resolve()
    if resolved != root and root not in resolved.parents:
        raise PermissionError(f"Path is outside the Cutroom workspace: {root}")
    return resolved
