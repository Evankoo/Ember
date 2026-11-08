#!/usr/bin/env python3
"""Prepare a project plan, or register the exact confirmed plan without migration."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ember project plan and confirmed registration")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--plan", required=True, help="A JSON object with id/name/kind/description/focus/overview")
    parser.add_argument("--task-id", help="The unfinished task this registration belongs to")
    parser.add_argument("--expected-sha256", help="SHA-256 of the plan file the user confirmed")
    parser.add_argument("--confirm", action="store_true", help="Use only after the user explicitly confirms the complete plan")
    args = parser.parse_args(argv)
    try:
        from ember.project_registration import plan_project, register_project
        from ember.store import Workspace, WorkspaceError
    except ImportError:
        print("Run the project script with the Python of the installed Ember app.", file=sys.stderr)
        return 1
    try:
        content = Path(args.plan).read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        payload = json.loads(content)
        workspace = Workspace(args.workspace)
        proposal = plan_project(workspace, payload)
        if args.confirm:
            if not args.task_id or args.expected_sha256 != sha:
                raise WorkspaceError("Registration needs the same plan hash as the original task and the user's confirmation; it stops if the plan changed.")
            from ember.server import workspace_lock
            with workspace_lock(workspace):
                result = register_project(workspace, payload, task_id=args.task_id, confirmation=True)
        else:
            result = {**proposal, "sha256": sha}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, WorkspaceError) as error:
        from ember.language import finished
        print(f"Project creation failed: {finished('en', str(error))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
