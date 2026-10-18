#!/usr/bin/env python3
"""Loopback-only HTTP service for the Ember local workbench."""
from __future__ import annotations
from .ember_compat import env as ember_env
from ..deployment import runtime_root as _deployment_root

import json
import gzip
import hashlib
import io
import mimetypes
import os
import re
import secrets
import shutil
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from datetime import datetime
from email.parser import BytesParser
from email.policy import default as email_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit, urlunsplit

ROOT = _deployment_root()
from . import ember_workbench as workbench
from . import ember_archive_index as archive_index
from . import ember_agent
from . import ember_kimi
from . import ember_opencode
from . import ember_transfer
from . import ember_central_auth as central_auth
from . import ember_central_store as central_store
from . import check_skill_health
from .workspace_paths import current_environment, current_environment_name, local_config_root, shared_workspace_root

CSRF_TOKEN_PATH = local_config_root() / "workbench-csrf-token"
RUNTIME_SOURCE_PATHS = tuple(sorted(Path(__file__).resolve().parents[1].rglob('*.py'))) + tuple(sorted((Path(__file__).resolve().parents[1] / 'ember_ui' / 'static').iterdir()))
CORE_PAGE_PATHS = {"/review", "/archive", "/projects", "/library"}


def runtime_source_fingerprint() -> str:
    """Fingerprint the Python sources and shared interface files loaded by this server process."""
    digest = hashlib.sha256()
    from ..integrations import registered_source_paths
    for path in (*RUNTIME_SOURCE_PATHS, *registered_source_paths()):
        digest.update(str(path).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


STARTUP_SOURCE_FINGERPRINT = runtime_source_fingerprint()


def parse_form_body(body: bytes, content_type: str) -> dict[str, list[str]]:
    """Parse browser forms while preserving repeated fields such as selection."""
    if content_type.lower().startswith("multipart/form-data"):
        message = BytesParser(policy=email_policy).parsebytes(
            b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        )
        if not message.is_multipart():
            raise ValueError("invalid multipart form")
        values: dict[str, list[str]] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name or part.get_filename() is not None:
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            values.setdefault(name, []).append(payload.decode(charset, "replace"))
        return values
    return parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)


def load_or_create_csrf_token(path: Path = CSRF_TOKEN_PATH) -> str:
    """Keep local forms valid across routine workbench restarts."""
    try:
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 24:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(token + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return token


def normalize_executor(value: str) -> str:
    """Map retired executor identifiers to the current top-level executor."""
    return "opencode" if value == "kimi" else value


def task_return_location(
    requested: str, referer: str, host: str, task_id: str
) -> tuple[str, str]:
    """Resolve a same-origin task-detail return target and readable label."""
    current = f"/tasks/{quote(task_id, safe='')}"
    for raw in (requested, referer):
        if not raw:
            continue
        parsed = urlsplit(raw)
        if parsed.scheme or parsed.netloc:
            if parsed.scheme not in {"http", "https"} or parsed.netloc != host:
                continue
        path = parsed.path or "/"
        allowed = (
            path in {"/", "/review", "/weekly", "/projects", "/archive", "/library"}
            or path.startswith("/projects/")
            or path.startswith("/tasks/")
            or path.startswith("/settings/")
        )
        if not allowed or path == current:
            continue
        target = urlunsplit(("", "", path, parsed.query, parsed.fragment))
        if path == "/":
            label = "任务台"
        elif path in {"/review", "/weekly"}:
            label = "任务检视"
        elif path == "/projects":
            label = "项目视图"
        elif path.startswith("/projects/"):
            label = "项目任务页"
        elif path == "/archive":
            label = "归档中心"
        elif path == "/library":
            label = "资料浏览"
        elif path.startswith("/tasks/"):
            label = "上一个任务"
        else:
            label = "设置"
        return target, label
    return "/projects", "项目视图"


def health_readiness(server: WorkbenchServer | None = None) -> dict[str, object]:
    """Report canonical-data readiness separately from liveness; never raises."""
    checks: dict[str, object] = {}
    degraded = False
    try:
        root = shared_workspace_root()
        available = root.is_dir()
        checks["shared_root"] = {"path": str(root), "available": available}
        degraded = degraded or not available
    except Exception as exc:  # environment failure stays a readiness signal
        checks["shared_root"] = {"available": False, "error": type(exc).__name__}
        degraded = True
    try:
        status = workbench.task_index_sync_status()
        if not status:
            checks["task_index"] = {"state": "unknown"}
            degraded = True
        else:
            state = str(status.get("state") or "unknown")
            checks["task_index"] = {
                "state": state,
                "record_count": status.get("record_count"),
                "last_check_at": status.get("last_check_at"),
            }
            degraded = degraded or state not in {"ok", "ready"}
    except Exception as exc:
        checks["task_index"] = {"state": "unknown", "error": type(exc).__name__}
        degraded = True
    try:
        search_status = workbench.home_search_index_status()
        checks["home_search_index"] = search_status
        degraded = degraded or search_status.get("state") != "ready"
    except Exception as exc:
        checks["home_search_index"] = {"state": "unknown", "error": type(exc).__name__}
        degraded = True
    try:
        current_fingerprint = runtime_source_fingerprint()
        source_state = "ready" if current_fingerprint == STARTUP_SOURCE_FINGERPRINT else "stale"
        checks["runtime_source"] = {
            "state": source_state,
            "loaded": STARTUP_SOURCE_FINGERPRINT[:12],
            "current": current_fingerprint[:12],
        }
        degraded = degraded or source_state != "ready"
    except Exception as exc:
        checks["runtime_source"] = {"state": "unknown", "error": type(exc).__name__}
        degraded = True
    try:
        pdf_preview = workbench.pdf_preview_dependency_status()
        checks["pdf_preview"] = pdf_preview
        degraded = degraded or pdf_preview.get("state") != "ready"
    except Exception as exc:
        checks["pdf_preview"] = {"state": "unknown", "error": type(exc).__name__}
        degraded = True
    if server is not None:
        page_routes = server.core_page_health()
        checks["page_routes"] = page_routes
        degraded = degraded or page_routes.get("state") in {"stalled", "error"}
    return {
        "status": "degraded" if degraded else "ready",
        "checks": checks,
        "observed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def open_codex_project() -> None:
    explicit = workbench.executor_config().get("codex", {}).get("path", "")
    settings = workbench.executor_settings.read_settings()
    if settings.get("local_registry") and any(entry["id"] == "codex" for entry in settings["executors"]):
        explicit = workbench.executor_settings.executor_definition("codex")["path"]
    if explicit:
        application = workbench.executor_settings.validate_software_path("codex", explicit)
        arguments = ["/usr/bin/open", "-a", str(application), str(ROOT)]
    else:
        # Fixed workflows retain Launch Services discovery when no path is saved.
        arguments = ["/usr/bin/open", "-b", "com.openai.codex", str(ROOT)]
    subprocess.run(
        arguments,
        check=True,
        timeout=10,
    )


def central_mode() -> bool:
    return ember_env("EMBER_CENTRAL_MODE") == "1"


def canonical_task_card_path(task_id: str) -> Path | None:
    """Resolve a task card from the shared NAS task store, never the local cache."""
    found = workbench.tasks.find_task(task_id)
    return found[2].resolve() if found else None


def reveal_task_folder(task_id: str) -> Path:
    """Open Finder at the shared task-card folder with the task card selected."""
    task_card = canonical_task_card_path(task_id)
    if not task_card or not task_card.is_file():
        raise ValueError("没有找到可打开的 NAS 任务卡。")
    subprocess.run(["/usr/bin/open", "-R", str(task_card)], check=True)
    return task_card


class DispatchResult(NamedTuple):
    notice: str
    clipboard_text: str = ""


def dispatch_executor(
    executor: str,
    *,
    title: str,
    prompt: str,
    task_id: str = "",
    target_machine: str = "",
) -> DispatchResult:
    """Copy by default in central mode; enqueue only for an explicit bridge."""
    if central_mode():
        selected_machine = target_machine.strip()
        if not selected_machine:
            label = "Codex" if executor == "codex" else "OpenCode"
            return DispatchResult(
                f"完整提示词已生成；请到已接入 余烬 · Ember 的 {label} 中粘贴发送。",
                prompt,
            )
        live = {
            str(bridge.get("machine_id") or ""): bridge
            for bridge in central_store.live_bridges()
        }
        bridge = live.get(selected_machine)
        if not bridge:
            raise ValueError("所选执行电脑当前不在线，请刷新后重新选择。")
        if executor not in set(bridge.get("executors") or []):
            raise ValueError("所选执行电脑未启用这个执行器。")
        request = central_store.enqueue(
            executor=executor,
            title=title,
            prompt=prompt,
            task_id=task_id,
            target_machine=selected_machine,
        )
        executor_label = "Codex" if executor == "codex" else "OpenCode"
        return DispatchResult(
            f"提示词已发送到 {bridge.get('label') or selected_machine}；"
            f"执行桥将复制提示词并打开 {executor_label}（请求 {request['request_id']}）。"
        )
    if executor == "codex":
        subprocess.run(["/usr/bin/pbcopy"], input=prompt, text=True, check=True)
        open_codex_project()
        return DispatchResult("任务信息已复制，并已打开 Codex 的 余烬 · Ember 项目。")
    registered = workbench.executor_settings.read_settings()
    registered_opencode = bool(registered.get("local_registry")) and any(
        entry["id"] == "opencode" for entry in registered.get("executors", [])
    )
    if executor == "opencode" and not registered_opencode:
        ember_opencode.launch_in_otty(title=title, prompt=prompt)
        return DispatchResult("任务信息已复制到剪贴板，并已在 Otty 新标签页打开 OpenCode。")
    entry = workbench.executor_settings.executor_definition(executor)
    if entry["kind"] == "command" and (executor == "opencode" or Path(entry["path"]).name == "opencode"):
        ember_opencode.launch_in_otty(title=title, prompt=prompt, executable=Path(entry["path"]))
        return DispatchResult("任务信息已复制到剪贴板，并已在 Otty 新标签页打开 OpenCode。")
    subprocess.run(["/usr/bin/pbcopy"], input=prompt, text=True, check=True)
    if entry["kind"] == "app":
        subprocess.run(["/usr/bin/open", "-a", entry["path"]], check=True, timeout=10)
    else:
        command = "cd " + shlex.quote(str(ROOT)) + " && " + shlex.quote(entry["path"])
        script = 'tell application "Terminal"\nactivate\ndo script ' + json.dumps(command, ensure_ascii=False) + '\nend tell'
        subprocess.run(["/usr/bin/osascript", "-"], input=script, text=True, check=True, timeout=15)
    return DispatchResult(f"任务信息已复制，并已打开 {entry['label']}；请自行粘贴发送。")


def copy_prompt_only(prompt: str) -> DispatchResult:
    return DispatchResult("完整提示词已生成；请到已接入 余烬 · Ember 的 AI 工具中粘贴发送。", prompt)


def prompt_with_task_override(prompt: str, form: dict[str, str]) -> str:
    """Apply an explicit dialog edit without changing locked prompt sections."""
    override = form.get("task_override") if "task_override" in form else None
    return workbench.apply_prompt_task_override(prompt, override)


def route_task_prompt_action(
    *,
    route_mode: str,
    request_text: str,
    task_id: str = "",
    user_supplement: str = "",
    extra_context: list[str] | None = None,
    executor: str = "",
    copy_only: bool = False,
    target_machine: str = "",
    task_override: str | None = None,
) -> DispatchResult:
    prompt = workbench.route_task_prompt(
        route_mode,
        request_text,
        task_id=task_id,
        user_supplement=user_supplement,
        extra_context=extra_context,
    )
    prompt = workbench.apply_prompt_task_override(prompt, task_override)
    if copy_only:
        return copy_prompt_only(prompt)
    if not workbench.valid_executor(executor):
        raise ValueError("请选择执行器。")
    status = workbench.executor_status().get(executor, {})
    if not status.get("configured"):
        raise ValueError("所选执行工具尚未配置成功。")
    title = {"new": "首页新建任务", "continue": "首页继续任务", "derive": "首页二创任务"}.get(route_mode, "首页任务")
    return dispatch_executor(
        executor,
        title=title,
        prompt=prompt,
        task_id=task_id if route_mode in {"continue", "derive"} else "",
        target_machine=target_machine,
    )


def _safe_staging_name(filename: str) -> str:
    """Keep the uploaded basename and extension, stripping path segments."""
    name = Path(str(filename or "")).name.strip()
    if not name or name.startswith("."):
        raise ValueError("文件名无效。")
    return name


def stage_router_file(staging: dict[str, Path], filename: str, payload: bytes) -> dict[str, object]:
    """Persist one dropped file into local runtime staging; no task mutation."""
    from . import ember_task_inputs as inputs

    name = _safe_staging_name(filename)
    limit = inputs.task_input_snapshot_max_bytes()
    if len(payload) > limit:
        raise ValueError(
            f"{name} 为 {len(payload)} 字节，超过 {limit} 字节输入快照上限；"
            "请先通过 project-intake 归档后再引用。"
        )
    staging_id = uuid.uuid4().hex[:16]
    folder = ROOT / "tmp" / "home-staging" / staging_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_bytes(payload)
    staging[staging_id] = target
    return {"staging_id": staging_id, "name": name, "size": len(payload)}


def resolve_router_staged_file(staging: dict[str, Path], staging_id: str) -> Path:
    safe = re.fullmatch(r"[0-9a-f]{16}", str(staging_id or ""))
    if not safe:
        raise ValueError("无效的暂存文件编号。")
    path = staging.get(staging_id)
    if path and path.is_file():
        return path
    folder = (ROOT / "tmp" / "home-staging" / staging_id).resolve()
    staging_root = (ROOT / "tmp" / "home-staging").resolve()
    if not str(folder).startswith(str(staging_root)):
        raise ValueError("暂存文件路径越界。")
    files = [item for item in folder.glob("*") if item.is_file() and not item.name.startswith(".")] if folder.is_dir() else []
    if len(files) != 1:
        raise ValueError("暂存文件不存在或已失效；请重新拖入。")
    staging[staging_id] = files[0]
    return files[0]


def router_staged_context(
    staging: dict[str, Path], staging_ids: list[str], route_mode: str,
) -> tuple[list[Path], list[str]]:
    """Build stable prompt context without registering or moving staged files."""
    paths = [resolve_router_staged_file(staging, staging_id) for staging_id in staging_ids]
    if not paths:
        return [], []
    if route_mode in {"continue", "derive"}:
        lines = [
            "- 派发时由工作台登记以下输入快照；执行器必须从任务卡的输入项读取已登记路径：",
            *(f"  - `{path.name}`（{path.stat().st_size} 字节）" for path in paths),
        ]
    else:
        lines = [
            "- 建卡后立即用 `ember_task_inputs.py add-snapshot` 登记以下输入文件，保留原扩展名：",
            *(f"  - `{path}`（{path.stat().st_size} 字节）" for path in paths),
        ]
    return paths, lines


def register_home_snapshot(task_id: str, source: Path) -> dict[str, object]:
    """Register one staged file as an immutable task input snapshot."""
    from . import ember_task_inputs as inputs

    size = source.stat().st_size
    limit = inputs.task_input_snapshot_max_bytes()
    if size > limit:
        raise ValueError(f"{source.name} 超过输入快照上限。")
    name = inputs.validate_name(source.name)
    task_path = inputs.find_task(task_id)
    text = task_path.read_text(encoding="utf-8")
    parsed = inputs.parse_inputs(text)
    items = list(parsed["items"])
    fingerprint = inputs.sha256(source)
    identifier = inputs.item_id("snapshot", name, fingerprint)
    existing = next((item for item in items if item.get("id") == identifier), None)
    if existing:
        return existing
    folder = inputs.task_inputs_root() / task_id
    destination = folder / name
    if destination.exists():
        raise ValueError(f"输入快照已存在且不可覆盖：{destination}")
    folder.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=f".{name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
        shutil.copy2(source, temporary)
        if inputs.sha256(temporary) != fingerprint or temporary.stat().st_size != size:
            raise ValueError("输入快照校验失败。")
        os.replace(temporary, destination)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    relative = destination.relative_to(inputs.shared_workspace_root()).as_posix()
    item = {
        "id": identifier,
        "name": name,
        "purpose": "首页交接补充材料",
        "storage": "snapshot",
        "source_locator": str(source),
        "source_environment": current_environment_name(),
        "path": relative,
        "sha256": fingerprint,
        "size": size,
        "required": False,
        "added_at": inputs.now_beijing(),
    }
    items.append(item)
    inputs.update_card(
        task_path, task_id, items,
        f"首页执行交接登记任务输入快照 `{name}`；输入资料与交付物保持分离。",
    )
    return item


def dispatch_material_manager(
    executor: str,
    *,
    mode: str,
    title: str,
    prompt: str,
    task_id: str = "",
    target_machine: str = "",
) -> DispatchResult:
    try:
        choice = ember_agent.execution_choice("material-manager", executor)
        started = ember_agent.start_run(
            agent_id="material-manager",
            executor=executor,
            model=choice["model"],
            mode=mode,
            task_id=task_id,
            fallback_from=choice["fallback_from"],
            fallback_reason=choice["fallback_reason"],
        )
    except ember_agent.AgentError as exc:
        raise ValueError(str(exc)) from exc
    run = started["run"]
    bound_prompt = workbench.attach_material_manager_run(
        prompt,
        run_id=str(run["run_id"]),
        executor=executor,
        model=str(run["model"]),
        reasoning=str(run.get("reasoning") or choice["reasoning"]),
        mode=mode,
    )
    try:
        dispatched = dispatch_executor(
            executor,
            title=title,
            prompt=bound_prompt,
            task_id=task_id,
            target_machine=target_machine,
        )
    except Exception as exc:
        try:
            ember_agent.finish_run(
                run_id=str(run["run_id"]), state="failed", result_refs=[], error=str(exc)
            )
        except ember_agent.AgentError:
            pass
        raise
    model_note = f"资料管理员 · {run['model']} {run.get('reasoning') or choice['reasoning']} · {run['run_id']}。"
    return DispatchResult(f"{dispatched.notice} {model_note}", dispatched.clipboard_text)


def dispatch_nas_open(
    *, task_id: str, delivery: str, relative_path: str, target_machine: str
) -> DispatchResult:
    if not central_mode():
        raise ValueError("NAS 远程打开只用于中央工作台。")
    selected_machine = target_machine.strip()
    if not selected_machine:
        raise ValueError("请先在执行目标中选择要打开 NAS 的电脑。")
    live = {
        str(bridge.get("machine_id") or ""): bridge
        for bridge in central_store.live_bridges()
    }
    bridge = live.get(selected_machine)
    if not bridge:
        raise ValueError("所选电脑当前离线，无法打开 NAS 挂载盘。")
    if "finder" not in set(bridge.get("executors") or []):
        raise ValueError("所选电脑的执行桥版本暂不支持打开 NAS，请更新后重试。")
    target = workbench.canonical_library_delivery_path(task_id, delivery, relative_path)
    if not target:
        raise ValueError("没有找到允许打开的 NAS 文件。")
    root = shared_workspace_root().resolve()
    try:
        nas_path = target.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("当前文件不在 NAS 共享正本中。") from exc
    request = central_store.enqueue(
        executor="finder",
        title=f"在 NAS 打开 · {target.name}",
        prompt="",
        task_id=task_id,
        target_machine=selected_machine,
        nas_path=nas_path,
    )
    return DispatchResult(
        f"已发送到 {bridge.get('label') or selected_machine}；"
        f"Finder 将显示 NAS 挂载盘中的文件（请求 {request['request_id']}）。"
    )


def new_task_project_source(project: str) -> Path:
    """Resolve formal projects and the non-project independent task scope."""
    if project in {"", "independent"}:
        return workbench.task_overview_source()
    if project not in workbench.project_items():
        raise ValueError("不支持的项目上下文。")
    source = workbench.allowed_source("project", project)
    if not source:
        raise ValueError("没有找到对应项目看板。")
    return source


class WorkbenchServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int]):
        from ..tasks import TaskService, RuntimeTaskStorage
        self.tasks = TaskService(RuntimeTaskStorage())
        self.csrf_token = load_or_create_csrf_token()
        self._publish_records: list[dict[str, object]] | None = None
        self._publish_records_at = 0.0
        self._publish_records_lock = threading.Lock()
        self._archive_inbox_refresh_lock = threading.Lock()
        self._archive_inbox_refreshing = False
        self._archive_index_jobs_lock = threading.Lock()
        self._archive_index_jobs: dict[str, dict[str, object]] = {}
        self._core_page_lock = threading.Lock()
        self._core_page_routes: dict[str, dict[str, object]] = {}
        self.router_staging: dict[str, Path] = {}
        self._home_search_check_at = time.monotonic()
        super().__init__(address, WorkbenchHandler)

    def service_actions(self) -> None:
        super().service_actions()
        now = time.monotonic()
        if now - self._home_search_check_at < 10:
            return
        self._home_search_check_at = now
        # Observe the local task-index revision even without a search request.
        # Priming keeps the last snapshot and schedules any rebuild off-thread.
        try:
            workbench.prime_home_search_index()
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"Homepage search index check failed; retrying later: {type(exc).__name__}", file=sys.stderr)

    def begin_core_page_request(self, path: str) -> tuple[str, float] | None:
        normalized = "/review" if path == "/weekly" else path
        if normalized not in CORE_PAGE_PATHS:
            return None
        started_at = time.monotonic()
        with self._core_page_lock:
            route = self._core_page_routes.setdefault(normalized, {"in_flight": 0})
            route["in_flight"] = int(route.get("in_flight") or 0) + 1
            route.setdefault("oldest_started_at", started_at)
        return normalized, started_at

    def finish_core_page_request(self, request: tuple[str, float] | None, *, ok: bool) -> None:
        if request is None:
            return
        path, started_at = request
        with self._core_page_lock:
            route = self._core_page_routes.setdefault(path, {"in_flight": 0})
            route["in_flight"] = max(0, int(route.get("in_flight") or 0) - 1)
            if not route["in_flight"]:
                route.pop("oldest_started_at", None)
            route["last_state"] = "ready" if ok else "error"
            route["last_duration_ms"] = round((time.monotonic() - started_at) * 1000)
            route["last_completed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    def core_page_health(self) -> dict[str, object]:
        now = time.monotonic()
        routes: dict[str, object] = {}
        overall = "ready"
        with self._core_page_lock:
            snapshot = {path: dict(value) for path, value in self._core_page_routes.items()}
        for path in sorted(CORE_PAGE_PATHS):
            record = snapshot.get(path, {})
            in_flight = int(record.get("in_flight") or 0)
            oldest = record.get("oldest_started_at")
            age = round(now - float(oldest), 1) if in_flight and oldest is not None else 0
            state = str(record.get("last_state") or "unknown")
            if in_flight:
                state = "stalled" if age >= 5 else "busy"
            if state == "stalled":
                overall = "stalled"
            elif state == "error" and overall != "stalled":
                overall = "error"
            routes[path] = {
                "state": state,
                "in_flight": in_flight,
                "oldest_seconds": age,
                "last_duration_ms": record.get("last_duration_ms"),
                "last_completed_at": record.get("last_completed_at"),
            }
        return {"state": overall, "routes": routes}

    def publish_records(self, *, force: bool = False) -> list[dict[str, object]]:
        with self._publish_records_lock:
            if not force and self._publish_records is not None and time.monotonic() - self._publish_records_at < 60:
                return [dict(item) for item in self._publish_records]
            records = workbench.ember_publish.list_records()
            self._publish_records = [dict(item) for item in records]
            self._publish_records_at = time.monotonic()
            return [dict(item) for item in records]

    def invalidate_publish_records(self) -> None:
        with self._publish_records_lock:
            self._publish_records = None
            self._publish_records_at = 0.0

    def schedule_archive_inbox_snapshot_refresh(self) -> bool:
        """Start at most one local Inbox scan without delaying the HTTP response."""
        with self._archive_inbox_refresh_lock:
            if self._archive_inbox_refreshing:
                return False
            self._archive_inbox_refreshing = True

        def refresh() -> None:
            try:
                workbench.archive_inbox.refresh_snapshot()
            finally:
                with self._archive_inbox_refresh_lock:
                    self._archive_inbox_refreshing = False

        threading.Thread(target=refresh, name="ember-archive-inbox-refresh", daemon=True).start()
        return True

    def schedule_archive_index_refresh(self, project: str = "") -> dict[str, object]:
        """Run an AList/rclone index refresh as one background job per scope."""
        scope = project.strip() or "all"
        with self._archive_index_jobs_lock:
            for job in self._archive_index_jobs.values():
                if job.get("scope") == scope and job.get("status") in {"scheduled", "running"}:
                    return dict(job)
            job_id = f"archive-index-{int(time.time())}-{secrets.token_hex(4)}"
            job = {
                "job_id": job_id,
                "scope": scope,
                "status": "scheduled",
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "finished_at": "",
                "project_count": 0,
                "error": "",
            }
            self._archive_index_jobs[job_id] = job
            if len(self._archive_index_jobs) > 30:
                removable = [key for key, value in self._archive_index_jobs.items() if value.get("status") not in {"scheduled", "running"}]
                for key in removable[: len(self._archive_index_jobs) - 30]:
                    self._archive_index_jobs.pop(key, None)

        def refresh() -> None:
            with self._archive_index_jobs_lock:
                self._archive_index_jobs[job_id]["status"] = "running"
            try:
                payload = archive_index.refresh_project(project) if project else archive_index.refresh_all()
            except (archive_index.ArchiveIndexError, OSError, ValueError) as exc:
                with self._archive_index_jobs_lock:
                    self._archive_index_jobs[job_id].update({
                        "status": "error",
                        "error": str(exc),
                        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    })
                return
            with self._archive_index_jobs_lock:
                self._archive_index_jobs[job_id].update({
                    "status": "complete",
                    "project_count": int(payload.get("project_count") or 0),
                    "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                })

        threading.Thread(target=refresh, name=f"ember-{job_id}", daemon=True).start()
        return dict(job)

    def archive_index_job(self, job_id: str) -> dict[str, object] | None:
        with self._archive_index_jobs_lock:
            job = self._archive_index_jobs.get(job_id)
            return dict(job) if job else None


class WorkbenchHandler(BaseHTTPRequestHandler):
    server_version = "EmberWorkbench/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].lower()
        if central_mode():
            allowed = {
                value.strip().lower()
                for value in ember_env("EMBER_ALLOWED_HOSTS", "").split(",")
                if value.strip()
            }
            return bool(host and (not allowed or host in allowed))
        return host in {"127.0.0.1", "localhost"}

    def _authorized(self, path: str) -> bool:
        if not central_mode() or path in {"/health", "/healthz"}:
            return True
        authorization = self.headers.get("Authorization", "")
        if path.startswith("/api/bridge/"):
            valid = central_auth.valid_bridge_authorization(authorization)
        else:
            valid = central_auth.valid_ui_authorization(authorization)
        if valid:
            return True
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        if not path.startswith("/api/bridge/"):
            self.send_header("WWW-Authenticate", 'Basic realm="Ember Central", charset="UTF-8"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "13")
        self.end_headers()
        self.wfile.write(b"unauthorized\n")
        return False

    def _json_body(self, *, maximum: int = 1024 * 1024) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > maximum:
            raise ValueError("invalid JSON request size")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _send_json(self, payload: object, status: int = 200) -> None:
        self._send(
            json.dumps(payload, ensure_ascii=False),
            status,
            "application/json; charset=utf-8",
        )

    def _wants_json(self) -> bool:
        return (
            "application/json" in (self.headers.get("Accept") or "").lower()
            or "fetch" in (self.headers.get("X-Requested-With") or "").lower()
        )

    def _send_archive_result(
        self,
        *,
        return_to: str,
        notice: str,
        details: dict[str, object] | None = None,
        refresh: list[str] | None = None,
        status: int = HTTPStatus.OK,
    ) -> None:
        if self._wants_json():
            self._send_json({
                "ok": True,
                "notice": notice,
                "refresh": refresh or [],
                **(details or {}),
            }, status)
            return
        self._redirect(return_to, notice=notice)

    def _task_bundle(self, task_id: str) -> bytes:
        if not central_store.ID_RE.fullmatch(task_id):
            raise ValueError("invalid task id")
        shared = workbench.shared_workspace_root()
        candidates = [
            shared / "tasks" / "active" / f"{task_id}.md",
            shared / "tasks" / "completed" / f"{task_id}.md",
        ]
        card = next((path for path in candidates if path.is_file()), None)
        if not card:
            raise ValueError("task card not found")
        roots = [
            (card, Path("task") / card.name),
            (shared / "任务资料" / task_id, Path("inputs")),
            (shared / "交付" / "草稿" / task_id, Path("delivery") / "draft"),
            (shared / "交付" / "正式交付" / task_id, Path("delivery") / "final"),
        ]
        manifest: list[dict[str, object]] = []
        total = 0
        maximum = int(ember_env("EMBER_REMOTE_BUNDLE_MAX_BYTES", str(512 * 1024 * 1024)))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as archive:
            for source, logical in roots:
                paths = [source] if source.is_file() else ([path for path in source.rglob("*") if path.is_file()] if source.is_dir() else [])
                for path in paths:
                    relative = logical if source.is_file() else logical / path.relative_to(source)
                    size = path.stat().st_size
                    total += size
                    if total > maximum:
                        raise ValueError("task bundle exceeds configured limit")
                    archive.write(path, relative.as_posix())
                    manifest.append({"path": relative.as_posix(), "size": size, "sha256": central_store.sha256(path)})
            archive.writestr("manifest.json", json.dumps({"task_id": task_id, "files": manifest}, ensure_ascii=False, indent=2))
        return output.getvalue()

    def _send(
        self,
        body: str | bytes,
        status: int = 200,
        content_type: str = "text/html; charset=utf-8",
        *,
        cache_control: str = "no-store",
        frame_options: str = "DENY",
        content_security_policy: str = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; font-src 'self' data:; form-action 'self'; frame-ancestors 'none'",
    ) -> None:
        payload = body.encode("utf-8") if isinstance(body, str) else body
        use_gzip = (
            len(payload) >= 1024
            and "gzip" in self.headers.get("Accept-Encoding", "").lower()
            and (content_type.startswith("text/") or "json" in content_type)
        )
        if use_gzip:
            payload = gzip.compress(payload, compresslevel=4)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", frame_options)
        self.send_header("Content-Security-Policy", content_security_policy)
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(
        self,
        path: str,
        notice: str | DispatchResult = "",
        error: str = "",
        *,
        client_redirect: bool = False,
        clipboard_text: str = "",
    ) -> None:
        if isinstance(notice, DispatchResult):
            clipboard_text = notice.clipboard_text
            notice = notice.notice
        if not error and self.path.startswith("/actions/publish-"):
            self.server.invalidate_publish_records()
        safe = path if path.startswith("/") and not path.startswith("//") else "/"
        # AJAX requests receive JSON instead of a 303 redirect.
        accept = self.headers.get("Accept", "")
        if accept and "application/json" in accept:
            result = {"ok": not error, "error": error, "notice": notice}
            if client_redirect and not error:
                result["redirect"] = safe
            if clipboard_text and not error:
                result["clipboard_text"] = clipboard_text
            payload = json.dumps(result, ensure_ascii=False)
            self._send(payload, content_type="application/json; charset=utf-8")
            return
        params = {key: value for key, value in (("notice", notice), ("error", error)) if value}
        if params:
            parsed = urlsplit(safe)
            query = parsed.query + ("&" if parsed.query else "") + urlencode(params)
            safe = urlunsplit(("", "", parsed.path, query, parsed.fragment))
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", safe)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_file(self, path: Path, *, cache_control: str = "no-store", extra_headers: dict[str, str] | None = None) -> None:
        """Stream one allowlisted local file with byte-range support."""
        size = path.stat().st_size
        start, end = 0, max(size - 1, 0)
        status = HTTPStatus.OK
        range_header = self.headers.get("Range", "")
        if range_header.startswith("bytes=") and size:
            try:
                first, last = range_header[6:].split("-", 1)
                start = int(first) if first else 0
                end = int(last) if last else size - 1
                if start < 0 or start >= size or end < start:
                    raise ValueError
                end = min(end, size - 1)
                status = HTTPStatus.PARTIAL_CONTENT
            except (ValueError, TypeError):
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = end - start + 1 if size else 0
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not length:
            return
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                chunk = handle.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self) -> None:
        request = self.server.begin_core_page_request(urlsplit(self.path).path)
        ok = False
        try:
            self._dispatch_get()
            ok = True
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # keep the loopback server alive with a real error page
            self.log_error("GET %s failed: %s\n%s", self.path, exc, traceback.format_exc())
            try:
                self._send(
                    workbench.render_status_page(
                        "服务异常",
                        "页面暂时无法打开",
                        "工作台处理这个页面时出现异常；请刷新重试，或回到任务台继续其他操作。",
                        self.server.csrf_token,
                    ),
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            except Exception:
                pass
        finally:
            self.server.finish_core_page_request(request, ok=ok)

    def _dispatch_get(self) -> None:
        if not self._valid_host():
            self._send("invalid host", HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8")
            return
        parsed = urlsplit(self.path)
        if not self._authorized(parsed.path):
            return
        query = parse_qs(parsed.query)
        notice = query.get("notice", [""])[0]
        error = query.get("error", [""])[0]
        if parsed.path == "/api/tasks" or (parsed.path.startswith("/api/tasks/") and len(parsed.path.split("/")) == 4 and parsed.path != "/api/tasks/search"):
            from ..tasks import TaskError
            try:
                payload = {"tasks": self.server.tasks.list()} if parsed.path == "/api/tasks" else self.server.tasks.get(unquote(parsed.path[len("/api/tasks/"):]))
                self._send_json(payload)
            except TaskError as exc:
                self._send_json({"error": str(exc)}, exc.status)
            return
        if parsed.path in {"/health", "/healthz"}:
            self._send(json.dumps({
                "ok": True,
                "service": "ember-workbench",
                "environment": current_environment_name(),
                "machine_label": current_environment().get("label"),
                "readiness": health_readiness(self.server),
            }, ensure_ascii=False), content_type="application/json; charset=utf-8")
            return
        if parsed.path == "/api/bridge/pending":
            machine_id = query.get("machine_id", [""])[0]
            self._send_json({"requests": central_store.pending(machine_id)})
            return
        if parsed.path == "/api/bridge/bridges":
            self._send_json({"bridges": central_store.live_bridges()})
            return
        if parsed.path == "/api/central/bridges":
            self._send_json({"bridges": central_store.live_bridges()})
            return
        if parsed.path.startswith("/api/bridge/tasks/") and parsed.path.endswith("/bundle"):
            task_id = unquote(parsed.path[len("/api/bridge/tasks/"):-len("/bundle")]).strip("/")
            try:
                payload = self._task_bundle(task_id)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
                return
            self._send(payload, content_type="application/zip", cache_control="no-store")
            return
        static_name = parsed.path.removeprefix("/assets/") if parsed.path.startswith("/assets/") else ""
        if static_name in workbench.STATIC_ASSETS:
            self._send(
                workbench.STATIC_ASSETS[static_name],
                content_type=workbench.STATIC_CONTENT_TYPES[Path(static_name).suffix],
                cache_control="public, max-age=31536000, immutable",
            )
            return
        if parsed.path == "/assets/archive.css":
            self._send(
                workbench.ARCHIVE_CSS,
                content_type="text/css; charset=utf-8",
                cache_control="public, max-age=31536000, immutable",
            )
            return
        if parsed.path == "/assets/archive.js":
            self._send(
                workbench.ARCHIVE_JS,
                content_type="text/javascript; charset=utf-8",
                cache_control="public, max-age=31536000, immutable",
            )
            return
        if parsed.path == "/assets/project-navigation.js":
            self._send(
                workbench.PROJECT_NAVIGATION_JS,
                content_type="text/javascript; charset=utf-8",
                cache_control="public, max-age=31536000, immutable",
            )
            return
        if parsed.path == "/":
            self._send(workbench.render_home(self.server.csrf_token, notice, error))
            return
        if parsed.path == "/archive":
            archive_view = query.get("view", [""])[0]
            state = workbench.normalize_archive_view_state(
                view=archive_view,
                scene=query.get("scene", [""])[0],
                source=query.get("source", [""])[0],
                label=query.get("label", [""])[0],
                queue_view=query.get("queue", [""])[0],
                query=query.get("q", [""])[0],
                page=query.get("page", ["1"])[0],
            )
            inbox_snapshot = None
            if state["scene"] == "inbox" and state["source"] == "inbox":
                inbox_snapshot = workbench.archive_inbox.load_snapshot()
                if workbench.archive_inbox.snapshot_needs_refresh(inbox_snapshot):
                    self.server.schedule_archive_inbox_snapshot_refresh()
            self._send(workbench.render_archive(
                self.server.csrf_token, notice, error,
                view=archive_view,
                scene=str(state["scene"]),
                source=str(state["source"]),
                label=str(state["label"]),
                queue_view=str(state["queue"]),
                query=str(state["q"]),
                page=int(state["page"]),
                publish_records=self.server.publish_records(),
                inbox_snapshot=inbox_snapshot,
            ))
            return
        if parsed.path in {"/review", "/weekly"}:
            self._send(workbench.render_weekly(
                self.server.csrf_token, notice, error,
                mode=query.get("mode", [""])[0],
                review_view=query.get("label", query.get("view", [""]))[0],
                panel=query.get("panel", [""])[0],
            ))
            return
        if parsed.path == "/library":
            self._send(workbench.render_library(self.server.csrf_token, notice, error))
            return
        if parsed.path == "/projects":
            if query.get("view", [""])[0] == "tasks":
                self._redirect("/review")
                return
            self._send(workbench.render_projects(self.server.csrf_token))
            return
        if parsed.path == "/executors":
            self._redirect("/settings#execution")
            return
        if parsed.path == "/settings":
            self._send(workbench.render_settings(self.server.csrf_token, notice=notice, error=error))
            return
        if parsed.path == "/settings/executors":
            suffix = f"?{parsed.query}" if parsed.query else ""
            self._redirect(f"/settings{suffix}#execution")
            return
        if parsed.path == "/settings/agents":
            suffix = f"?{parsed.query}" if parsed.query else ""
            self._redirect(f"/settings{suffix}#agents")
            return
        if parsed.path == "/settings/skills":
            suffix = f"?{parsed.query}" if parsed.query else ""
            self._redirect(f"/settings{suffix}#skills")
            return
        if parsed.path.startswith("/api/tasks/") and parsed.path.endswith("/preview"):
            task_id = unquote(parsed.path[len("/api/tasks/"):-len("/preview")]).strip("/")
            preview = workbench.task_preview_payload(task_id)
            self._send(
                json.dumps(preview or {"error": "任务不存在"}, ensure_ascii=False),
                200 if preview else HTTPStatus.NOT_FOUND,
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/home/search":
            payload = workbench.unified_search_payload(query.get("q", [""])[0], include_external=False)
            self._send(json.dumps(payload, ensure_ascii=False), content_type="application/json; charset=utf-8")
            return
        if parsed.path == "/api/tasks/search":
            payload = workbench.task_search_payload(
                query.get("q", [""])[0],
                project=query.get("project", [""])[0],
                work_type=query.get("type", [""])[0],
                status=query.get("status", [""])[0],
            )
            self._send(json.dumps(payload, ensure_ascii=False), content_type="application/json; charset=utf-8")
            return
        if parsed.path == "/api/publish/packages":
            self._send(json.dumps({"error": "旧发布工作台接口已停止；请使用归档中心。"}, ensure_ascii=False), HTTPStatus.GONE, "application/json; charset=utf-8")
            return
        if parsed.path.startswith("/api/organization-reports/") and parsed.path.endswith("/preview"):
            task_id = unquote(parsed.path[len("/api/organization-reports/"):-len("/preview")]).strip("/")
            preview = workbench.organization_report_preview_payload(task_id)
            self._send(
                json.dumps(preview or {"error": "整理报告不存在"}, ensure_ascii=False),
                200 if preview else HTTPStatus.NOT_FOUND,
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/library/directory":
            payload = (workbench.library_flat_files_payload(
                query.get("task_id", [""])[0], query.get("delivery", [""])[0]
            ) if query.get("flat", [""])[0] == "1" else workbench.library_directory_payload(
                query.get("task_id", [""])[0], query.get("delivery", [""])[0], query.get("path", [""])[0]
            ))
            self._send(json.dumps(payload or {"error": "目录不存在"}, ensure_ascii=False), 200 if payload else HTTPStatus.NOT_FOUND, "application/json; charset=utf-8")
            return
        if parsed.path == "/api/workspace-inbox/directory":
            try:
                offset = max(0, int(query.get("offset", ["0"])[0]))
            except ValueError:
                offset = 0
            payload = workbench.workspace_inbox_directory_payload(query.get("path", [""])[0], offset)
            self._send(json.dumps(payload or {"error": "目录不存在或不允许访问"}, ensure_ascii=False), 200 if payload else HTTPStatus.NOT_FOUND, "application/json; charset=utf-8")
            return
        if parsed.path == "/api/csrf-token":
            self._send_json({"csrf_token": self.server.csrf_token})
            return
        if parsed.path == "/api/archive-fragment":
            state = workbench.normalize_archive_view_state(
                view=query.get("view", [""])[0],
                scene=query.get("scene", [""])[0],
                source=query.get("source", [""])[0],
                label=query.get("label", [""])[0],
                queue_view=query.get("queue", [""])[0],
                query=query.get("q", [""])[0],
                page=query.get("page", ["1"])[0],
            )
            panel = query.get("panel", [""])[0]
            if panel == "source" and state["scene"] == "inbox":
                snapshot = None
                if state["source"] == "inbox":
                    snapshot = workbench.archive_inbox.load_snapshot()
                    if workbench.archive_inbox.snapshot_needs_refresh(snapshot):
                        self.server.schedule_archive_inbox_snapshot_refresh()
                payload = workbench.archive_source_view_payload(
                    self.server.csrf_token,
                    state,
                    inbox_snapshot=snapshot,
                )
            elif panel == "queue":
                payload = workbench.archive_queue_view_payload(self.server.csrf_token, state)
            elif panel == "history":
                payload = workbench.archive_history_view_payload(
                    state,
                    publish_records=self.server.publish_records(),
                )
            else:
                self._send_json({"error": "归档局部视图参数无效。"}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json(payload)
            return
        if parsed.path == "/api/archive-index-job":
            job = self.server.archive_index_job(query.get("job_id", [""])[0])
            self._send_json(job or {"error": "刷新任务不存在。"}, HTTPStatus.OK if job else HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/api/archive-source/directory":
            try:
                offset = max(0, int(query.get("offset", ["0"])[0]))
                limit = max(1, min(100, int(query.get("limit", ["50"])[0])))
            except ValueError:
                offset, limit = 0, 50
            source_kind = query.get("source_kind", [""])[0]
            relative_path = query.get("path", [""])[0]
            if source_kind == "inbox" and not relative_path:
                snapshot = workbench.archive_inbox.load_snapshot()
                if workbench.archive_inbox.snapshot_needs_refresh(snapshot):
                    self.server.schedule_archive_inbox_snapshot_refresh()
            payload = workbench.archive_source_directory_payload(
                source_kind,
                relative_path,
                query.get("state", ["unclassified"])[0],
                offset=offset,
                limit=limit,
                query=query.get("q", [""])[0],
                snapshot_id=query.get("snapshot_id", [""])[0],
            )
            self._send_json(
                payload or {"error": "来源目录暂不可读，请检查 NAS 挂载后重试。", "retryable": True},
                HTTPStatus.OK if payload else HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        if parsed.path == "/api/archive-delivery/directory":
            task_id = query.get("task_id", [""])[0]
            state = query.get("delivery_state", [""])[0]
            record = workbench.record_map().get(task_id) or {}
            allowed = str(record.get("project") or "") in workbench.archive_capable_projects()
            payload = workbench.library_directory_payload(task_id, state, query.get("path", [""])[0]) if allowed else None
            self._send(json.dumps(payload or {"error": "交付目录不存在或不允许访问"}, ensure_ascii=False), 200 if payload else HTTPStatus.NOT_FOUND, "application/json; charset=utf-8")
            return
        if parsed.path == "/api/archive-queue":
            selected_view = query.get("view", [""])[0]
            if selected_view in workbench.ARCHIVE_QUEUE_VALUES:
                state = workbench.normalize_archive_view_state(
                    scene="inbox",
                    source=query.get("source", ["inbox"])[0],
                    label=query.get("label", ["unclassified"])[0],
                    queue_view=selected_view,
                )
                self._send_json(workbench.archive_queue_view_payload(self.server.csrf_token, state))
            else:
                self._send_json(workbench.archive_queue.load())
            return
        if parsed.path == "/api/archive/directory":
            payload = workbench.archive_directory_payload(query.get("path", [""])[0])
            self._send(json.dumps(payload or {"error": "归档目录不存在或不允许访问"}, ensure_ascii=False), 200 if payload else HTTPStatus.NOT_FOUND, "application/json; charset=utf-8")
            return
        if parsed.path == "/api/library/file-preview":
            payload = workbench.library_file_preview_payload(
                query.get("task_id", [""])[0],
                query.get("delivery", [""])[0],
                query.get("path", [""])[0],
            )
            self._send(json.dumps(payload or {"error": "文件不存在"}, ensure_ascii=False), 200 if payload else HTTPStatus.NOT_FOUND, "application/json; charset=utf-8")
            return
        if parsed.path == "/api/library/document-viewer":
            page = workbench.library_document_viewer_html(
                query.get("task_id", [""])[0],
                query.get("delivery", [""])[0],
                query.get("path", [""])[0],
            )
            self._send(
                page or "<h1>文档不存在</h1>",
                200 if page else HTTPStatus.NOT_FOUND,
                frame_options="SAMEORIGIN",
                content_security_policy="default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'none'; frame-ancestors 'self'",
            )
            return
        if parsed.path == "/api/library/preview-page":
            try:
                page_number = int(query.get("page", ["0"])[0])
            except ValueError:
                page_number = 0
            path = workbench.library_preview_page_path(
                query.get("task_id", [""])[0],
                query.get("delivery", [""])[0],
                query.get("path", [""])[0],
                page_number,
            )
            if not path or not path.is_file():
                self._send("preview page not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
                return
            self._send_file(path, cache_control="private, max-age=31536000, immutable")
            return
        if parsed.path.startswith("/api/library/office-preview/"):
            decoded = unquote(parsed.path[len("/api/library/office-preview/"):])
            parts = decoded.split("/", 1)
            path = workbench.library_quicklook_asset_path(parts[0], parts[1]) if len(parts) == 2 else None
            if not path or not path.is_file():
                self._send("office preview asset not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
                return
            headers = {
                "Referrer-Policy": "no-referrer",
            }
            if path.suffix.lower() in {".html", ".htm"}:
                policy = (
                    "sandbox allow-scripts; default-src 'none'; "
                    "img-src 'self' data: blob:; media-src 'self' data: blob:; "
                    "style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
                    "script-src 'self' 'unsafe-inline'; frame-src 'self'; object-src 'self'; "
                    "form-action 'none'"
                )
                if path.name == "Preview.html":
                    policy += "; frame-ancestors 'self'"
                headers["Content-Security-Policy"] = policy
            cache_control = "private, no-cache, max-age=0" if path.name == "Preview.html" else "private, max-age=31536000, immutable"
            self._send_file(path, cache_control=cache_control, extra_headers=headers)
            return
        if parsed.path.startswith("/api/library/content/"):
            decoded = unquote(parsed.path[len("/api/library/content/"):])
            parts = decoded.split("/", 2)
            path = workbench.library_delivery_path(parts[0], parts[1], parts[2]) if len(parts) == 3 else None
            if not path or not path.is_file():
                self._send("file not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
                return
            if path.suffix.lower() in workbench.LIBRARY_HTML_SUFFIXES:
                rendered = workbench.library_html_preview_content(parts[0], parts[1], parts[2])
                if rendered is None:
                    self._send("file not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
                    return
                self._send(
                    rendered,
                    frame_options="SAMEORIGIN",
                    content_security_policy="sandbox; default-src 'none'; img-src 'self' data: blob:; media-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; form-action 'none'; frame-ancestors 'self'",
                )
                return
            self._send_file(path)
            return
        if parsed.path == "/api/library/html-asset":
            path = workbench.library_html_asset_path(
                query.get("task_id", [""])[0],
                query.get("path", [""])[0],
            )
            if not path:
                self._send("file not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
                return
            self._send_file(path, cache_control="private, max-age=300")
            return
        if parsed.path == "/api/library/raw":
            path = workbench.library_delivery_path(
                query.get("task_id", [""])[0],
                query.get("delivery", [""])[0],
                query.get("path", [""])[0],
            )
            if not path or not path.is_file():
                self._send("file not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
                return
            headers = {}
            if query.get("download", [""])[0] == "1":
                headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(path.name, safe='')}"
            self._send_file(path, extra_headers=headers)
            return
        if parsed.path.startswith("/tasks/"):
            task_id = unquote(parsed.path[len("/tasks/"):]).strip("/")
            back_path, back_label = task_return_location(
                query.get("return_to", [""])[0],
                self.headers.get("Referer", ""),
                self.headers.get("Host", ""),
                task_id,
            )
            page = workbench.render_task(
                task_id,
                self.server.csrf_token,
                notice,
                error,
                back_path=back_path,
                back_label=back_label,
            )
            self._send(
                page
                or workbench.render_status_page(
                    "任务不存在",
                    "任务不存在",
                    "没有找到这个任务卡；它可能已被移动、合并或完成整理。",
                    self.server.csrf_token,
                ),
                200 if page else 404,
            )
            return
        match = parsed.path.split("/")
        if len(match) == 3 and match[1] == "projects":
            project = unquote(match[2])
            page = workbench.render_project_tasks(project, self.server.csrf_token)
            self._send(
                page
                or workbench.render_status_page(
                    "项目任务视图不存在",
                    "项目任务视图不存在",
                    "没有找到这个项目的任务视图；请从项目视图重新进入。",
                    self.server.csrf_token,
                ),
                200 if page else 404,
            )
            return
        self._send(
            workbench.render_status_page(
                "页面不存在",
                "页面不存在",
                "这个地址没有对应的页面；请从导航重新进入。",
                self.server.csrf_token,
            ),
            HTTPStatus.NOT_FOUND,
        )

    def do_POST(self) -> None:
        if not self._valid_host():
            self._send("invalid host", HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8")
            return
        parsed_path = urlsplit(self.path).path
        if not self._authorized(parsed_path):
            return
        if parsed_path.startswith("/api/bridge/"):
            try:
                payload = self._json_body()
                machine_id = str(payload.get("machine_id") or "")
                if parsed_path == "/api/bridge/register":
                    result = central_store.register_bridge(
                        machine_id,
                        label=str(payload.get("label") or ""),
                        executors=[str(value) for value in payload.get("executors", []) if isinstance(value, str)],
                    )
                elif parsed_path.startswith("/api/bridge/requests/"):
                    request_id = unquote(parsed_path[len("/api/bridge/requests/"):]).strip("/")
                    result = central_store.transition(
                        request_id,
                        machine_id=machine_id,
                        status=str(payload.get("status") or ""),
                        error=str(payload.get("error") or ""),
                    )
                else:
                    self._send_json({"error": "unknown bridge action"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json(result)
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        if parsed_path == "/api/router/stage-file":
            content_type = self.headers.get("Content-Type", "")
            if not content_type.lower().startswith("multipart/form-data"):
                self._send_json({"error": "仅支持表单上传"}, HTTPStatus.BAD_REQUEST)
                return
            if length <= 0 or length > 256 * 1024 * 1024:
                self._send_json({"error": "文件大小无效"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                message = BytesParser(policy=email_policy).parsebytes(
                    b"Content-Type: " + content_type.encode("latin-1", "replace")
                    + b"\r\nMIME-Version: 1.0\r\n\r\n" + self.rfile.read(length)
                )
                csrf_value = ""
                file_name = ""
                file_payload = b""
                for part in message.iter_parts():
                    field = part.get_param("name", header="content-disposition")
                    if field == "csrf":
                        csrf_value = (part.get_payload(decode=True) or b"").decode("utf-8", "replace").strip()
                    elif field == "file":
                        file_name = part.get_filename() or ""
                        file_payload = part.get_payload(decode=True) or b""
                if not secrets.compare_digest(csrf_value, self.server.csrf_token):
                    self._send_json({"error": "页面令牌已失效，请刷新页面后重试。"}, HTTPStatus.FORBIDDEN)
                    return
                if not file_name or not file_payload:
                    self._send_json({"error": "没有收到文件"}, HTTPStatus.BAD_REQUEST)
                    return
                result = stage_router_file(self.server.router_staging, file_name, file_payload)
                self._send_json(result)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        if length <= 0 or length > 1024 * 1024:
            self._send("invalid request", HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8")
            return
        try:
            parsed_form = parse_form_body(
                self.rfile.read(length),
                self.headers.get("Content-Type", "application/x-www-form-urlencoded"),
            )
        except (LookupError, ValueError):
            self._send("invalid request", HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8")
            return
        form = {key: values[0] for key, values in parsed_form.items()}
        return_to = form.get("return_to", "/")
        if not secrets.compare_digest(form.get("csrf", ""), self.server.csrf_token):
            if self._wants_json():
                self._send_json({
                    "error": "页面令牌已失效，已更新；正在保留当前选择并重试。",
                    "csrf_token": self.server.csrf_token,
                    "retryable": True,
                }, HTTPStatus.FORBIDDEN)
                return
            self._redirect(return_to, error="页面令牌已失效，请刷新页面后重试。")
            return
        try:
            default_actions = {
                "/actions/route-task", "/actions/new-task", "/actions/continue-task",
                "/actions/create-task-from-deliveries", "/actions/create-task-from-inputs",
                "/actions/revise-library-files", "/actions/workspace-inbox-task", "/actions/archive-item",
                "/actions/organize-selected-tasks", "/actions/organization-start", "/actions/weekly-confirm",
                "/actions/organize-project-intro", "/actions/organize-project-intro-chat",
                "/actions/maintain-project-intro", "/actions/archive-maintenance-start",
                "/actions/archive-batch-execute", "/actions/organize-archive-project",
                "/actions/open-archive-detection",
            }
            copy_only = parsed_path == "/actions/route-task" and form.get("copy_only") == "1"
            if parsed_path in default_actions and not copy_only and ember_env("EMBER_CENTRAL_MODE") != "1":
                environment = workbench.execution_environment()
                if not environment["executor_ready"]:
                    raise ValueError(environment["executor_error"] or "请先在设置页配置执行环境。")
                if form.get("executor") and normalize_executor(form["executor"]) != environment["executor"]:
                    raise ValueError("默认执行器已改变，请重新打开执行确认。")
                form["executor"] = environment["executor"]
            bound_manager_action = parsed_path in {"/actions/material-manager-start", "/actions/archive-batch-execute", "/actions/archive-item"} or (
                parsed_path == "/actions/workspace-inbox-task" and form.get("inbox_action") in {"archive_selected", "publish_archive"}
            )
            if bound_manager_action and normalize_executor(form.get("executor", "codex")) not in {"codex", "opencode"}:
                raise ValueError("资料管理员仍使用其已登记的 Codex / OpenCode 执行策略；普通软件登记不会获得这些权限。")
            if parsed_path == "/api/router/preview-prompt":
                route_mode = form.get("route_mode", "")
                request_text = form.get("request_text", "").strip()
                task_id = form.get("task_id", "").strip()
                if route_mode not in {"new", "continue", "derive"}:
                    raise ValueError("请选择有效的任务路由。")
                if not request_text:
                    raise ValueError("请描述本轮要求。")
                if route_mode in {"continue", "derive"} and not task_id:
                    raise ValueError("请先选择要继续或作为来源的任务。")
                _, extra_context = router_staged_context(
                    self.server.router_staging,
                    parsed_form.get("staged_file_id", []),
                    route_mode,
                )
                material_context = workbench.home_material_context(parsed_form.get("material_selection", [])) if parsed_form.get("material_selection") else []
                extra_context = [*extra_context, *material_context]
                prompt = workbench.route_task_prompt(
                    route_mode,
                    request_text,
                    task_id=task_id,
                    user_supplement=form.get("user_supplement", ""),
                    extra_context=extra_context,
                )
                preview = workbench.editable_prompt_preview(prompt)
                preview.update(workbench.execution_environment())
                self._send_json(preview)
                return
            if parsed_path == "/api/execution/preview-prompt":
                action_path = form.get("action_path", "").strip()
                if not action_path.startswith("/actions/"):
                    raise ValueError("无效的执行动作。")
                preview = workbench.execution_prompt_preview(action_path, form, parsed_form)
                preview.update(workbench.editable_prompt_preview(preview["prompt"]))
                preview.update(workbench.execution_environment(str(preview.get("fixed_executor") or "")))
                self._send_json(preview)
                return
            if self.path in {"/actions/publish-create", "/actions/publish-status", "/actions/publish-associate", "/actions/publish-archive", "/actions/publish-confirm", "/actions/publish-edit"}:
                raise ValueError("旧发布工作台入口已停止；请在归档中心选择素材并使用“发布归档”类型。")
            if parsed_path == "/actions/discover-executor-software":
                self._send_json({"ok": True, **workbench.executor_settings.discover_software()})
                return
            if parsed_path == "/actions/check-executor-settings":
                workbench.executor_settings.validate_settings(form)
                self._redirect(return_to, notice="软件路径检查通过；没有保存配置，也没有启动软件或修改客户端配置。")
                return
            if parsed_path == "/actions/save-executor-settings":
                result = workbench.executor_settings.save_settings(form)
                notice = "已保存 余烬 · Ember 软件路径；模型与登录继续由软件管理。" if result["changed_files"] else "配置已一致，无需改写。"
                self._redirect("/settings#execution", notice=notice, client_redirect=True)
                return
            if parsed_path == "/actions/refresh-settings-health":
                payload = check_skill_health.collect_health()
                check_skill_health.write_snapshot(payload)
                readiness = health_readiness(self.server)
                entries = payload.get("entries")
                registered = len(entries) if isinstance(entries, dict) else 0
                readiness_label = "正常" if readiness.get("status") == "ready" else "部分异常"
                self._redirect(
                    return_to,
                    notice=f"健康检查已完成：系统{readiness_label}，已检测 {registered} 个注册 Skill。",
                    client_redirect=True,
                )
                return
            if parsed_path == "/actions/agent-install":
                result = ember_agent.install_agent(form.get("agent_id", ""))
                self._redirect(
                    return_to,
                    notice=f"资料管理员 Hermes 适配器已安装：{result.get('hermes_profile')}。",
                    client_redirect=True,
                )
                return
            if parsed_path == "/actions/agent-verify":
                result = ember_agent.verify_agent(form.get("agent_id", ""))
                if not result.get("ok"):
                    raise ValueError("；".join(result.get("errors") or ["Agent 验证失败"]))
                states = "、".join(
                    f"{name}:{item.get('state')}" for name, item in result.get("executors", {}).items()
                )
                self._redirect(return_to, notice=f"资料管理员验证通过；{states}。", client_redirect=True)
                return
            if parsed_path == "/actions/agent-expire-runs":
                result = ember_agent.expire_stale_runs()
                self._redirect(
                    return_to,
                    notice=f"已收口 {result.get('expired_count', 0)} 个过期资料管理员运行记录，历史台账未删除。",
                    client_redirect=True,
                )
                return
            if parsed_path == "/actions/material-manager-start":
                executor = normalize_executor(form.get("executor", "codex"))
                mode = form.get("mode", "file_management")
                task_id = form.get("task_id", "")
                if mode == "task_organization":
                    selected_task_ids = parsed_form.get("selected_task_id", [])
                    prompt = workbench.material_manager_task_organization_prompt(selected_task_ids)
                    title = f"资料管理员 · 任务整理 · {len(dict.fromkeys(selected_task_ids))} 项"
                else:
                    selections = parsed_form.get("selection", [])
                    prompt = workbench.material_manager_prompt(mode, task_id=task_id, selections=selections)
                    title = "资料管理员 · 文件处理"
                dispatch = dispatch_material_manager(
                    executor,
                    mode=mode,
                    title=title,
                    prompt=prompt,
                    task_id=task_id,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(return_to, notice=dispatch.notice, clipboard_text=dispatch.clipboard_text)
                return
            if self.path == "/actions/archive-queue-add":
                payload = workbench.archive_queue_add(int(form.get("revision", "0")), parsed_form.get("selection", []))
                operation = payload.get("operation") if isinstance(payload.get("operation"), dict) else {}
                added = int(operation.get("added") or 0)
                covered = int(operation.get("covered") or 0)
                detail = f"；另有 {covered} 项已在归档篮或已被所选上级文件夹包含" if covered else ""
                self._send_archive_result(
                    return_to=return_to,
                    notice=f"已向归档篮追加 {added} 项{detail}；revision {payload.get('revision')}。",
                    details={"revision": int(payload.get("revision") or 0), "operation": operation},
                    refresh=["queue"],
                )
                return
            if self.path == "/actions/archive-inbox-transition":
                payload = workbench.archive_inbox_transition(
                    parsed_form.get("selection", []),
                    form.get("source_state", ""),
                    form.get("target_state", ""),
                )
                updated = len(payload.get("updated") or payload.get("moved") or [])
                duplicates = len(payload.get("duplicates") or [])
                detail = f"；拦截 {duplicates} 个重复归档候选" if duplicates else ""
                queued = int(payload.get("queued") or 0)
                removed = int(payload.get("removed_from_queue") or 0)
                queue_detail = f"；自动入队 {queued} 项" if queued else f"；自动移出队列 {removed} 项" if removed else ""
                self.server.schedule_archive_inbox_snapshot_refresh()
                self._send_archive_result(
                    return_to=return_to,
                    notice=f"已更新 {updated} 项收件箱标签{queue_detail}{detail}。",
                    details={
                        "updated": payload.get("updated") or [],
                        "moved": payload.get("moved") or [],
                        "duplicates": payload.get("duplicates") or [],
                        "queued": queued,
                        "removed_from_queue": removed,
                        "queue_revision": int(payload.get("revision") or payload.get("queue_revision") or 0),
                    },
                    refresh=["source", "queue"],
                )
                return
            if self.path == "/actions/archive-inbox-delete":
                payload = workbench.archive_inbox_delete(parsed_form.get("selection", []))
                deleted = len(payload.get("deleted") or [])
                failed = len(payload.get("errors") or [])
                detail = f"；{failed} 项删除失败" if failed else ""
                self.server.schedule_archive_inbox_snapshot_refresh()
                self._send_archive_result(
                    return_to=return_to,
                    notice=f"已从 NAS Inbox 永久删除 {deleted} 项{detail}。",
                    details={
                        "deleted": payload.get("deleted") or [],
                        "errors": payload.get("errors") or [],
                        "skipped_descendants": payload.get("skipped_descendants") or [],
                    },
                    refresh=["source"],
                )
                return
            if self.path == "/actions/refresh-archive-inbox-snapshot":
                workbench.archive_inbox.invalidate_snapshot(reason="manual_refresh")
                scheduled = self.server.schedule_archive_inbox_snapshot_refresh()
                self._send_archive_result(
                    return_to=return_to,
                    notice="Inbox 快照已在后台刷新；当前列表会自动更新。",
                    details={"scheduled": scheduled},
                    refresh=["source"],
                    status=HTTPStatus.ACCEPTED,
                )
                return
            if self.path == "/actions/open-archive-inbox":
                target = workbench.archive_inbox_open_path(form.get("state", "unclassified"))
                subprocess.run(["/usr/bin/open", str(target)], check=True, timeout=10)
                self._redirect(return_to, notice="已在 Finder 打开 NAS Inbox 文件夹。")
                return
            if self.path == "/actions/archive-queue-update":
                payload = workbench.archive_queue_update(int(form.get("revision", "0")), parsed_form.get("item_id", []), form)
                self._send_archive_result(
                    return_to=return_to,
                    notice=f"队列信息已批量更新；revision {payload.get('revision')}。",
                    details={"revision": int(payload.get("revision") or 0)},
                    refresh=["queue"],
                )
                return
            if self.path == "/actions/archive-queue-recheck-source":
                payload = workbench.archive_queue_recheck_sources(
                    int(form.get("revision", "0")),
                    parsed_form.get("item_id", []),
                )
                if int(payload.get("recovered") or 0):
                    notice = f"已重新定位 {payload.get('recovered')} 项来源；请重新检查归档信息。"
                else:
                    notice = "来源仍与原指纹不一致；未沿用旧确认。请移出队列后重新加入。"
                self._send_archive_result(
                    return_to=return_to,
                    notice=notice,
                    details={
                        "revision": int(payload.get("revision") or 0),
                        "checked": int(payload.get("checked") or 0),
                        "recovered": int(payload.get("recovered") or 0),
                        "unresolved": int(payload.get("unresolved") or 0),
                    },
                    refresh=["queue"],
                )
                return
            if self.path == "/actions/archive-queue-remove":
                payload = workbench.archive_queue_remove(int(form.get("revision", "0")), parsed_form.get("item_id", []))
                snapshot = workbench.archive_inbox.load_snapshot()
                if workbench.archive_inbox.snapshot_needs_refresh(snapshot):
                    self.server.schedule_archive_inbox_snapshot_refresh()
                self._send_archive_result(
                    return_to=return_to,
                    notice=f"已移出队列；NAS Inbox 来源同时取消待归档标签，文件未改变。revision {payload.get('revision')}。",
                    details={"revision": int(payload.get("revision") or 0)},
                    refresh=["source", "queue"],
                )
                return
            if self.path == "/actions/archive-queue-confirm":
                batch = workbench.archive_queue_confirm(int(form.get("revision", "0")), parsed_form.get("item_id", []), form)
                self._send_archive_result(
                    return_to=return_to,
                    notice=f"批次 {batch.get('batch_id')} 已锁定，可选择执行器。",
                    details={
                        "batch_id": str(batch.get("batch_id") or ""),
                        "confirmed_revision": int(batch.get("confirmed_revision") or 0),
                    },
                    refresh=["queue"],
                )
                return
            if self.path == "/actions/archive-batch-return":
                payload = workbench.archive_batch_return_to_queue(
                    int(form.get("revision", "0")),
                    form.get("batch_id", ""),
                )
                self._send_archive_result(
                    return_to=return_to,
                    notice=f"已返回队列修改信息；恢复 {payload.get('restored', 0)} 项，原有填写已保留。",
                    details={
                        "revision": int(payload.get("revision") or 0),
                        "restored": int(payload.get("restored") or 0),
                        "batch_id": str(payload.get("batch_id") or form.get("batch_id") or ""),
                    },
                    refresh=["queue"],
                )
                return
            if self.path == "/actions/archive-batch-execute":
                batch_id = form.get("batch_id", "")
                queue_payload = workbench.archive_queue.load()
                batch = next(
                    (item for item in queue_payload.get("batches", []) if item.get("batch_id") == batch_id),
                    None,
                )
                if not batch:
                    raise ValueError("确认批次不存在，请重新确认。")
                if str(batch.get("status") or "confirmed") in {"conflict", "failed_retryable", "receipt_pending"}:
                    workbench.archive_batch_reconfirm_recovery(batch_id)
                prompt = workbench.archive_batch_prompt(batch_id)
                executor = normalize_executor(form.get("executor", ""))
                status = workbench.executor_status().get(executor, {})
                if not status.get("configured"):
                    raise ValueError("所选执行工具尚未配置成功。")
                dispatch = dispatch_material_manager(
                    executor, mode="project_archive", title=f"批量归档 · {batch_id}", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(
                    return_to,
                    notice=f"{dispatch.notice} 执行器将逐包处理。",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            if self.path == "/actions/archive-maintenance-start":
                prompt = workbench.archive_maintenance_prompt(form.get("scope", ""))
                prompt = prompt_with_task_override(prompt, form)
                executor = normalize_executor(form.get("executor", ""))
                status = workbench.executor_status().get(executor, {})
                if not status.get("configured"):
                    raise ValueError("所选执行工具尚未配置成功。")
                dispatch = dispatch_executor(
                    executor, title="归档中心 · 整理维护", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(
                    return_to,
                    notice=f"{dispatch.notice} 先生成只读建议，不启动资料管理员。",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            if self.path == "/actions/publish-create":
                record = workbench.ember_publish.create_record(
                    project=form.get("project", ""),
                    topic=form.get("topic", ""),
                    platform=form.get("platform", ""),
                    account=form.get("account", ""),
                    status="copy_review",
                    copy_source="gstudio",
                    copy_text=form.get("copy_text", ""),
                    published_at="",
                    source_task_id=form.get("source_task_id", ""),
                    material_path=form.get("material_path", ""),
                )
                workbench.tasks.sync_index_records(publish_shared=False)
                self._redirect(return_to, notice=f"发布记录 {record.get('release_id')} 已建立。")
                return
            if self.path == "/actions/publish-status":
                project = form.get("project", "")
                release_id = form.get("release_id", "")
                changes: dict[str, object] = {"status": form.get("status", "")}
                if form.get("published_at"):
                    changes["published_at"] = form["published_at"]
                elif form.get("status") == "published":
                    changes["published_at"] = datetime.now().astimezone().strftime("%Y-%m-%d")
                record = workbench.ember_publish.update_record(project, release_id, **changes)
                workbench.tasks.sync_index_records(publish_shared=False)
                self._redirect(return_to, notice=f"{release_id} 已更新为{workbench.ember_publish.STATUS_LABELS.get(str(record.get('status')), record.get('status'))}。")
                return
            if self.path == "/actions/publish-associate":
                project = form.get("project", "")
                release_id = form.get("release_id", "")
                material_path = form.get("material_path", "")
                if not material_path:
                    raise ValueError("请选择资料包。")
                workbench.ember_publish.update_record(project, release_id, material_path=material_path)
                workbench.tasks.sync_index_records(publish_shared=False)
                self._redirect(return_to, notice=f"{release_id} 已关联资料包。")
                return
            if self.path == "/actions/publish-archive":
                project = form.get("project", "")
                release_id = form.get("release_id", "")
                record = workbench.ember_publish.find_record(project, release_id)
                if not record:
                    raise ValueError("发布记录不存在。")
                if str(record.get("status") or "") != "published":
                    raise ValueError("只有已经发布且待归档的记录才能发起归档。")
                prompt = workbench.publish_record_archive_prompt(record)
                prompt = prompt_with_task_override(prompt, form)
                executor = normalize_executor(form.get("executor", ""))
                status = workbench.executor_status().get(executor, {})
                if not status.get("configured"):
                    raise ValueError("所选执行工具尚未配置成功。")
                dispatch = dispatch_executor(
                    executor, title=f"发布归档 · {record.get('topic') or release_id}", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(
                    return_to,
                    notice=f"{release_id}：{dispatch.notice}",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            if self.path == "/actions/publish-confirm":
                project = form.get("project", "")
                release_id = form.get("release_id", "")
                record = workbench.ember_publish.find_record(project, release_id)
                if not record:
                    raise ValueError("发布记录不存在。")
                current = str(record.get("status") or "")
                target = "ready" if current == "copy_review" else "copy_review"
                workbench.ember_publish.update_record(project, release_id, status=target)
                workbench.tasks.sync_index_records(publish_shared=False)
                label = "已确认，待发布" if target == "ready" else "已取消确认"
                self._redirect(return_to, notice=f"{release_id} {label}。")
                return
            if self.path == "/actions/publish-edit":
                project = form.get("project", "")
                release_id = form.get("release_id", "")
                record = workbench.ember_publish.find_record(project, release_id)
                if not record:
                    raise ValueError("发布记录不存在。")
                if str(record.get("status")) in {"archived", "rejected"}:
                    raise ValueError("历史记录不能在工作台中修改。")
                changes: dict[str, object] = {}
                for key in ("topic", "platform", "account", "material_path", "copy_text"):
                    if key in form:
                        changes[key] = form[key]
                if not changes:
                    raise ValueError("没有可更新的字段。")
                workbench.ember_publish.update_record(project, release_id, **changes)
                workbench.tasks.sync_index_records(publish_shared=False)
                self._redirect(return_to, notice=f"{release_id} 已更新。")
                return
            if self.path == "/actions/review-view-create":
                payload = workbench.review_views.create_view(
                    form.get("name", ""), expected_revision=int(form.get("revision", "0"))
                )
                self._redirect(return_to, notice="标签已创建；当前仍显示全部任务，可以勾选任务后添加标签。")
                return
            if self.path == "/actions/review-view-rename":
                workbench.review_views.rename_view(
                    form.get("view_id", ""), form.get("name", ""),
                    expected_revision=int(form.get("revision", "0")),
                )
                self._redirect(return_to, notice="标签名称已更新。")
                return
            if self.path == "/actions/review-view-delete":
                workbench.review_views.delete_view(
                    form.get("view_id", ""), expected_revision=int(form.get("revision", "0"))
                )
                self._redirect(return_to, notice="标签已删除；任务卡和交付物未改变。")
                return
            if self.path == "/actions/review-view-members":
                task_ids = list(dict.fromkeys(parsed_form.get("selected_task_id", [])))
                records = workbench.record_map()
                if not task_ids or any(task_id not in records for task_id in task_ids):
                    raise ValueError("请选择有效任务卡。")
                view_id = form.get("view_id", "")
                action = form.get("action", "")
                revision = int(form.get("revision", "0"))
                if view_id == "focus":
                    workbench.review_views.update_focus_tasks(task_ids, action, expected_revision=revision)
                else:
                    workbench.review_views.update_view_tasks(view_id, task_ids, action, expected_revision=revision)
                label = "加入" if action == "add" else "移出"
                self._redirect(return_to, notice=f"已将 {len(task_ids)} 张任务卡{label}标签；任务卡内容未修改。")
                return
            if self.path == "/actions/project-priority":
                project = form.get("project", "")
                task_id = form.get("task_id", "")
                if project not in workbench.project_overview_scope_slugs():
                    raise ValueError("不支持的任务范围。")
                workbench.set_project_task_priority(project, task_id, form.get("important") == "1")
                self._redirect(return_to, notice="当前重要事项已更新。")
                return
            if self.path == "/actions/project-favorite":
                value = form.get("favorite", "")
                if value not in {"0", "1"}:
                    raise ValueError("收藏状态无效。")
                workbench.set_project_favorite(form.get("project", ""), value == "1")
                self._redirect(return_to, notice="项目已收藏置顶。" if value == "1" else "已取消项目收藏。", client_redirect=True)
                return
            if self.path == "/actions/project-order":
                workbench.set_project_display_order(parsed_form.get("project_order", []))
                self._redirect(return_to, notice="项目顺序已更新。")
                return
            if self.path == "/actions/open-folder":
                task_id = form.get("task_id", "")
                record = workbench.record_map().get(task_id)
                folder = workbench.resolve_delivery_folder(record) if record else None
                if not folder:
                    raise ValueError("没有找到可打开的交付文件夹。")
                if central_mode():
                    self._redirect(
                        f"/tasks/{quote(task_id, safe='')}#taskDeliveryWorkspace",
                        notice="已在工作台中打开 NAS 交付文件夹。",
                        client_redirect=True,
                    )
                    return
                subprocess.run(["/usr/bin/open", str(folder)], check=True)
                self._redirect(return_to, notice="已在 Finder 打开交付文件夹。")
                return
            if self.path == "/actions/open-task-folder":
                task_id = form.get("task_id", "")
                task_card = canonical_task_card_path(task_id)
                if not task_card or not task_card.is_file():
                    raise ValueError("没有找到可打开的 NAS 任务卡。")
                if central_mode():
                    self._redirect(
                        f"/tasks/{quote(task_id, safe='')}",
                        notice="已回到当前任务卡。",
                        client_redirect=True,
                    )
                    return
                reveal_task_folder(task_id)
                self._redirect(return_to, notice="已在 Finder 中显示任务卡所在文件夹。")
                return
            if self.path == "/actions/open-task-input-folder":
                task_id = form.get("task_id", "")
                folder = workbench.task_input_root(task_id)
                if not folder:
                    raise ValueError("没有找到可打开的任务输入目录。")
                if central_mode():
                    self._redirect(
                        f"/tasks/{quote(task_id, safe='')}#taskDeliveryWorkspace",
                        notice="已在工作台中打开 NAS 输入资料。",
                        client_redirect=True,
                    )
                    return
                subprocess.run(["/usr/bin/open", str(folder)], check=True)
                self._redirect(return_to, notice="已在 Finder 打开输入资料目录。")
                return
            if self.path == "/actions/open-task-input":
                task_id = form.get("task_id", "")
                path = workbench.task_input_path(task_id, form.get("path", ""))
                if not path or not path.is_file():
                    raise ValueError("没有找到允许打开的任务输入文件。")
                if central_mode():
                    self._redirect(
                        f"/tasks/{quote(task_id, safe='')}#taskDeliveryWorkspace",
                        notice="已在工作台中定位 NAS 输入资料。",
                        client_redirect=True,
                    )
                    return
                subprocess.run(["/usr/bin/open", "-R", str(path)], check=True)
                self._redirect(return_to, notice="已在 Finder 中显示输入资料。")
                return
            if self.path == "/actions/open-library-item":
                task_id = form.get("task_id", "")
                delivery = form.get("delivery", "")
                relative_path = form.get("path", "")
                path = workbench.canonical_library_delivery_path(task_id, delivery, relative_path)
                if not path:
                    raise ValueError("没有找到允许打开的交付文件。")
                mode = form.get("mode", "reveal")
                if central_mode():
                    if mode == "nas":
                        notice = dispatch_nas_open(
                            task_id=task_id,
                            delivery=delivery,
                            relative_path=relative_path,
                            target_machine=form.get("machine_id", ""),
                        )
                        self._redirect(return_to, notice=notice)
                        return
                    if mode == "reveal":
                        target = f"/tasks/{quote(task_id, safe='')}#taskDeliveryWorkspace"
                        notice = "已在工作台中打开 NAS 文件夹。"
                    elif mode == "open":
                        preview = workbench.library_file_preview_payload(task_id, delivery, relative_path)
                        target = str((preview or {}).get("raw_url") or "")
                        if not target.startswith("/"):
                            raise ValueError("当前文件无法在浏览器中打开。")
                        notice = "已通过浏览器打开 NAS 文件。"
                    elif mode == "download":
                        target = "/api/library/raw?" + urlencode({
                            "task_id": task_id,
                            "delivery": delivery,
                            "path": relative_path,
                            "download": "1",
                        })
                        notice = "已开始从 NAS 下载到当前电脑。"
                    else:
                        raise ValueError("不支持的打开方式。")
                    self._redirect(target, notice=notice, client_redirect=True)
                    return
                if mode == "reveal":
                    command = ["/usr/bin/open", str(path)] if path.is_dir() else ["/usr/bin/open", "-R", str(path)]
                    notice = "已在 Finder 中显示。"
                elif mode == "open":
                    command = ["/usr/bin/open", str(path)]
                    notice = "已使用系统应用打开。"
                elif mode == "download":
                    downloaded = ember_transfer.download_delivery_file(form.get("task_id", ""), form.get("delivery", ""), form.get("path", ""))
                    command = ["/usr/bin/open", "-R", str(downloaded)]
                    notice = "已通过 rsync 下载到本机 Downloads/Ember。"
                else:
                    raise ValueError("不支持的打开方式。")
                subprocess.run(command, check=True, timeout=10)
                self._redirect(return_to, notice=notice)
                return
            if self.path == "/actions/create-task-from-deliveries":
                executor = normalize_executor(form.get("executor", "codex"))
                prompt = workbench.create_task_from_deliveries_prompt(parsed_form.get("selection", []))
                prompt = prompt_with_task_override(prompt, form)
                status = workbench.executor_status().get(executor, {})
                if not status.get("configured"):
                    raise ValueError("所选执行工具尚未配置成功。")
                dispatch = dispatch_executor(
                    executor, title="从交付物建立新任务", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(
                    return_to,
                    notice=f"{dispatch.notice} 请继续说明具体任务目标。",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            if self.path == "/actions/create-task-from-inputs":
                executor = normalize_executor(form.get("executor", "codex"))
                prompt = workbench.create_task_from_inputs_prompt(parsed_form.get("selection", []))
                prompt = prompt_with_task_override(prompt, form)
                status = workbench.executor_status().get(executor, {})
                if not status.get("configured"):
                    raise ValueError("所选执行工具尚未配置成功。")
                dispatch = dispatch_executor(
                    executor, title="用输入资料开始处理", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(
                    return_to,
                    notice=f"{dispatch.notice} 请继续说明具体处理目标。",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            if self.path == "/actions/revise-library-files":
                executor = normalize_executor(form.get("executor", "codex"))
                prompt = workbench.library_multi_revision_prompt(parsed_form.get("selection", []))
                prompt = prompt_with_task_override(prompt, form)
                status = workbench.executor_status().get(executor, {})
                if not status.get("configured"):
                    raise ValueError("所选执行工具尚未配置成功。")
                notice = dispatch_executor(
                    executor, title="交付文件二次处理", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(return_to, notice=notice)
                return
            if self.path == "/actions/open-source":
                source = workbench.allowed_source(form.get("kind", ""), form.get("identifier", ""))
                if not source:
                    raise ValueError("没有找到原始 Markdown 文件。")
                subprocess.run(["/usr/bin/open", str(source)], check=True)
                self._redirect(return_to, notice="已用默认应用打开原始 Markdown。")
                return
            if self.path == "/actions/continue-task":
                task_id = form.get("task_id", "")
                record = workbench.record_map().get(task_id)
                source = workbench.allowed_source("task", task_id)
                if not record or not source:
                    raise ValueError("没有找到对应任务卡。")
                executor = normalize_executor(form.get("executor", "codex"))
                status = workbench.executor_status().get(executor, {})
                if not status.get("configured"):
                    raise ValueError("所选执行工具尚未配置成功。")
                prompt = workbench.continuation_prompt(
                    record,
                    source,
                    parsed_form.get("selection", []),
                    form.get("create_new_task", "") == "1",
                )
                prompt = prompt_with_task_override(prompt, form)
                title = str(record.get("task_name") or record.get("title") or task_id)
                notice = dispatch_executor(
                    executor,
                    title=f"继续 · {title}",
                    prompt=prompt,
                    task_id=task_id,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(return_to, notice=notice)
                return
            if self.path == "/actions/continue-project":
                project = form.get("project", "")
                source = workbench.allowed_source("project", project)
                if not source:
                    raise ValueError("没有找到对应项目看板。")
                notice = dispatch_executor(
                    "codex",
                    title=f"继续项目 · {project}",
                    prompt=prompt_with_task_override(workbench.project_continuation_prompt(project, source), form),
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(return_to, notice=notice)
                return
            if self.path == "/actions/new-task":
                task_type = form.get("task_type", "")
                create_task_group = form.get("create_task_group", "") == "1"
                related_task_ids = parsed_form.get("related_task_id", [])
                records = workbench.record_map()
                if create_task_group:
                    task_type = "task_group"
                    if len(set(related_task_ids)) < 2:
                        raise ValueError("提炼任务主线至少需要选择两张普通任务卡。")
                    if any(records.get(task_id, {}).get("task_kind") == "task_group" for task_id in related_task_ids):
                        raise ValueError("任务主线不能嵌套，请只选择普通任务卡。")
                if task_type not in workbench.NEW_TASK_LABEL:
                    raise ValueError("不支持的新建任务类型。")
                project = form.get("project", "")
                if create_task_group and not project:
                    member_projects = {
                        str(records.get(task_id, {}).get("project") or "")
                        for task_id in related_task_ids
                    } - {""}
                    if len(member_projects) == 1:
                        project = member_projects.pop()
                source = new_task_project_source(project)
                executor = normalize_executor(form.get("executor", "codex"))
                status = workbench.executor_status().get(executor, {})
                valid_task_ids = set(records)
                if any(task_id not in valid_task_ids for task_id in related_task_ids):
                    raise ValueError("包含无效的关联任务卡。")
                delivery_mode = form.get("delivery_mode", "gate")
                if delivery_mode not in {"gate", "delivery", "none"}:
                    raise ValueError("不支持的交付模式。")
                prompt = workbench.new_task_prompt(task_type, project, source, delivery_mode, related_task_ids)
                prompt = prompt_with_task_override(prompt, form)
                label = workbench.NEW_TASK_LABEL[task_type]
                notice = dispatch_executor(
                    executor,
                    title=label,
                    prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(return_to, notice=notice)
                return
            if self.path == "/actions/route-task":
                route_mode = form.get("route_mode", "")
                request_text = form.get("request_text", "").strip()
                task_id = form.get("task_id", "").strip()
                user_supplement = form.get("user_supplement", "")
                if route_mode not in {"new", "continue", "derive"}:
                    raise ValueError("请选择有效的任务路由。")
                if not request_text:
                    raise ValueError("请描述本轮要求。")
                if route_mode in {"continue", "derive"} and not task_id:
                    raise ValueError("请先选择要继续或作为来源的任务。")
                executor = normalize_executor(form.get("executor", "codex"))
                copy_only = form.get("copy_only", "") == "1"
                staged_paths, extra_context = router_staged_context(
                    self.server.router_staging,
                    parsed_form.get("staged_file_id", []),
                    route_mode,
                )
                material_context = workbench.home_material_context(parsed_form.get("material_selection", [])) if parsed_form.get("material_selection") else []
                extra_context = [*extra_context, *material_context]
                if staged_paths and route_mode in {"continue", "derive"} and not copy_only:
                    for staged_path in staged_paths:
                        register_home_snapshot(task_id, staged_path)
                        shutil.rmtree(staged_path.parent, ignore_errors=True)
                        self.server.router_staging = {
                            key: value for key, value in self.server.router_staging.items()
                            if value != staged_path
                        }
                notice = route_task_prompt_action(
                    route_mode=route_mode,
                    request_text=request_text,
                    task_id=task_id,
                    user_supplement=user_supplement,
                    extra_context=extra_context,
                    executor=executor,
                    copy_only=copy_only,
                    target_machine=form.get("machine_id", ""),
                    task_override=form.get("task_override") if "task_override" in form else None,
                )
                self._redirect(return_to, notice=notice)
                return
            if self.path == "/actions/refresh-archive":
                project = form.get("project", "")
                job = self.server.schedule_archive_index_refresh(project)
                scope = "当前项目" if project else "全部项目"
                self._send_archive_result(
                    return_to=return_to,
                    notice=f"{scope}的目录索引已在后台串行刷新；当前页面继续使用已有索引。",
                    details={"job": job},
                    refresh=["directory"],
                    status=HTTPStatus.ACCEPTED,
                )
                return
            if self.path == "/actions/refresh-workspace-inbox":
                entries = workbench.refresh_workspace_inbox_entries()
                fixed_counts = {
                    str(entry.get("name") or ""): int(entry.get("child_count") or 0)
                    for entry in entries if entry.get("fixed")
                }
                count_text = "，".join(f"{name} {fixed_counts.get(name, 0)} 项" for name in workbench.WORKSPACE_INBOX_FOLDERS)
                self._redirect(return_to, notice=f"工作台目录已刷新：{count_text}。")
                return
            if self.path == "/actions/open-workspace-inbox":
                target = workbench.workspace_inbox_path(form.get("path", ""))
                if not target:
                    raise ValueError("当前来源路径不存在或未挂载。")
                subprocess.run(["/usr/bin/open", str(target)], check=True, timeout=10)
                self._redirect(return_to, notice="已在 Finder 打开当前资料来源。")
                return
            if self.path == "/actions/workspace-inbox-task":
                executor = normalize_executor(form.get("executor", ""))
                status = workbench.executor_status().get(executor, {})
                if not status.get("configured"):
                    raise ValueError("所选执行工具尚未配置成功。")
                action = form.get("inbox_action", "")
                prompt = workbench.workspace_inbox_task_prompt(action, parsed_form.get("source_path", []), parsed_form.get("archive_path", []))
                prompt = prompt_with_task_override(prompt, form)
                labels = {"organize_workspace":"整理工作台", "archive_selected":"归档选中内容", "organize_archive":"整理当前归档", "organize_baidu":"整理百度历史归档", "check_indexes":"检查归档备份", "publish_archive":"发布归档"}
                title = labels.get(action, "资料归档")
                if action in {"archive_selected", "publish_archive"}:
                    notice = dispatch_material_manager(
                        executor, mode="project_archive", title=title, prompt=prompt,
                        target_machine=form.get("machine_id", ""),
                    )
                else:
                    notice = dispatch_executor(
                        executor, title=title, prompt=prompt,
                        target_machine=form.get("machine_id", ""),
                    )
                self._redirect(return_to, notice=notice)
                return
            if self.path == "/actions/archive-item":
                executor = normalize_executor(form.get("executor", ""))
                status = workbench.executor_status().get(executor, {})
                if not status.get("configured"):
                    raise ValueError("所选执行工具尚未配置成功。")
                prompt = workbench.archive_item_prompt(form.get("project_name", ""), form.get("remote_path", ""), form.get("item_name", ""))
                prompt = prompt_with_task_override(prompt, form)
                notice = dispatch_material_manager(
                    executor, mode="project_archive", title=f"归档 · {form.get('item_name') or '项目'}", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(return_to, notice=notice)
                return
            if self.path == "/actions/open-archive-path":
                requested = form.get("path", "") or str(workbench.archive_index.config().get("display_root") or "")
                target = workbench.archive_open_target(requested)
                if not target or not target.is_dir():
                    raise ValueError("NAS 项目归档区不存在或未挂载。")
                subprocess.run(["/usr/bin/open", str(target)], check=True, timeout=10)
                self._redirect(return_to, notice="已在 Finder 打开 NAS 项目归档区。")
                return
            if self.path == "/actions/open-organization-center":
                target = workbench.ember_organization.ORGANIZATION_ROOT
                target.mkdir(parents=True, exist_ok=True)
                subprocess.run(["/usr/bin/open", str(target)], check=True, timeout=10)
                self._redirect(return_to, notice="已打开整理中心索引目录。")
                return
            if self.path == "/actions/create-task-group-from-selection":
                task_ids = parsed_form.get("selected_task_id", [])
                prompt = workbench.selected_tasks_task_group_prompt(task_ids)
                prompt = prompt_with_task_override(prompt, form)
                notice = dispatch_executor(
                    "codex", title=f"提炼任务主线 · {len(dict.fromkeys(task_ids))} 项", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(return_to, notice=notice)
                return
            if self.path == "/actions/organize-selected-tasks":
                executor = normalize_executor(form.get("executor", ""))
                status = workbench.executor_status().get(executor, {})
                if not status.get("configured"):
                    raise ValueError("所选执行工具尚未配置成功。")
                task_ids = parsed_form.get("selected_task_id", [])
                prompt = workbench.selected_tasks_organization_prompt(executor, task_ids)
                prompt = prompt_with_task_override(prompt, form)
                dispatch = dispatch_executor(
                    executor, title=f"按任务整理 · {len(dict.fromkeys(task_ids))} 项", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(
                    return_to,
                    notice=f"{dispatch.notice} 请在新任务中说明整理要求。",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            if self.path == "/actions/organization-start":
                executor = normalize_executor(form.get("executor", ""))
                mode = form.get("mode", "")
                scope = form.get("scope", "")
                prompt = workbench.organization_prompt(executor, mode, scope)
                prompt = prompt_with_task_override(prompt, form)
                label = workbench.ember_organization.MODE_LABELS.get(mode, "整理")
                title = f"{label} · {scope}" if scope else label
                dispatch = dispatch_executor(
                    executor, title=title, prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(
                    return_to,
                    notice=f"{dispatch.notice} 本轮将先建立普通整理任务卡并生成建议。",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            if self.path == "/actions/weekly-confirm":
                executor = normalize_executor(form.get("executor", ""))
                new_round = form.get("new_round", "0") == "1"
                project_name = form.get("project_name", "")
                if not workbench.valid_executor(executor):
                    raise ValueError("不支持的执行工具。")
                prompt = workbench.weekly_confirmation_prompt(executor, new_round=new_round, project_name=project_name)
                prompt = prompt_with_task_override(prompt, form)
                title = f"每周整理 · {project_name}" if project_name else "每周整理"
                dispatch = dispatch_executor(
                    executor, title=title, prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                scope = f"{project_name}项目" if project_name else "本周"
                self._redirect(
                    return_to,
                    notice=f"{scope}：{dispatch.notice} 请逐项确认后执行。",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            if self.path == "/actions/organize-project-intro":
                executor = normalize_executor(form.get("executor", ""))
                project_name = form.get("project", "")
                if not workbench.valid_executor(executor):
                    raise ValueError("不支持的执行工具。")
                if not project_name or project_name not in workbench.project_items():
                    raise ValueError("项目不存在。")
                prompt = workbench.organize_project_intro_prompt(executor, project_name)
                prompt = prompt_with_task_override(prompt, form)
                dispatch = dispatch_executor(
                    executor, title=f"整理项目介绍 · {project_name}", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(
                    return_to,
                    notice=f"{dispatch.notice} 请确认后让模型修改源文件并更新整理记录。",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            if self.path == "/actions/organize-project-intro-chat":
                executor = normalize_executor(form.get("executor", ""))
                project_name = form.get("project", "")
                user_input = form.get("user_input", "").strip()
                if not workbench.valid_executor(executor):
                    raise ValueError("不支持的执行工具。")
                if not project_name or project_name not in workbench.project_items():
                    raise ValueError("项目不存在。")
                if not user_input:
                    raise ValueError("请输入要补充或修改的信息。")
                prompt = workbench.organize_project_intro_chat_prompt(executor, project_name, user_input)
                prompt = prompt_with_task_override(prompt, form)
                dispatch = dispatch_executor(
                    executor, title=f"对话补充项目介绍 · {project_name}", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(
                    return_to,
                    notice=f"{dispatch.notice} 请确认后让模型修改源文件并更新整理记录。",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            if self.path == "/actions/maintain-project-intro":
                executor = normalize_executor(form.get("executor", ""))
                project_name = form.get("project", "")
                user_input = form.get("user_input", "").strip()
                if not workbench.valid_executor(executor):
                    raise ValueError("不支持的执行工具。")
                if not project_name or project_name not in workbench.project_items():
                    raise ValueError("项目不存在。")
                prompt = workbench.maintain_project_intro_prompt(project_name, user_input)
                prompt = prompt_with_task_override(prompt, form)
                dispatch = dispatch_executor(
                    executor, title=f"维护项目介绍 · {project_name}", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                self._redirect(
                    return_to,
                    notice=f"{dispatch.notice} 请确认后让模型修改源文件并更新整理记录。",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            if self.path == "/actions/open-project-board":
                project_name = form.get("project", "")
                if not project_name or project_name not in workbench.project_items():
                    raise ValueError("项目不存在。")
                board_path = workbench.PROJECT_BOARD_ROOT / project_name
                if not board_path.exists():
                    raise ValueError("项目工作文件夹不存在。")
                subprocess.run(["/usr/bin/open", str(board_path)], check=True)
                self._redirect(return_to, notice=f"已在 Finder 打开 {project_name} 项目工作文件夹。")
                return
            if self.path == "/actions/open-project-knowledge":
                project_name = form.get("project", "")
                target = workbench.project_description_source(project_name)
                if not target:
                    raise ValueError("余烬 · Ember 共享项目说明不存在或当前机器不可读。")
                subprocess.run(["/usr/bin/open", str(target)], check=True, timeout=10)
                self._redirect(return_to, notice=f"已打开 {project_name} 的 余烬 · Ember 项目说明。")
                return
            if self.path == "/actions/open-project-entry":
                project_name = form.get("project", "")
                entry = form.get("entry", "")
                target = workbench.project_entry_target(project_name, entry)
                if not target:
                    raise ValueError("项目入口不存在或当前机器不可用。")
                subprocess.run(["/usr/bin/open", target[1]], check=True, timeout=10)
                self._redirect(return_to, notice=f"已打开 {project_name} 的 {entry} 入口。")
                return
            if self.path == "/actions/open-kimi-archive":
                project_name = form.get("project_name", "")
                prompt = ember_kimi.archive_prompt(project_name)
                dispatch = dispatch_executor(
                    "opencode", title=f"整理项目目录 · {project_name or '全部'}", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                scope = project_name or "全部项目"
                self._redirect(
                    return_to,
                    notice=f"{scope}：{dispatch.notice}",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            if self.path in {"/actions/organize-archive-project", "/actions/open-archive-detection"}:
                project_name = form.get("project_name", "")
                executor = normalize_executor(form.get("executor", ""))
                if not workbench.valid_executor(executor):
                    raise ValueError("不支持的执行工具。")
                if not workbench.executor_status().get(executor, {}).get("configured"):
                    raise ValueError("所选执行工具尚未配置成功。")
                prompt = ember_kimi.archive_prompt(project_name)
                dispatch = dispatch_executor(
                    executor, title=f"整理项目目录 · {project_name or '全部'}", prompt=prompt,
                    target_machine=form.get("machine_id", ""),
                )
                scope = project_name or "全部项目"
                self._redirect(
                    return_to,
                    notice=f"{scope}：{dispatch.notice}",
                    clipboard_text=dispatch.clipboard_text,
                )
                return
            self._send("unknown action", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
        except (
            ValueError,
            OSError,
            subprocess.SubprocessError,
            archive_index.ArchiveIndexError,
            ember_kimi.KimiIntegrationError,
            ember_opencode.OpenCodeIntegrationError,
        ) as exc:
            if self._wants_json():
                self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
                return
            self._redirect(return_to, error=str(exc))

    def do_PUT(self) -> None:
        if not self._valid_host():
            self._send("invalid host", HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8")
            return
        parsed = urlsplit(self.path)
        if not self._authorized(parsed.path):
            return
        prefix = "/api/bridge/tasks/"
        marker = "/draft/"
        if not parsed.path.startswith(prefix) or marker not in parsed.path:
            self._send_json({"error": "unknown remote write endpoint"}, HTTPStatus.NOT_FOUND)
            return
        remainder = parsed.path[len(prefix):]
        task_id, relative_path = remainder.split(marker, 1)
        task_id, relative_path = unquote(task_id), unquote(relative_path)
        length = int(self.headers.get("Content-Length", "0") or 0)
        maximum = int(ember_env("EMBER_REMOTE_WRITE_MAX_BYTES", str(256 * 1024 * 1024)))
        if length < 0 or length > maximum:
            self._send_json({"error": "invalid remote write size"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            result = central_store.write_draft(
                task_id,
                relative_path,
                self.rfile.read(length),
                expected_sha256=self.headers.get("X-Ember-Base-SHA256", ""),
            )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        self._send_json(result)


def main() -> int:
    from ..application import Application
    from ..deployment import current_deployment
    Application(current_deployment().profile).serve(int(workbench.config().get("port", 8765)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
