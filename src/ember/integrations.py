"""Load explicitly registered local integrations; no discovery or remote loading."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from .deployment import current_deployment

PRIVATE_RUNTIME_MODULES = frozenset({'gstudio_system_sync', 'install_gstudio_sync',
                                    'install_gstudio_mount', 'install_gstudio_webdav',
                                    'gstudio_workspace_layout'})


class IntegrationError(RuntimeError):
    pass


def load_runtime_extension(name: str):
    if name not in PRIVATE_RUNTIME_MODULES:
        raise IntegrationError('Unsupported local integration.')
    root = current_deployment().runtime_root.resolve()
    try:
        manifest_path = root / 'integrations/manifest.json'
        if manifest_path.is_symlink():
            raise IntegrationError('Integration manifest must be a local regular file.')
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('schema_version') != 1:
            raise IntegrationError('Unsupported integration manifest schema.')
        entry = manifest['modules'][name]
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise IntegrationError('Integration path must be relative to the deployment.')
        path = (root / relative).resolve(strict=True)
        if root not in path.parents or path.suffix != '.py' or not path.is_file():
            raise IntegrationError('Integration escapes the deployment.')
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise IntegrationError('Local integration checksum changed; revalidate its deployment manifest.')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise IntegrationError(f'Local integration {name} is not configured; it is not part of the open-source package.') from exc
    fullname = 'ember.runtime.' + name
    previous = sys.modules.get(fullname)
    spec = importlib.util.spec_from_file_location(fullname, path)
    if spec is None or spec.loader is None:
        raise IntegrationError('Cannot load registered integration.')
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if previous is not None:
            sys.modules[fullname] = previous
        else:
            sys.modules.pop(fullname, None)
        raise
    return module


def registered_source_paths() -> tuple[Path, ...]:
    """Health fingerprints include private code without redistributing its contents."""
    root = current_deployment().runtime_root.resolve()
    manifest = root / 'integrations/manifest.json'
    if not manifest.exists():
        return ()
    if manifest.is_symlink():
        raise IntegrationError('Integration manifest must be a local file.')
    try:
        data = json.loads(manifest.read_text())
        if data.get('schema_version') != 1 or not isinstance(data.get('modules'), dict):
            raise IntegrationError('Invalid integration manifest.')
        paths = [manifest]
        for name, item in data['modules'].items():
            if name not in PRIVATE_RUNTIME_MODULES:
                raise IntegrationError('Unknown private module.')
            path = (root / item['path']).resolve(strict=True)
            if root not in path.parents or path.suffix != '.py':
                raise IntegrationError('Private source escapes its deployment.')
            paths.append(path)
        return tuple(paths)
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise IntegrationError('Cannot fingerprint registered local sources.') from exc
