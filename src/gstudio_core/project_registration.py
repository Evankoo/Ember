"""Read-only project proposals and confirmed writes through the existing store."""
from __future__ import annotations

from .bootstrap import verify_workspace_contract
from .store import Workspace, WorkspaceError


def plan_project(workspace: Workspace, payload: dict) -> dict:
    workspace._payload(payload)
    if set(payload) - {"id", "name", "kind", "description", "focus", "overview"}:
        raise WorkspaceError("建项方案只能包含项目登记与说明字段。")
    identifier = workspace._identifier(payload.get("id"), "project id")
    if identifier == "independent":
        raise WorkspaceError("independent 是独立任务范围，不是正式项目。")
    name = workspace._string(payload, "name", required=True, limit=80)
    kind = payload.get("kind")
    if kind not in ("project", "system"):
        raise WorkspaceError("请先确认建立业务项目还是系统工作区。")
    description = workspace._string(payload, "description", required=True, limit=5000)
    focus = workspace._string(payload, "focus", limit=5000)
    overview = workspace._string(payload, "overview") or f"# {name}\n\n## 项目概况\n\n{description}\n"
    matches = [{"id": item["id"], "name": item["name"], "kind": item["kind"]}
               for item in workspace.snapshot()["projects"]
               if item["id"] == identifier or item["name"].casefold() == name.casefold()]
    return {"project": {"id": identifier, "name": name, "kind": kind, "description": description,
                        "focus": focus, "overview": overview}, "matches": matches, "can_create": not matches,
            "canonical_paths": ["config/projects.json", f"projects/{identifier}.md"],
            "boundaries": "只登记项目和说明；不迁移资料、重分配任务、调用模型或发布。"}


def register_project(workspace: Workspace, payload: dict, *, task_id: str, confirmation: bool) -> dict:
    if confirmation is not True:
        raise WorkspaceError("请先确认本次完整建项方案。")
    with workspace._lock:
        verify_workspace_contract(workspace)
        _, metadata, _ = workspace._task(task_id)
        if metadata["status"] == "completed":
            raise WorkspaceError("建项应记录在未完成的跟踪任务中。", 409)
        proposal = plan_project(workspace, payload)
        if not proposal["can_create"]:
            raise WorkspaceError("发现同 ID 或同名项目；先确认复用或修订方案，不覆盖原项目。", 409)
        result = workspace.create_project(proposal["project"])
        workspace.update_task(task_id, {"skills_used": ["gstudio-project"],
                              "log_entry": f"按确认方案登记{result['kind']}：{result['name']}（{result['id']}）；已回读登记与独立项目说明，未迁移资料或改变任务归属。"})
        return result
