"""Stable service launcher selecting one verified package installation."""
from __future__ import annotations
import argparse
import os
import sys
from .deployment import current_deployment
from .package_update import active
from .process import module_command

SERVICES = {
    'workbench': 'ember.runtime.ember_workbench_service',
    'task-index': 'ember.runtime.ember_task_index_sync',
    'system-sync': 'ember.runtime.ember_system_sync',
    'weekly': 'ember.runtime.ember_weekly_organization',
    'execution-bridge': 'ember.runtime.ember_execution_bridge',
    'mcp': 'ember.runtime.ember_mcp_server',
}


def command(service: str, arguments: list[str]) -> list[str]:
    if service not in SERVICES:
        raise ValueError('Unknown registered service.')
    profile = current_deployment()
    pointer = active(profile)
    python = pointer['active']['python'] if pointer else sys.executable
    # Isolated mode requires a caller-selected temporary workbench port.
    if service == 'workbench':
        if arguments:
            raise ValueError('Workbench service arguments come from its deployment configuration.')
    return [python, '-I', *module_command(SERVICES[service], *arguments, python=python)[1:]]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service', choices=SERVICES)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    target = command(args.service, args.arguments)
    os.execv(target[0], target)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
