"""Thin legacy CLI entries execute the one selected installed Ember package."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
from .application import Application, RUNTIME_TOOLS
from .package_update import active
from .process import module_command


def command(profile: str | Path, tool: str, arguments: list[str]) -> list[str]:
    if tool not in RUNTIME_TOOLS:
        raise ValueError('Unknown compatibility command.')
    app = Application(profile)
    pointer = active(app.deployment)
    python = pointer['active']['python'] if pointer else sys.executable
    return [python, '-I', *module_command('ember.runtime.' + tool, *arguments, python=python)[1:]]


def stage_launchers(profile: str | Path, bootstrap_python: str | Path) -> list[Path]:
    """Prepare reviewable shims without replacing any existing runtime scripts."""
    app = Application(profile)
    root = app.deployment.local_config_root / 'compat-launchers'
    root.mkdir(parents=True, exist_ok=True)
    result = []
    for name in sorted(RUNTIME_TOOLS):
        text = ('# Generated Ember compatibility entry; no business logic.\n'
                'import os, sys\n'
                'if __name__ == "__main__":\n'
                f'    os.execv({str(bootstrap_python)!r}, [{str(bootstrap_python)!r}, "-I", "-m", "ember.compat", '
                f'{str(app.deployment.profile)!r}, {name!r}] + sys.argv[1:])\n'
                'else:\n'
                f'    from ember.runtime.{name} import *\n')
        file = root / (name + '.py')
        if file.exists() and file.read_text() != text:
            raise ValueError('Compatibility entry differs; preserve it for review rather than overwrite.')
        if not file.exists():
            file.write_text(text)
        result.append(file)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile')
    parser.add_argument('tool', choices=sorted(RUNTIME_TOOLS))
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    target = command(args.profile, args.tool, args.arguments)
    os.execv(target[0], target)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
