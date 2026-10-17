#!/usr/bin/env python3
from __future__ import annotations
import json
from ..deployment import runtime_root as _deployment_root

import os
from pathlib import Path

from .workspace_paths import project_archive_root as resolved_project_archive_root

# Baidu locators remain compatibility and backup-replica identifiers. New
# archive writes use the canonical NAS project archive returned by archive_root.
BYPY_REMOTE_ROOT = "100项目"
BYPY_ARCHIVE_URI_ROOT = "bypy:/100项目"
BYPY_DISPLAY_ROOT = "/apps/bypy/100项目"

# Retained only to interpret historical task cards created before 2026-07-14.
LEGACY_EVAN4T_ARCHIVE_ROOT = Path(os.environ.get("GSTUDIO_LEGACY_ARCHIVE_ROOT", "/nonexistent/legacy-archive"))

PROJECT_ARCHIVE_NAMES = json.loads((_deployment_root() / "config" / "archive-names.json").read_text())


def archive_root() -> Path:
    """Return the canonical NAS project archive root."""
    configured = os.environ.get("GSTUDIO_ARCHIVE_ROOT")
    if configured:
        return Path(configured).expanduser()

    return resolved_project_archive_root()


def remote_archive_path(*parts: str) -> str:
    """Build a bypy CLI-relative path below the configured app directory."""
    clean = [str(part).strip("/") for part in parts if str(part).strip("/")]
    return "/".join((BYPY_REMOTE_ROOT, *clean))


def archive_uri(*parts: str) -> str:
    """Build the canonical mounted NAS locator for a new archive target."""
    clean = [str(part).strip("/") for part in parts if str(part).strip("/")]
    return str(archive_root().joinpath(*clean))


def project_archive_remote_path(project: str) -> str:
    return remote_archive_path(PROJECT_ARCHIVE_NAMES[project])


def project_archive_uri(project: str) -> str:
    return archive_uri(PROJECT_ARCHIVE_NAMES[project])


def project_archive_root(project: str) -> Path:
    return archive_root() / PROJECT_ARCHIVE_NAMES[project]


def project_archive_roots() -> dict[str, Path]:
    return {
        project: project_archive_root(project)
        for project in PROJECT_ARCHIVE_NAMES
    }


def map_archive_path(path: Path) -> Path:
    """Map a legacy Evan4T path to the local index for read-only inspection."""
    root = archive_root()
    try:
        return root / path.relative_to(LEGACY_EVAN4T_ARCHIVE_ROOT)
    except ValueError:
        return path
