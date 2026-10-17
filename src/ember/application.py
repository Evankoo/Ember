"""Application entry for explicitly configured full-capability deployments."""
from __future__ import annotations

import importlib
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sys
import stat

from .deployment import Deployment, DeploymentError, current_deployment

# Compatibility command names invoke the migrated implementation, never a
# second checkout's scripts or request-provided Python modules.
RUNTIME_TOOLS = frozenset({
    'check_codex_integration',
    'check_conformance',
    'check_skill_health',
    'copy_board',
    'doctor',
    'ensure_monthly_publish_ledger',
    'gstudio_agent',
    'gstudio_archive_backup_audit',
    'gstudio_archive_index',
    'gstudio_archive_queue',
    'gstudio_daily_report',
    'gstudio_execution_bridge',
    'gstudio_mcp_server',
    'gstudio_organization',
    'gstudio_project',
    'gstudio_system_sync',
    'gstudio_task',
    'gstudio_task_index_sync',
    'gstudio_task_inputs',
    'gstudio_task_organization',
    'gstudio_weekly_organization',
    'gstudio_weekly_report',
    'gstudio_workbench_service',
    'gstudio_workspace_layout',
    'install_gstudio_execution_bridge',
    'install_gstudio_mcp',
    'install_gstudio_mount',
    'install_gstudio_sync',
    'install_gstudio_task_index_sync',
    'install_gstudio_webdav',
    'install_gstudio_weekly_organization',
    'install_gstudio_workbench',
    'migrate_task_execution_metadata',
    'migrate_task_navigation',
    'migrate_task_titles',
    'task_dashboard',
    'task_gate',
    'task_intake',
    'weekly_task_review',
})


class Application:
    def __init__(self, profile: Path | str):
        deployment = Deployment.load(profile)
        if current_deployment.cache_info().currsize and current_deployment() != deployment:
            raise DeploymentError('A process cannot switch deployment roots after loading application modules.')
        roots = {
            'GSTUDIO_SHARED_WORKSPACE_ROOT': deployment.shared_root,
            'GSTUDIO_TASK_INPUTS_ROOT': deployment.shared_root / '任务资料',
            'GSTUDIO_ARCHIVE_INBOX_ROOT': deployment.inbox_root,
            'GSTUDIO_PROJECT_ARCHIVE_ROOT': deployment.archive_root,
            'GSTUDIO_ARCHIVE_ROOT': deployment.archive_root,
            'GSTUDIO_LOCAL_CONFIG_ROOT': deployment.local_config_root,
        }
        for key, target in roots.items():
            value = os.environ.get(key)
            if value and Path(value).expanduser().resolve() != target:
                raise DeploymentError(f'{key} conflicts with the explicit deployment profile.')
        if deployment.isolation_root:
            value = os.environ.get('GSTUDIO_WORKSPACE_INBOX_ROOT')
            if value:
                path = Path(value).expanduser().resolve()
                if path != deployment.isolation_root and deployment.isolation_root not in path.parents:
                    raise DeploymentError('GSTUDIO_WORKSPACE_INBOX_ROOT escapes the isolated deployment.')
        os.environ['EMBER_DEPLOYMENT_PROFILE'] = str(deployment.profile)
        self.deployment = current_deployment()

    @contextmanager
    def service_lock(self):
        """A profile starts one local workbench, regardless of the selected port."""
        root = self.deployment.local_config_root
        root.mkdir(parents=True, exist_ok=True)
        path = root / 'workbench-service.lock'
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise DeploymentError('Workbench lock must be a regular file.')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DeploymentError('This deployment already has a running workbench.') from exc
            yield
        finally:
            os.close(fd)

    @property
    def tasks(self):
        from .tasks import TaskService, RuntimeTaskStorage
        return TaskService(RuntimeTaskStorage())

    def check(self) -> dict:
        """Read canonical metadata; never repair cards or generate an empty fallback."""
        for lifecycle in ('active', 'completed'):
            if not (self.deployment.shared_root / 'tasks' / lifecycle).is_dir():
                raise DeploymentError('Canonical task directory unavailable; refusing fallback.')
        from .runtime import gstudio_project, gstudio_task
        problems = gstudio_project.validate_registry(gstudio_project.load_registry(), require_cards=True)
        if problems:
            raise DeploymentError('Project registry validation failed: ' + '; '.join(problems))
        from .tasks import TaskError
        try:
            records = self.tasks.list()
        except TaskError as exc:
            raise DeploymentError(str(exc)) from exc
        ids = [record['id'] for record in records]
        if len(ids) != len(set(ids)):
            raise DeploymentError('Duplicate task IDs in canonical deployment metadata.')
        return {'status': 'ready', 'environment': self.deployment.environment,
                'projects': len(gstudio_project.load_registry()['projects']), 'tasks': len(records),
                'shared_root': str(self.deployment.shared_root), 'production_switch': False}

    def run_tool(self, name: str, arguments: list[str]) -> int:
        if name not in RUNTIME_TOOLS:
            raise DeploymentError('Unknown application tool.')
        module = importlib.import_module('.runtime.' + name, 'ember')
        old = sys.argv
        try:
            sys.argv = [name, *arguments]
            return int(module.main() or 0)
        finally:
            sys.argv = old

    def serve(self, port: int = 0) -> None:
        if not 0 <= port <= 65535:
            raise DeploymentError('Port must be between 0 and 65535.')
        if self.deployment.isolation_root and port in {8765, 18783}:
            raise DeploymentError('An isolated candidate cannot claim production or retired trial ports.')
        with self.service_lock():
            self.check()
            from .runtime import gstudio_task, gstudio_workbench_service
            gstudio_task.sync_index_records(publish_shared=False)
            server = gstudio_workbench_service.WorkbenchServer(('127.0.0.1', port))
            print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/', 'deployment': str(self.deployment.profile)}, ensure_ascii=False), flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
