#!/usr/bin/env python3
"""Prepare a project plan, or register the exact confirmed plan without migration."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="GStudio 项目方案与确认登记")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--plan", required=True, help="包含 id/name/kind/description/focus/overview 的 JSON 对象")
    parser.add_argument("--task-id", help="本次登记所属的未完成任务")
    parser.add_argument("--expected-sha256", help="用户已确认方案文件的 SHA-256")
    parser.add_argument("--confirm", action="store_true", help="只在用户明确确认完整方案后使用")
    args = parser.parse_args(argv)
    try:
        from gstudio_core.project_registration import plan_project, register_project
        from gstudio_core.store import Workspace, WorkspaceError
    except ImportError:
        print("请使用已安装 GStudio 应用的 Python 运行建项脚本。", file=sys.stderr)
        return 1
    try:
        content = Path(args.plan).read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        payload = json.loads(content)
        workspace = Workspace(args.workspace)
        proposal = plan_project(workspace, payload)
        if args.confirm:
            if not args.task_id or args.expected_sha256 != sha:
                raise WorkspaceError("登记需要原任务与用户确认的相同方案哈希；方案变化时停止。")
            from gstudio_core.server import workspace_lock
            with workspace_lock(workspace):
                result = register_project(workspace, payload, task_id=args.task_id, confirmation=True)
        else:
            result = {**proposal, "sha256": sha}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, WorkspaceError) as error:
        print(f"项目建项失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
