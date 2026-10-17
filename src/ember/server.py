"""Loopback workspace APIs and explicitly confirmed, saved-software opening."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import stat
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__
from .store import WorkspaceError, preview_kind
from .executors import ExecutorRegistry
import subprocess
import sys

WEB = Path(__file__).resolve().parent / "web"
# The shared interface layer's stylesheets and scripts, served at /ember_ui/<name>.
SHARED_STATIC = Path(__file__).resolve().parent / "ember_ui" / "static"
MAX_BODY = 1_048_576
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
       "font-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; "
       "base-uri 'self'; form-action 'none'; frame-ancestors 'none'")


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, workspace, port=8783, *, executor_registry=None):
        self.workspace = workspace
        self.executor_registry = executor_registry or ExecutorRegistry()
        self.csrf_token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "Ember/" + __version__

    def log_message(self, *_):
        pass  # Do not retain task content or visitor requests in access logs.

    def end_headers(self):
        csp = CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'") if getattr(self, "framable", False) else CSP
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        super().end_headers()

    def send(self, status, data, content_type="application/json; charset=utf-8", attachment=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if attachment is not None:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(attachment))
        self.end_headers()
        self.wfile.write(data)

    def json(self, result, status=200):
        self.send(status, {"ok": True, "data": result})

    def error(self, message, status=400):
        self.send(status, {"ok": False, "error": message})

    def local_request(self):
        port = self.server.server_port
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "").lower() not in allowed_hosts:
            raise WorkspaceError("仅允许本机地址访问", 403)
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + h for h in allowed_hosts}:
            raise WorkspaceError("跨来源请求不受支持", 403)

    def do_GET(self):
        self.framable = False
        try:
            self.local_request()
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            if path == "/api/state":
                result = self.server.workspace.snapshot()
                result["csrf_token"] = self.server.csrf_token
                self.json(result)
            elif path == "/api/health":
                from .bootstrap import verify_workspace_contract
                contract = verify_workspace_contract(self.server.workspace)
                state = self.server.workspace.snapshot()
                self.json({"status": "ready", "version": __version__, "tasks": len(state["tasks"]), "contract": contract})
            elif path == "/api/settings":
                self.json({"execution_environment": self.server.executor_registry.snapshot(), "skills": self.registered_skills()})
            elif path == "/api/pages/settings":
                from .pages import render_settings
                self.json({"html": render_settings(self.registered_skills())})
            elif path == "/api/pages/task":
                # Server-rendered with the shared template; app.js inserts it and wires the materials.
                from .pages import render_task
                markup = render_task(self.server.workspace.snapshot(), query.get("id", [""])[0])
                if markup is None:
                    raise WorkspaceError("该任务不在当前工作区。", 404)
                self.json({"html": markup})
            elif path == "/api/pages/home":
                from .pages import render_home
                self.json({"html": render_home(self.server.workspace.snapshot())})
            elif path == "/api/pages/project":
                from .pages import render_project
                page = render_project(self.server.workspace.snapshot(), query.get("id", [""])[0])
                if page is None:
                    raise WorkspaceError("该项目不在当前工作区。", 404)
                self.json(page)
            elif path == "/api/pages/library":
                from .pages import render_library
                self.json({"html": render_library(self.server.workspace.snapshot())})
            elif path == "/api/pages/review":
                from .pages import render_review
                self.json({"html": render_review(self.server.workspace.snapshot())})
            elif path == "/api/review/search":
                from .pages import review_search
                self.json(review_search(self.server.workspace.snapshot(), query.get("q", [""])[0], query.get("project", [""])[0],
                                        query.get("type", [""])[0], query.get("status", [""])[0]))
            elif path == "/api/review/report-preview":
                from .pages import report_preview
                result = report_preview(self.server.workspace.snapshot(), query.get("id", [""])[0])
                if result is None:
                    raise WorkspaceError("该整理报告不在当前工作区。", 404)
                self.json(result)
            elif path == "/api/home/search":
                from .pages import home_search
                self.json(home_search(self.server.workspace.snapshot(), query.get("q", [""])[0]))
            elif path == "/api/home/task-preview":
                from .pages import task_preview
                result = task_preview(self.server.workspace.snapshot(), query.get("id", [""])[0])
                if result is None:
                    raise WorkspaceError("该任务不在当前工作区。", 404)
                self.json(result)
            elif path == "/api/home/file-preview":
                from .pages import file_preview
                self.json(file_preview(self.server.workspace.read_file(query.get("id", [""])[0])))
            elif path == "/api/update":
                # Only on the user's click; the result says what is available, it installs nothing.
                from .updates import check_update
                self.json(check_update(self.server.workspace))
            elif path == "/api/preview":
                file, _ = self.server.workspace.raw_file(query.get("id", [""])[0])
                if not preview_kind(file):
                    raise WorkspaceError("这类文件不在页面中预览，请下载或用系统应用打开。", 415)
                with os.fdopen(os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise WorkspaceError("仅支持普通文件预览")
                    self.framable = True  # PDFs render in a same-origin frame on the task page.
                    self.send(200, stream.read(), mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            elif path in {"/api/file", "/api/raw"}:
                file_id = query.get("id", [""])[0]
                if path == "/api/file":
                    self.json(self.server.workspace.read_file(file_id))
                else:
                    file, meta = self.server.workspace.raw_file(file_id)
                    # Downloads are always attachments, including HTML/SVG/scripts.
                    with os.fdopen(os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as stream:
                        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                            raise WorkspaceError("仅支持普通文件下载")
                        self.send(200, stream.read(), "application/octet-stream", file.name)
            elif path.startswith("/api/"):
                self.error("接口不存在", 404)
            else:
                self.static(path)
        except WorkspaceError as error:
            self.error(str(error), getattr(error, "status", 400))
        except (OSError, ValueError) as error:
            self.error("工作区或资源不可读取：" + str(error), 400)

    def registered_skills(self):
        """The workspace's basic Skills as registered in its manifest; registration is not proof they can run."""
        from .bootstrap import verify_workspace_contract
        verify_workspace_contract(self.server.workspace)
        records = [item for item in self.server.workspace._json("skills/manifest.json").get("skills", [])
                   if isinstance(item, dict) and item.get("name") in {"ember-init", "ember", "ember-project"}
                   and item.get("path") == f".agents/skills/{item['name']}/SKILL.md"]
        return [{"name": item["name"], "version": item.get("version", "未登记版本"), "purpose": item.get("purpose", ""), "registered": True} for item in records]

    def static(self, path):
        if path == "/":
            path = "/index.html"
        relative = Path(path.lstrip("/"))
        if any(part in {"..", "."} or part.startswith(".") for part in relative.parts) or "\\" in path:
            raise WorkspaceError("资源路径无效", 404)
        allowed = path in {"/index.html", "/app.js", "/app.css"} or path.startswith(("/assets/", "/fonts/", "/ember_ui/"))
        base = WEB
        if relative.parts[:1] == ("ember_ui",):
            base, relative = SHARED_STATIC, Path(*relative.parts[1:])
        target = base / relative
        if not allowed or not relative.parts or not target.resolve().is_relative_to(base.resolve()):
            raise WorkspaceError("资源不存在", 404)
        if target.is_symlink() or not target.is_file():
            raise WorkspaceError("资源不存在", 404)
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or target.suffix == ".js":
            content_type += "; charset=utf-8"
        self.send(200, target.read_bytes(), content_type)

    def do_POST(self):
        try:
            self.local_request()
            if not secrets.compare_digest(self.headers.get("X-Ember-Token", ""), self.server.csrf_token):
                raise WorkspaceError("请求凭据无效，请刷新页面", 403)
            if self.headers.get_content_type() != "application/json":
                raise WorkspaceError("请求必须为 JSON", 415)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise WorkspaceError("请求为空或超过 1 MiB", 413)
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise WorkspaceError("请求必须为 JSON 对象")
            path = unquote(urlsplit(self.path).path)
            w = self.server.workspace
            routes = {
                "/api/projects": w.create_project,
                "/api/tasks": w.create_task,
                "/api/inbox/label": w.set_inbox_label,
                "/api/context": w.build_context,
                "/api/review/context": w.build_review_context,
                "/api/reports": w.save_report,
                "/api/executors/check": self.server.executor_registry.validate,
                "/api/executors/save": self.server.executor_registry.save,
            }
            if path in routes:
                result = routes[path](payload)
            elif path == "/api/executors/discover":
                if payload:
                    raise WorkspaceError("查找只使用受限的本机安装目录，不接受自定义扫描参数。")
                result = self.server.executor_registry.discover()
            elif path == "/api/reveal":
                mode = payload.pop("mode", "reveal")
                result = reveal(w.locate(payload), mode)
            elif path == "/api/executors/open":
                result = self.server.executor_registry.open_software(payload, w.path)
            elif path == "/api/onboarding/remove-init-skill":
                from .onboarding_completion import remove_init_skill
                result = remove_init_skill(w, payload)
            elif path.startswith("/api/tasks/"):
                parts = path.split("/")[3:]
                task_id = parts[0]
                if not task_id or "/" in task_id or len(parts) > 2:
                    raise WorkspaceError("任务路径无效", 404)
                if len(parts) == 1:
                    result = w.update_task(task_id, payload)
                else:
                    methods = {"materials": w.add_material, "references": w.add_reference,
                               "promote": w.promote_task, "complete": w.complete_task, "important": w.set_important}
                    if parts[1] not in methods:
                        raise WorkspaceError("接口不存在", 404)
                    result = methods[parts[1]](task_id, payload)
            else:
                raise WorkspaceError("接口不存在", 404)
            self.json(result)
        except WorkspaceError as error:
            self.error(str(error), getattr(error, "status", 400))
        except (ValueError, UnicodeError):
            self.error("请求 JSON 无效")
        except OSError:
            self.error("写入失败，原数据已保留，请检查工作区权限", 500)


def reveal(target: Path, mode: str = "reveal") -> dict:
    """Show a workspace file or folder in Finder, or open a file with its default application.

    The target is always resolved by the workspace from an indexed material or task folder;
    no request-provided path or command reaches the system.
    """
    if mode not in ("reveal", "open"):
        raise WorkspaceError("mode 必须为 reveal 或 open。")
    if sys.platform == "darwin":
        argv = ["/usr/bin/open", "-R", str(target)] if mode == "reveal" and target.is_file() else ["/usr/bin/open", str(target)]
    elif sys.platform.startswith("linux"):
        argv = ["xdg-open", str(target.parent if mode == "reveal" and target.is_file() else target)]
    else:
        raise WorkspaceError("当前系统不支持在文件管理器中打开。")
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WorkspaceError(f"没能打开：{error}") from None
    if result.returncode:
        raise WorkspaceError(f"没能打开：{(result.stderr or result.stdout).strip()[:300] or f'退出码 {result.returncode}'}")
    return {"opened": target.name, "mode": mode}


@contextmanager
def workspace_lock(workspace):
    """Prevent two local service processes from writing the same workspace."""
    try:
        import fcntl
    except ImportError as error:
        raise WorkspaceError("服务目前支持 macOS 与 Linux") from error
    path = workspace._safe(".ember/service.lock")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise WorkspaceError("工作区锁必须为普通文件")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WorkspaceError("该工作区已有服务运行，请停止原服务后再启动", 409) from error
        yield
    finally:
        os.close(fd)


def run(workspace, port=8783):
    with workspace_lock(workspace):
        server = LocalServer(workspace, port)
        print(f"Ember {__version__} · http://127.0.0.1:{server.server_port}/", flush=True)
        print("仅本机访问；按 Ctrl+C 停止。", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
