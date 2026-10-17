"""Prepare, verify and atomically select a packaged runtime; never start a service."""
from __future__ import annotations
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from .deployment import Deployment, DeploymentError


class UpdateError(RuntimeError):
    pass


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise UpdateError('Release state must be a regular file.')
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise UpdateError('Unreadable release state; refusing fallback.') from exc
    if not isinstance(value, dict):
        raise UpdateError('Invalid release state.')
    return value


def _atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if resolved == root.resolve() or root.resolve() not in resolved.parents:
        raise UpdateError('Release path escapes its registered directory.')
    return resolved


@contextmanager
def _lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(root / 'release.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _run(args: list[str], *, env: dict | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd='/', env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Avoid writing client environment or dependency server URLs into ordinary logs.
        raise UpdateError(f'Runtime command failed with exit code {result.returncode}: {Path(args[0]).name}')
    return result


def _verify_bindings(python: Path, deployment: Deployment) -> None:
    code = ("import json,os; from pathlib import Path; "
            "from ember.runtime.workspace_paths import shared_workspace_root,task_inputs_root,archive_inbox_root,project_archive_root; "
            "d=json.loads(Path(os.environ['EMBER_DEPLOYMENT_PROFILE']).read_text()); "
            "assert shared_workspace_root().resolve()==Path(d['shared_root']).resolve(); "
            "assert task_inputs_root().resolve()==Path(d['shared_root']).resolve()/'任务资料'; "
            "assert archive_inbox_root().resolve()==Path(d['inbox_root']).resolve(); "
            "assert project_archive_root().resolve()==Path(d['archive_root']).resolve()")
    env = dict(os.environ, EMBER_DEPLOYMENT_PROFILE=str(deployment.profile))
    env.pop('PYTHONPATH', None)
    _run([str(python), '-I', '-c', code], env=env)


def prepare(wheel: Path, deployment: Deployment, *, expected_sha256: str,
            revision: str, wheelhouse: Path | None = None) -> dict:
    if not isinstance(revision, str) or not revision or len(revision) > 160:
        raise UpdateError('A bounded source revision is required.')
    wheel = wheel.resolve(strict=True)
    actual = digest(wheel)
    if not expected_sha256 or actual != expected_sha256:
        raise UpdateError('Wheel checksum does not match the selected build.')
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if not any(name.startswith('ember/') for name in names):
            raise UpdateError('Wheel does not contain the Ember package.')
        for name in names:
            member = Path(name)
            if member.is_absolute() or '..' in member.parts or not (name.startswith('ember/') or '.dist-info/' in name):
                raise UpdateError('Unexpected wheel member.')
    root = deployment.local_config_root / 'releases'
    directory = root / (actual + '-' + hashlib.sha256(revision.encode()).hexdigest()[:12])
    python = directory / 'venv/bin/python'
    receipt = directory / 'prepared.json'
    with _lock(deployment.local_config_root):
        previous = _read(receipt)
        if previous and previous.get('wheel_sha256') == actual and previous.get('source_revision') == revision and python.is_file():
            _validate_release(previous, deployment)
            _verify_bindings(python, deployment)
            return previous
        if directory.exists():
            raise UpdateError('Incomplete or conflicting prepared release; preserve it for diagnosis.')
        directory.mkdir(parents=True)
        try:
            _run([sys.executable, '-m', 'venv', str(directory / 'venv')])
            args = [str(python), '-m', 'pip', 'install', '--disable-pip-version-check']
            if wheelhouse is not None:
                args += ['--no-index', '--find-links', str(wheelhouse.resolve(strict=True))]
            args += [str(wheel) + '[full]']
            _run(args)
            env = dict(os.environ, EMBER_DEPLOYMENT_PROFILE=str(deployment.profile))
            env.pop('PYTHONPATH', None)
            result = _run([str(python), '-I', '-m', 'ember', '--deployment-profile', str(deployment.profile), 'check'], env=env)
            check = json.loads(result.stdout)
            _verify_bindings(python, deployment)
            if check.get('status') != 'ready':
                raise UpdateError('Prepared runtime is not ready.')
            manifest_result = _run([str(python), '-I', '-c',
                "import hashlib,importlib.metadata,json; d=importlib.metadata.distribution('ember'); "
                "print(json.dumps({str(d.locate_file(f)):hashlib.sha256(d.locate_file(f).read_bytes()).hexdigest() for f in d.files if f.hash is not None}))"])
            installed_files = {str(_inside(Path(name), directory).relative_to(directory)): checksum
                               for name, checksum in json.loads(manifest_result.stdout).items()}
            value = {'installed_files': installed_files, 'schema_version': 1, 'python': str(python), 'directory': str(directory),
                     'wheel_sha256': actual, 'source_revision': revision, 'check': check,
                     'profile': str(deployment.profile)}
            _atomic(receipt, value)
            return value
        except Exception:
            # No active pointer was changed. Failed files remain outside the working runtime.
            raise


def _validate_release(value: dict, deployment: Deployment) -> dict:
    if value.get('profile') != str(deployment.profile):
        raise UpdateError('Prepared release belongs to another deployment.')
    root = deployment.local_config_root / 'releases'
    directory = _inside(Path(str(value.get('directory', ''))), root)
    # venv interpreters are valid symlinks to the base interpreter; validate their directory lexically.
    python = Path(str(value.get('python', '')))
    if python != directory / 'venv/bin/python' or not python.is_file():
        raise UpdateError('Prepared interpreter is missing or outside its release.')
    receipt = _read(directory / 'prepared.json')
    if receipt != value or not value.get('wheel_sha256') or not value.get('source_revision'):
        raise UpdateError('Prepared release receipt does not match.')
    files = value.get('installed_files')
    if not isinstance(files, dict) or not files:
        raise UpdateError('Prepared runtime integrity manifest is missing.')
    for relative, checksum in files.items():
        file = _inside(directory / relative, directory)
        if not file.is_file() or digest(file) != checksum:
            raise UpdateError('Prepared runtime files changed; refusing activation or startup.')
    return value


def active(deployment: Deployment) -> dict | None:
    pointer = _read(deployment.local_config_root / 'active-release.json')
    if pointer is None:
        return None
    if pointer.get('schema_version') != 1 or not isinstance(pointer.get('revision'), int):
        raise UpdateError('Invalid active release pointer; refusing fallback.')
    _validate_release(pointer.get('active', {}), deployment)
    return pointer


def activate(prepared: dict, deployment: Deployment, *, expected_revision: int) -> dict:
    with _lock(deployment.local_config_root):
        _validate_release(prepared, deployment)
        prior = active(deployment)
        revision = prior['revision'] if prior else 0
        if revision != expected_revision:
            raise UpdateError('Active release changed; reload before selecting a build.')
        if prior and prior['active'] == prepared:
            return prior
        result = {'schema_version': 1, 'revision': revision + 1, 'active': prepared,
                  'previous': prior['active'] if prior else None}
        _atomic(deployment.local_config_root / 'active-release.json', result)
        return result


def rollback(deployment: Deployment, *, expected_revision: int) -> dict:
    with _lock(deployment.local_config_root):
        prior = active(deployment)
        if not prior or prior['revision'] != expected_revision or not prior.get('previous'):
            raise UpdateError('No matching previous release for rollback.')
        _validate_release(prior['previous'], deployment)
        result = {'schema_version': 1, 'revision': prior['revision'] + 1,
                  'active': prior['previous'], 'previous': prior['active']}
        _atomic(deployment.local_config_root / 'active-release.json', result)
        return result


def restore_selection(previous: dict | None, deployment: Deployment, *, expected_revision: int) -> None:
    """Undo a failed activation without rewriting user data or prepared files."""
    with _lock(deployment.local_config_root):
        current = active(deployment)
        if not current or current['revision'] != expected_revision:
            raise UpdateError('Release changed while recovering; manual review required.')
        path = deployment.local_config_root / 'active-release.json'
        if previous is None:
            path.replace(path.with_name(f'failed-first-activation-{expected_revision}.json'))
        else:
            _validate_release(previous['active'], deployment)
            _atomic(path, {'schema_version': 1, 'revision': expected_revision + 1,
                           'active': previous['active'], 'previous': current['active']})


def build_wheel(repository: Path, output: Path, *, wheelhouse: Path | None = None) -> Path:
    repository = repository.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, '-m', 'pip', 'wheel', str(repository), '--no-deps', '--wheel-dir', str(output)]
    if wheelhouse is not None:
        args += ['--no-index', '--find-links', str(wheelhouse.resolve(strict=True))]
    result = subprocess.run(args, cwd=repository, capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise UpdateError('Received package build failed; active runtime was not changed.')
    wheels = list(output.glob('ember-*.whl'))
    if len(wheels) != 1:
        raise UpdateError('A received revision must produce exactly one Ember wheel.')
    return wheels[0]
