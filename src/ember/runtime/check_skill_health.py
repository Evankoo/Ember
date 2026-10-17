#!/usr/bin/env python3
"""Machine-local health snapshot for registered GStudio Skills."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from . import workspace_paths

ROOT = _deployment_root()
MANIFEST_PATH = ROOT / "skills" / "manifest.json"
EXECUTION_REGISTRY_PATH = ROOT / "config" / "mcp-integrations" / "registry.json"
SNAPSHOT_PATH = Path(
    os.environ.get("GSTUDIO_SKILL_HEALTH_PATH")
    or workspace_paths.local_config_root() / "skill-health.json"
).expanduser()


def _now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _path_exists(value: str) -> bool:
    return Path(value).expanduser().exists()


def _configured(name: str, env_files: tuple[Path, ...] = ()) -> bool:
    if os.environ.get(name):
        return True
    prefix = f"{name}="
    for path in env_files:
        try:
            if any(line.strip().startswith(prefix) for line in path.read_text(encoding="utf-8").splitlines()):
                return True
        except (FileNotFoundError, OSError, UnicodeError):
            continue
    return False


def _service(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def _codex_mcp_configured(*names: str) -> bool:
    path = Path.home() / ".codex" / "config.toml"
    try:
        text = path.read_text(encoding="utf-8").lower()
    except (FileNotFoundError, OSError, UnicodeError):
        return False
    return any(name.lower() in text for name in names)


def _result(status: str, missing: list[str] | None = None, note: str = "") -> dict[str, object]:
    return {"status": status, "missing": missing or [], "note": note}


def _node_major_version() -> int | None:
    if not shutil.which("node"):
        return None
    try:
        completed = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
        value = (completed.stdout or completed.stderr).strip().lstrip("v")
        return int(value.split(".", 1)[0]) if completed.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _lark_cli_status() -> dict[str, object]:
    if not shutil.which("lark-cli"):
        return _result("unavailable", ["lark-cli"])
    env = {
        **os.environ,
        "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
        "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
    }
    try:
        completed = subprocess.run(
            ["lark-cli", "auth", "status", "--json", "--verify"],
            capture_output=True,
            check=False,
            env=env,
            text=True,
            timeout=10,
        )
        payload = json.loads(completed.stdout or completed.stderr)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return _result("conditional", ["lark-cli authentication status"], "无法验证本机飞书登录状态。")
    user = ((payload.get("identities") or {}).get("user") or {}) if isinstance(payload, dict) else {}
    if completed.returncode == 0 and user.get("status") == "ready" and user.get("verified") is True:
        return _result("available")
    bot = ((payload.get("identities") or {}).get("bot") or {}) if isinstance(payload, dict) else {}
    if completed.returncode == 0 and bot.get("status") == "ready" and bot.get("verified") is True:
        return _result("conditional", ["lark-cli user authentication"], "bot 身份可用；个人飞书资源需要用户登录。")
    return _result("unavailable", ["lark-cli configuration/authentication"])


def profile_status(profile: str) -> dict[str, object]:
    """Resolve one declared health profile without exposing secret values."""
    if profile == "always":
        return _result("available")
    if profile == "bdpan":
        return _result("available" if shutil.which("bdpan") else "unavailable", [] if shutil.which("bdpan") else ["bdpan CLI"])
    if profile == "bypy":
        return _result("available" if shutil.which("bypy") else "unavailable", [] if shutil.which("bypy") else ["bypy CLI"])
    if profile == "anydoc-cli":
        missing = []
        node_major = _node_major_version()
        if node_major is None:
            missing.append("Node.js 20+")
        elif node_major < 20:
            missing.append(f"Node.js 20+ (found {node_major})")
        if not shutil.which("npx"):
            missing.append("npx")
        return _result(
            "available" if not missing else "unavailable",
            missing,
            "首次转换会从 npm 获取固定版本 @firecrawl/anydoc@0.1.6。" if not missing else "",
        )
    if profile == "alist-rclone":
        missing = []
        if not shutil.which("rclone"):
            missing.append("rclone CLI")
        if not _service("127.0.0.1", 5244):
            missing.append("AList service")
        return _result("available" if not missing else "unavailable", missing)
    if profile == "gstudio-task-bridge":
        script = Path(__file__).with_name("gstudio_mcp_server.py")
        return _result("available" if script.is_file() else "unavailable", [] if script.is_file() else ["GStudio MCP server"])
    if profile == "justoneapi-mcp":
        ok = _codex_mcp_configured("justoneapi")
        return _result("available" if ok else "unavailable", [] if ok else ["JustOneAPI MCP connection"])
    if profile == "tikhub-mcp":
        ok = _codex_mcp_configured("tikhub-xiaohongshu", "tikhub-douyin")
        return _result("available" if ok else "unavailable", [] if ok else ["TikHub MCP connection"])
    if profile == "lark-cli":
        return _lark_cli_status()
    if profile == "social-providers":
        ok = _codex_mcp_configured("justoneapi", "tikhub")
        return _result("available" if ok else "conditional", [] if ok else ["JustOneAPI/TikHub MCP"], "浏览器或手工导入仍可作为兜底。")
    if profile == "imagegen":
        return _result("conditional", note="由当前执行器提供 imagegen；本机脚本无法独立验证。")
    if profile == "artifact-node":
        base = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies"
        missing = []
        if not (base / "node" / "bin" / "node").exists():
            missing.append("Codex bundled Node")
        if not (base / "node" / "node_modules").exists():
            missing.append("@oai/artifact-tool runtime")
        return _result("available" if not missing else "unavailable", missing)
    if profile == "video-download":
        ok = (ROOT / "skills" / "video-downloader" / "scripts" / "video_downloader.py").exists()
        return _result("available" if ok else "unavailable", [] if ok else ["video_downloader.py"])
    return _result("conditional", [f"未知健康配置：{profile}"])


def collect_health() -> dict[str, object]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    try:
        registry = json.loads(EXECUTION_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        registry = {}
    profile_names = {
        str(skill.get("health_profile") or "always")
        for skill in manifest.get("skills", [])
        if isinstance(skill, dict)
    }
    for key in ("mcp_integrations", "tool_integrations"):
        values = registry.get(key) if isinstance(registry, dict) else None
        if not isinstance(values, list):
            continue
        profile_names.update(
            str(item.get("health_profile") or "always")
            for item in values
            if isinstance(item, dict)
        )
    profiles = {
        profile: profile_status(profile)
        for profile in sorted(profile_names)
    }
    entries: dict[str, dict[str, object]] = {}
    for skill in manifest.get("skills", []):
        name = str(skill.get("name") or "")
        if not name:
            continue
        profile = str(skill.get("health_profile") or "always")
        entries[name] = {
            "skill": name,
            "health_profile": profile,
            **profiles[profile],
        }
    return {
        "schema_version": 2,
        "machine": os.environ.get("GSTUDIO_MACHINE") or os.uname().nodename,
        "checked_at": _now().isoformat(timespec="seconds"),
        "entries": entries,
        "profiles": profiles,
    }


def write_snapshot(payload: dict[str, object]) -> Path:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return SNAPSHOT_PATH


def read_snapshot(max_age_seconds: int = 900) -> dict[str, object]:
    """Read the last local snapshot without probing or writing anything."""
    try:
        payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("snapshot must be an object")
        checked = dt.datetime.fromisoformat(str(payload.get("checked_at") or ""))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
        state = "fresh" if (_now() - checked).total_seconds() <= max_age_seconds else "stale"
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {
            "schema_version": 2,
            "checked_at": "",
            "entries": {},
            "profiles": {},
            "snapshot_state": "missing",
        }
    return {**payload, "snapshot_state": state}


def load_snapshot(max_age_seconds: int = 900) -> dict[str, object]:
    """Compatibility loader that refreshes stale snapshots for explicit callers."""
    payload = read_snapshot(max_age_seconds=max_age_seconds)
    if payload.get("snapshot_state") == "fresh":
        return payload
    payload = collect_health()
    write_snapshot(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Check machine-local GStudio Skill health")
    parser.add_argument("--json", action="store_true", help="Print the full JSON snapshot")
    parser.add_argument("--write", action="store_true", help=f"Write {SNAPSHOT_PATH}")
    args = parser.parse_args()
    payload = collect_health()
    if args.write:
        write_snapshot(payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        counts = {status: sum(1 for item in payload["entries"].values() if item["status"] == status) for status in ("available", "conditional", "unavailable")}
        print(f"GStudio Skill health: {counts['available']} available, {counts['conditional']} conditional, {counts['unavailable']} unavailable")
        print(f"- checked_at: {payload['checked_at']}")
        if args.write:
            print(f"- snapshot: {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
