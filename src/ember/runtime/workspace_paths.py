#!/usr/bin/env python3
from __future__ import annotations
from ..deployment import current_deployment
from ..deployment import runtime_root as _deployment_root

import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = _deployment_root()
CONFIG_PATH = ROOT / "config" / "workspace-environments.json"
_TEST_SANDBOX: Path | None = None


def _config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _test_sandbox(name: str) -> Path | None:
    """Unit tests never reach a real shared root unless a test names one explicitly."""
    if "unittest" not in sys.modules or os.environ.get("GSTUDIO_ALLOW_REAL_ROOTS_IN_TESTS") == "1":
        return None
    global _TEST_SANDBOX
    if _TEST_SANDBOX is None:
        _TEST_SANDBOX = Path(tempfile.mkdtemp(prefix="gstudio-test-roots-")).resolve()
        atexit.register(shutil.rmtree, _TEST_SANDBOX, ignore_errors=True)
    path = _TEST_SANDBOX / name
    path.mkdir(exist_ok=True)
    return path


def current_environment_name() -> str:
    return os.environ.get("GSTUDIO_ENVIRONMENT") or current_deployment().environment


def current_environment() -> dict:
    environments = _config().get("environments", {})
    name = current_environment_name()
    if name in environments:
        return environments[name]

    raise RuntimeError(
        f"Unregistered GStudio environment: {name!r} (home={Path.home()})"
    )


def shared_workspace_root() -> Path:
    """Return the writable primary root; never silently fall back for writes."""
    configured = os.environ.get("GSTUDIO_SHARED_WORKSPACE_ROOT")
    if configured:
        return Path(configured).expanduser()
    return _test_sandbox("shared") or current_deployment().shared_root


def readable_shared_workspace_root() -> Path:
    """Return the registered shared root; GStudio has no secondary fallback."""
    return shared_workspace_root()


def shared_workspace_status() -> dict[str, object]:
    primary = shared_workspace_root()
    primary_available = primary.is_dir()
    return {
        "primary": str(primary),
        "primary_available": primary_available,
        "selected_for_writes": str(primary),
        "selected_for_reads": str(readable_shared_workspace_root()),
        "writes_fail_closed": not primary_available,
    }


def shared_task_root() -> Path:
    return shared_workspace_root() / "tasks"


def delivery_root() -> Path:
    return shared_workspace_root() / "交付"


def task_inputs_root() -> Path:
    configured = os.environ.get("GSTUDIO_TASK_INPUTS_ROOT")
    if configured:
        return Path(configured).expanduser()
    return _test_sandbox("task-inputs") or (shared_workspace_root() / "任务资料")


def task_input_snapshot_max_bytes() -> int:
    configured = os.environ.get("GSTUDIO_TASK_INPUT_SNAPSHOT_MAX_BYTES")
    if configured:
        try:
            value = int(configured)
        except ValueError as exc:
            raise ValueError("GSTUDIO_TASK_INPUT_SNAPSHOT_MAX_BYTES must be an integer") from exc
        if value <= 0:
            raise ValueError("GSTUDIO_TASK_INPUT_SNAPSHOT_MAX_BYTES must be positive")
        return value
    value = int(current_environment().get("task_input_snapshot_max_bytes") or 209_715_200)
    if value <= 0:
        raise ValueError("task_input_snapshot_max_bytes must be positive")
    return value


def workspace_inbox_root() -> Path:
    configured = os.environ.get("GSTUDIO_WORKSPACE_INBOX_ROOT")
    if configured:
        return Path(configured).expanduser()
    return _test_sandbox("workspace-inbox") or Path(current_environment()["workspace_inbox_root"])


def archive_inbox_root() -> Path:
    configured = os.environ.get("GSTUDIO_ARCHIVE_INBOX_ROOT")
    if configured:
        return Path(configured).expanduser()
    return _test_sandbox("archive-inbox") or current_deployment().inbox_root


def project_archive_root() -> Path:
    """Return the canonical NAS project archive; never fall back locally."""
    configured = os.environ.get("GSTUDIO_PROJECT_ARCHIVE_ROOT")
    if configured:
        return Path(configured).expanduser()
    return _test_sandbox("project-archive") or current_deployment().archive_root


def local_config_root() -> Path:
    configured = os.environ.get("GSTUDIO_LOCAL_CONFIG_ROOT")
    return Path(configured).expanduser() if configured else (_test_sandbox("local-config") or current_deployment().local_config_root)


def downloads_root() -> Path:
    configured = os.environ.get("GSTUDIO_DOWNLOADS_ROOT")
    if configured:
        return Path(configured).expanduser()
    return _test_sandbox("downloads") or Path(current_environment().get("downloads_root") or (Path.home() / "Downloads"))


def path_equivalence_pairs() -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for rule in _config().get("path_equivalence_rules", []):
        macbook = rule.get("macbook_pro")
        mini = rule.get("mac_mini")
        if macbook and mini:
            pairs.append((Path(macbook), Path(mini)))
    for rule in _config().get('path_aliases', []):
        if isinstance(rule, dict) and rule.get('from') and rule.get('to'):
            pairs.append((Path(rule['from']), Path(rule['to'])))
    return pairs


def equivalent_path_strings(path: Path) -> set[str]:
    boundary = getattr(current_deployment(), 'isolation_root', None)
    # Existing unit-test sandboxes supply their own temporary roots. Real
    # isolated deployments only resolve references within their explicit copy.
    isolated = boundary is not None and 'unittest' not in sys.modules
    lexical = Path(os.path.abspath(path.expanduser()))
    resolved = lexical if isolated and boundary not in lexical.parents else path.resolve()
    values = {str(resolved), str(path)}
    for left, right in path_equivalence_pairs():
        for source, target in ((left, right), (right, left)):
            try:
                values.add(str(target / resolved.relative_to(source)))
            except ValueError:
                pass
    if isolated:
        values = {value for value in values if Path(value) == boundary or boundary in Path(value).parents}
    return values
