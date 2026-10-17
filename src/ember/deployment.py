"""Explicit deployment locations for the full application; no host-specific defaults.

The portable workspace CLI does not load a deployment profile. Full capabilities
require an explicit profile; importing a module never discovers production data.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import os
from pathlib import Path


class DeploymentError(ValueError):
    pass


@dataclass(frozen=True)
class Deployment:
    profile: Path
    environment: str
    runtime_root: Path
    shared_root: Path
    inbox_root: Path
    archive_root: Path
    local_config_root: Path
    repository_root: Path
    isolation_root: Path | None = None

    @classmethod
    def load(cls, filename: str | Path) -> 'Deployment':
        try:
            profile = Path(filename).expanduser().resolve(strict=True)
            data = json.loads(profile.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise DeploymentError('Deployment profile is unreadable; refusing fallback.') from exc
        if not isinstance(data, dict) or data.get('schema_version') != 1:
            raise DeploymentError('Unsupported deployment profile schema.')
        environment = data.get('environment')
        if not isinstance(environment, str) or not environment.strip():
            raise DeploymentError('Deployment environment is required.')
        values = {}
        for key in ('runtime_root', 'shared_root', 'inbox_root', 'archive_root', 'local_config_root', 'repository_root'):
            value = data.get(key)
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise DeploymentError(f'{key} must be an explicit absolute path.')
            values[key] = Path(value).resolve()
        isolation = data.get('isolation_root')
        if isolation is not None and (not isinstance(isolation, str) or not Path(isolation).is_absolute()):
            raise DeploymentError('isolation_root must be an explicit absolute path.')
        try:
            boundary = Path(isolation).resolve(strict=True) if isolation else None
        except OSError as exc:
            raise DeploymentError('Isolation boundary is unavailable.') from exc
        if boundary is not None:
            for key, value in values.items():
                if value != boundary and boundary not in value.parents:
                    raise DeploymentError(f'{key} escapes the isolated deployment.')
        roots = [values[k] for k in ('runtime_root', 'shared_root', 'inbox_root', 'archive_root', 'local_config_root')]
        for i, left in enumerate(roots):
            for right in roots[i + 1:]:
                if left == right or left in right.parents or right in left.parents:
                    raise DeploymentError('Deployment data, runtime, Inbox, archive and configuration roots must be separate.')
        return cls(profile=profile, environment=environment, isolation_root=boundary, **values)


@lru_cache(maxsize=1)
def current_deployment() -> Deployment:
    filename = os.environ.get('EMBER_DEPLOYMENT_PROFILE')
    if not filename:
        raise DeploymentError('Full capabilities require EMBER_DEPLOYMENT_PROFILE; no production root is inferred.')
    return Deployment.load(filename)


def runtime_root() -> Path:
    return current_deployment().runtime_root


def require_host_changes() -> None:
    """Isolated validation never installs, replaces or restarts host services."""
    if current_deployment().isolation_root is not None:
        raise DeploymentError('Host service/client changes are disabled for an isolated deployment.')
