"""Package-aware subprocess entry points shared by services and integrations."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys


def module_command(module: str, *arguments: str, python: str | Path | None = None) -> list[str]:
    if not module.startswith('ember.') or any(not part.isidentifier() for part in module.split('.')):
        raise ValueError('Only Ember package modules can be launched.')
    return [str(python or sys.executable), '-m', module, *arguments]


def installed_package(python: str | Path) -> bool:
    """Probe installation without PYTHONPATH or the working checkout masking it."""
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    try:
        result = subprocess.run([str(python), '-I', '-c', 'import ember.application, ember.runtime; print(ember.__version__)'],
                                env=env, cwd='/', capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
