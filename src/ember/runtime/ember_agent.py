#!/usr/bin/env python3
"""Manage Ember runtime Agents, executor adapters, and shared run records."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .time_format import now_iso_string
from .workspace_paths import shared_workspace_root


ROOT = _deployment_root()
REGISTRY = ROOT / "config" / "agents.json"
SKILL_MANIFEST = ROOT / "skills" / "manifest.json"
LEDGER_RELATIVE = Path("管理中心") / "运行状态" / "Agent记录" / "agent-runs.json"
LEDGER_VERSION = 1
ALLOWED_STATES = {"running", "completed", "needs_input", "failed", "needs_configuration", "expired"}
ALLOWED_MODES = {"file_management", "project_archive", "ebrain_raw_registration", "task_organization"}
ALLOWED_EXECUTORS = {"codex", "opencode", "hermes"}
REASONING_LEVELS = {"low", "medium", "high", "xhigh", "max"}
TECHNICAL_FALLBACK_REASONS = {
    "rate_limit", "timeout", "service_unavailable", "authentication", "quota"
}
RUN_AUTHORIZATION_MAX_AGE = timedelta(hours=6)


class AgentError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentError(f"cannot read JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AgentError(f"JSON root must be an object: {path}")
    return value


def registry() -> dict[str, object]:
    return _read_json(REGISTRY)


def agent_registry_entry(agent_id: str) -> dict[str, object]:
    agents = registry().get("runtime_agents")
    value = agents.get(agent_id) if isinstance(agents, dict) else None
    if not isinstance(value, dict):
        raise AgentError(f"unknown runtime Agent: {agent_id}")
    return value


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentError(f"cannot read Agent manifest: {path}: {exc}") from exc
    if not text.startswith("---\n"):
        raise AgentError(f"Agent manifest is missing frontmatter: {path}")
    try:
        raw, body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise AgentError(f"Agent frontmatter is not closed: {path}") from exc
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise AgentError(f"invalid Agent frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"')
    return values, body


def agent_manifest_path(agent_id: str) -> Path:
    entry = agent_registry_entry(agent_id)
    value = str(entry.get("manifest") or "")
    path = (ROOT / value).resolve()
    if ROOT.resolve() not in path.parents:
        raise AgentError(f"Agent manifest escapes Ember root: {value}")
    return path


def agent_definition(agent_id: str) -> tuple[dict[str, str], str]:
    return parse_frontmatter(agent_manifest_path(agent_id))


def executor_model_policy(values: dict[str, str], executor: str) -> dict[str, str]:
    policy = dict(values)
    if executor == "opencode":
        for key in ("primary_provider", "primary_model"):
            policy[key] = values.get(f"opencode_{key}", values[key])
    return policy


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _adapter_paths(agent_id: str) -> dict[str, list[Path]]:
    entry = agent_registry_entry(agent_id)
    raw = entry.get("adapter_files")
    result: dict[str, list[Path]] = {}
    if not isinstance(raw, dict):
        return result
    for executor, paths in raw.items():
        if isinstance(paths, list):
            result[str(executor)] = [(ROOT / str(path)).resolve() for path in paths]
    return result


def _available_local_skills() -> set[str]:
    manifest = _read_json(SKILL_MANIFEST)
    return {
        str(item.get("name"))
        for item in manifest.get("skills", [])
        if isinstance(item, dict) and item.get("name")
    }


def validate_agent(agent_id: str) -> list[str]:
    errors: list[str] = []
    path = agent_manifest_path(agent_id)
    try:
        values, body = parse_frontmatter(path)
    except AgentError as exc:
        return [str(exc)]

    required = {
        "type", "agent_id", "display_name", "version", "status", "residency",
        "description", "primary_provider", "primary_model", "primary_reasoning",
        "fallback_provider", "fallback_model", "fallback_reasoning", "local_skills",
        "external_skills", "adapters",
    }
    for key in sorted(required - values.keys()):
        errors.append(f"Agent manifest missing {key}: {path}")
    if values.get("type") != "ember_runtime_agent":
        errors.append("Agent type must be ember_runtime_agent")
    if values.get("agent_id") != agent_id or path.parent.name != agent_id:
        errors.append("Agent id must match registry id and directory name")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", agent_id):
        errors.append("Agent id must be lowercase kebab-case")
    if values.get("residency") not in {"on_demand", "queue_watcher", "persistent"}:
        errors.append("Agent residency is invalid")
    if values.get("status") not in {"active", "disabled", "proposed"}:
        errors.append("Agent status is invalid")
    for key in ("primary_reasoning", "fallback_reasoning"):
        if values.get(key) not in REASONING_LEVELS:
            errors.append(f"Agent {key} is invalid")
    mode_reasoning = _mode_reasoning_map(values.get("mode_reasoning", ""))
    for mode, reasoning in mode_reasoning.items():
        if mode not in ALLOWED_MODES:
            errors.append(f"Agent mode_reasoning references unknown mode: {mode}")
        if reasoning not in REASONING_LEVELS:
            errors.append(f"Agent mode_reasoning has invalid reasoning: {mode}={reasoning}")

    local_skills = _csv(values.get("local_skills", ""))
    known_skills = _available_local_skills()
    for skill in local_skills:
        if skill not in known_skills:
            errors.append(f"Agent references unknown Ember Skill: {skill}")

    external_skills = _csv(values.get("external_skills", ""))
    if "ebrain:ebrain-in" in external_skills:
        source = Path.home() / "Ebrain" / "skills" / "ebrain-in" / "SKILL.md"
        if not source.is_file():
            errors.append(f"EBrain external Skill is unavailable: {source}")
        for duplicate in (ROOT / "skills" / "ebrain-in", ROOT / ".agents" / "skills" / "ebrain-in"):
            if duplicate.exists() or duplicate.is_symlink():
                errors.append(f"EBrain external Skill must not be registered in Ember: {duplicate}")
    if "ebrain:ebrain-source" in external_skills:
        errors.append("material-manager must not depend on ebrain-source")

    sections = [
        "## Contract", "## Responsibilities", "## Routing", "## Permissions",
        "## Model Policy", "## Input And Output", "## Verification",
        "## Executor Adapters", "## Security",
    ]
    for section in sections:
        if section not in body:
            errors.append(f"Agent manifest missing section: {section}")

    adapters = _adapter_paths(agent_id)
    for executor in _csv(values.get("adapters", "")):
        paths = adapters.get(executor, [])
        if not paths:
            errors.append(f"Agent registry has no {executor} adapter")
        for adapter in paths:
            if not adapter.is_file():
                errors.append(f"Agent adapter is missing: {adapter}")
                continue
            text = adapter.read_text(encoding="utf-8")
            if executor != "hermes" and "agents/material-manager/AGENT.md" not in text:
                errors.append(f"Agent adapter does not reference canonical manifest: {adapter}")

    expected = {
        "gpt-5.6-luna": values.get("primary_model"),
        "deepseek-v4-flash": values.get("fallback_model"),
    }
    for model, configured in expected.items():
        if configured != model:
            errors.append(f"Agent model policy mismatch: expected {model}, got {configured}")
    for key, expected_value in {
        "opencode_primary_provider": "opencode-go",
        "opencode_primary_model": "glm-5.3-flash",
    }.items():
        if values.get(key) != expected_value:
            errors.append(f"Agent OpenCode policy mismatch: {key}")
    opencode_policy = executor_model_policy(values, "opencode")
    for adapter in adapters.get("opencode", []):
        if adapter.is_file() and "luna" in adapter.name:
            adapter_values, adapter_body = parse_frontmatter(adapter)
            model_id = f"{opencode_policy['primary_provider']}/{opencode_policy['primary_model']}"
            if adapter_values.get("model") != model_id or f"`{opencode_policy['primary_model']}`" not in adapter_body:
                errors.append(f"OpenCode primary adapter model differs from canonical policy: {adapter}")
    for paths in adapters.values():
        for adapter in paths:
            if adapter.is_file() and adapter.suffix in {".toml", ".md", ".yaml"}:
                text = adapter.read_text(encoding="utf-8")
                if ("luna" in adapter.name or executor_model_hint(adapter) == "primary") and "high" not in text:
                    errors.append(f"primary adapter does not pin high reasoning: {adapter}")
                if "deepseek" in adapter.name and "high" not in text:
                    errors.append(f"fallback adapter does not pin high reasoning: {adapter}")
    return errors


def executor_model_hint(path: Path) -> str:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return "primary" if "gpt-5.6-luna" in text else "fallback" if "deepseek-v4-flash" in text else ""


def _mode_reasoning_map(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _csv(raw):
        if "=" not in item:
            continue
        mode, reasoning = (part.strip() for part in item.split("=", 1))
        if mode and reasoning:
            result[mode] = reasoning
    return result


def reasoning_for_mode(values: dict[str, str], mode: str) -> str:
    return _mode_reasoning_map(values.get("mode_reasoning", "")).get(
        mode,
        values["primary_reasoning"],
    )


def _command_path(name: str, fallbacks: list[Path]) -> str:
    found = shutil.which(name)
    if found:
        return found
    return next((str(path) for path in fallbacks if path.is_file()), "")


def _run_text(command: list[str], timeout: int = 15) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or "") + (result.stderr or "")


def executor_status(agent_id: str) -> dict[str, object]:
    values, _ = agent_definition(agent_id)
    adapters = _adapter_paths(agent_id)

    codex = _command_path("codex", [Path("/Applications/ChatGPT.app/Contents/Resources/codex")])
    codex_ready = bool(codex and all(path.is_file() for path in adapters.get("codex", [])))

    opencode = _command_path("opencode", [Path.home() / ".opencode" / "bin" / "opencode"])
    opencode_auth = _run_text([opencode, "auth", "list"]) if opencode else ""
    opencode_policy = executor_model_policy(values, "opencode")
    opencode_models = _run_text([opencode, "models", opencode_policy["primary_provider"]], timeout=25) if opencode else ""
    opencode_model_id = f"{opencode_policy['primary_provider']}/{opencode_policy['primary_model']}"
    opencode_primary = opencode_model_id in opencode_models.splitlines() and "OpenCode Go" in opencode_auth
    opencode_fallback = "DeepSeek" in opencode_auth or bool(os.environ.get("DEEPSEEK_API_KEY"))

    hermes = _command_path("hermes", [Path.home() / ".local" / "bin" / "hermes"])
    profile = Path.home() / ".hermes" / "profiles" / agent_id
    managed = profile / ".ember-agent.json"
    hermes_auth = _run_text([hermes, "auth", "list"]) if hermes else ""
    hermes_primary = "openai-codex" in hermes_auth
    hermes_fallback = "deepseek" in hermes_auth.lower() or bool(os.environ.get("DEEPSEEK_API_KEY"))

    return {
        "codex": {
            "installed": codex_ready,
            "state": "available" if codex_ready else "unavailable",
            "primary_ready": codex_ready,
            "fallback_ready": codex_ready and bool(os.environ.get("DEEPSEEK_API_KEY")),
            "resolved": codex,
        },
        "opencode": {
            "installed": bool(opencode and all(path.is_file() for path in adapters.get("opencode", []))),
            "state": "available" if opencode_primary else "degraded" if opencode_fallback else "needs_configuration",
            "primary_ready": opencode_primary,
            "fallback_ready": opencode_fallback,
            "resolved": opencode,
        },
        "hermes": {
            "installed": bool(hermes and managed.is_file()),
            "state": "available" if managed.is_file() and hermes_primary else "degraded" if managed.is_file() and hermes_fallback else "needs_configuration",
            "primary_ready": hermes_primary,
            "fallback_ready": hermes_fallback,
            "resolved": str(profile),
        },
    }


def execution_choice(agent_id: str, executor: str) -> dict[str, str]:
    values, _ = agent_definition(agent_id)
    values = executor_model_policy(values, executor)
    status = executor_status(agent_id).get(executor)
    if not isinstance(status, dict) or not status.get("installed"):
        raise AgentError(f"Agent executor is not installed: {executor}")
    if status.get("primary_ready"):
        return {
            "model": values["primary_model"],
            "reasoning": values["primary_reasoning"],
            "fallback_from": "",
            "fallback_reason": "",
        }
    if status.get("fallback_ready"):
        return {
            "model": values["fallback_model"],
            "reasoning": values["fallback_reasoning"],
            "fallback_from": values["primary_model"],
            "fallback_reason": "primary_unavailable",
        }
    raise AgentError(f"Agent executor has no usable declared model: {executor}")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def install_agent(agent_id: str) -> dict[str, object]:
    errors = validate_agent(agent_id)
    if errors:
        raise AgentError("; ".join(errors))
    values, _ = agent_definition(agent_id)
    profile = Path.home() / ".hermes" / "profiles" / agent_id
    managed_path = profile / ".ember-agent.json"
    config_path = profile / "config.yaml"
    if config_path.exists() and not managed_path.is_file():
        raise AgentError(f"refusing to overwrite unmanaged Hermes profile: {profile}")

    template = ROOT / "agents" / agent_id / "adapters" / "hermes-config.yaml"
    config_text = template.read_text(encoding="utf-8").replace("__EMBER_ROOT__", str(ROOT))
    soul = (
        "# 余烬 · Ember Managed Agent\n\n"
        f"Canonical contract: `{ROOT / 'agents' / agent_id / 'AGENT.md'}`\n\n"
        "Read that file before every task. This profile is an executor adapter and must not redefine it.\n\n"
        "Before actual work, validate a supplied run_id with `python3 scripts/ember_agent.py "
        "run-require`, or create one with `run-start` using executor `hermes` and the exact "
        "mode/model metadata, then validate it. Finish every run with `run-finish`, including "
        "failure and needs_input.\n"
    )
    managed = {
        "version": 1,
        "agent_id": agent_id,
        "source": str(ROOT / "agents" / agent_id / "AGENT.md"),
        "installed_at": now_iso_string(),
        "managed_files": ["config.yaml", "SOUL.md", ".ember-agent.json"],
        "managed_skills": ["ember", "ember-organization", "project-intake", "ebrain-in"],
    }
    _atomic_write(config_path, config_text)
    _atomic_write(profile / "SOUL.md", soul)
    environment = profile / ".env"
    if not environment.exists():
        _atomic_write(
            environment,
            "# Machine-local credentials for this Hermes profile. Never commit this file.\n",
        )
    skills = profile / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    sources = {
        "ember": ROOT / "skills" / "ember",
        "ember-organization": ROOT / "skills" / "ember-organization",
        "project-intake": ROOT / "skills" / "project-intake",
        "ebrain-in": Path.home() / "Ebrain" / "skills" / "ebrain-in",
    }
    for name, source in sources.items():
        if not (source / "SKILL.md").is_file():
            raise AgentError(f"Agent Skill source is unavailable: {source}")
        link = skills / name
        if link.exists() or link.is_symlink():
            if not link.is_symlink() or link.resolve() != source.resolve():
                raise AgentError(f"refusing to replace unmanaged Hermes Skill entry: {link}")
        else:
            link.symlink_to(source)
    _atomic_write(managed_path, json.dumps(managed, ensure_ascii=False, indent=2) + "\n")
    return {"ok": True, "agent_id": agent_id, "hermes_profile": str(profile)}


def uninstall_agent(agent_id: str) -> dict[str, object]:
    profile = Path.home() / ".hermes" / "profiles" / agent_id
    managed_path = profile / ".ember-agent.json"
    if not managed_path.is_file():
        return {"ok": True, "agent_id": agent_id, "removed": [], "note": "not installed"}
    managed = _read_json(managed_path)
    removed: list[str] = []
    for name in managed.get("managed_skills", []):
        link = profile / "skills" / str(name)
        if link.is_symlink():
            link.unlink()
            removed.append(str(link))
    for name in managed.get("managed_files", []):
        path = profile / str(name)
        if path.is_file() or path.is_symlink():
            path.unlink()
            removed.append(str(path))
    return {"ok": True, "agent_id": agent_id, "removed": removed}


def ledger_path() -> Path:
    return shared_workspace_root() / LEDGER_RELATIVE


@contextmanager
def _locked_ledger() -> Iterator[tuple[Path, dict[str, object]]]:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if path.is_file():
            payload = _read_json(path)
        else:
            payload = {"version": LEDGER_VERSION, "revision": 0, "runs": []}
        if not isinstance(payload.get("runs"), list):
            raise AgentError(f"Agent run ledger is invalid: {path}")
        yield path, payload
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def read_ledger() -> dict[str, object]:
    path = ledger_path()
    if not path.is_file():
        return {"version": LEDGER_VERSION, "revision": 0, "runs": []}
    return _read_json(path)


def start_run(*, agent_id: str, executor: str, model: str, mode: str, task_id: str = "", fallback_from: str = "", fallback_reason: str = "") -> dict[str, object]:
    values, _ = agent_definition(agent_id)
    if executor not in ALLOWED_EXECUTORS:
        raise AgentError(f"unsupported Agent executor: {executor}")
    if mode not in ALLOWED_MODES:
        raise AgentError(f"unsupported Agent mode: {mode}")
    values = executor_model_policy(values, executor)
    allowed_models = {values["primary_model"], values["fallback_model"]}
    if model not in allowed_models:
        raise AgentError(f"model is not allowed for {agent_id}: {model}")
    if model == values["fallback_model"]:
        if fallback_reason not in TECHNICAL_FALLBACK_REASONS and fallback_reason != "primary_unavailable":
            raise AgentError("fallback model requires a declared technical failure")
        if not fallback_from:
            raise AgentError("fallback model requires fallback_from")
        if fallback_from != values["primary_model"]:
            raise AgentError("fallback_from must identify the declared primary model")
    elif fallback_from or fallback_reason:
        raise AgentError("primary model run must not include fallback metadata")
    now = now_iso_string()
    run = {
        "run_id": f"run-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "run_revision": 1,
        "agent_id": agent_id,
        "executor": executor,
        "model": model,
        "reasoning": (
            reasoning_for_mode(values, mode)
            if model == values["primary_model"]
            else _mode_reasoning_map(values.get("mode_reasoning", "")).get(
                mode, values["fallback_reasoning"]
            )
        ),
        "mode": mode,
        "task_id": task_id,
        "state": "running",
        "started_at": now,
        "updated_at": now,
        "result_refs": [],
    }
    if fallback_from:
        run["fallback_from"] = fallback_from
        run["fallback_reason"] = fallback_reason
    with _locked_ledger() as (path, payload):
        payload["runs"].append(run)
        payload["revision"] = int(payload.get("revision") or 0) + 1
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return {"run": run, "ledger_revision": payload["revision"]}


def require_run(*, run_id: str, mode: str, task_id: str = "") -> dict[str, object]:
    if mode not in ALLOWED_MODES:
        raise AgentError(f"unsupported Agent mode: {mode}")
    now = datetime.now(timezone.utc)
    with _locked_ledger() as (_, payload):
        run = next(
            (
                item for item in payload["runs"]
                if isinstance(item, dict) and item.get("run_id") == run_id
            ),
            None,
        )
        if run is None:
            raise AgentError(f"Agent run not found: {run_id}")
        if run.get("agent_id") != "material-manager":
            raise AgentError(f"Agent run is not material-manager: {run_id}")
        if run.get("state") != "running":
            raise AgentError(f"Agent run is not running: {run_id}")
        if run.get("mode") != mode:
            raise AgentError(
                f"Agent run mode mismatch: expected {mode}, got {run.get('mode') or 'missing'}"
            )
        if task_id and run.get("task_id") != task_id:
            raise AgentError(
                f"Agent run task mismatch: expected {task_id}, got {run.get('task_id') or 'missing'}"
            )
        try:
            started_at = datetime.fromisoformat(str(run.get("started_at") or ""))
            if started_at.tzinfo is None:
                raise ValueError("timezone is missing")
        except ValueError as exc:
            raise AgentError(f"Agent run has invalid started_at: {run_id}") from exc
        age = now - started_at.astimezone(timezone.utc)
        if age < timedelta(0) or age > RUN_AUTHORIZATION_MAX_AGE:
            raise AgentError(f"Agent run authorization expired: {run_id}")
        return {
            "ok": True,
            "authorization": {
                "run_id": run_id,
                "agent_id": "material-manager",
                "mode": mode,
                "task_id": str(run.get("task_id") or ""),
                "executor": str(run.get("executor") or ""),
                "model": str(run.get("model") or ""),
                "reasoning": str(run.get("reasoning") or ""),
                "started_at": str(run.get("started_at") or ""),
                "expires_at": (started_at + RUN_AUTHORIZATION_MAX_AGE).isoformat(),
            },
        }


def expire_stale_runs(*, max_age: timedelta = RUN_AUTHORIZATION_MAX_AGE) -> dict[str, object]:
    """Close stale running records without deleting their audit history."""
    now = datetime.now(timezone.utc)
    expired_ids: list[str] = []
    with _locked_ledger() as (path, payload):
        for run in payload["runs"]:
            if not isinstance(run, dict) or run.get("state") != "running":
                continue
            try:
                started_at = datetime.fromisoformat(str(run.get("started_at") or ""))
                if started_at.tzinfo is None:
                    continue
            except ValueError:
                continue
            if now - started_at.astimezone(timezone.utc) <= max_age:
                continue
            timestamp = now_iso_string()
            run["state"] = "expired"
            run["updated_at"] = timestamp
            run["completed_at"] = timestamp
            run["run_revision"] = int(run.get("run_revision") or 1) + 1
            run["error"] = "Agent run authorization expired without a final state"
            expired_ids.append(str(run.get("run_id") or ""))
        if expired_ids:
            payload["revision"] = int(payload.get("revision") or 0) + 1
            _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return {
            "ok": True,
            "expired_run_ids": expired_ids,
            "expired_count": len(expired_ids),
            "ledger_revision": int(payload.get("revision") or 0),
        }


def finish_run(*, run_id: str, state: str, result_refs: list[str], error: str = "") -> dict[str, object]:
    if state not in ALLOWED_STATES - {"running"}:
        raise AgentError(f"unsupported final Agent state: {state}")
    with _locked_ledger() as (path, payload):
        run = next((item for item in payload["runs"] if isinstance(item, dict) and item.get("run_id") == run_id), None)
        if run is None:
            raise AgentError(f"Agent run not found: {run_id}")
        if run.get("state") != "running":
            raise AgentError(f"Agent run is already final: {run_id}")
        now = now_iso_string()
        run["state"] = state
        run["updated_at"] = now
        run["completed_at"] = now
        run["run_revision"] = int(run.get("run_revision") or 1) + 1
        run["result_refs"] = [value for value in result_refs if value]
        if error:
            run["error"] = error[:1000]
        payload["revision"] = int(payload.get("revision") or 0) + 1
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return {"run": run, "ledger_revision": payload["revision"]}


def verify_agent(agent_id: str) -> dict[str, object]:
    errors = validate_agent(agent_id)
    status = executor_status(agent_id) if not errors else {}
    for executor, item in status.items():
        if not item.get("installed") and executor != "hermes":
            errors.append(f"{executor} adapter is not installed")
        if item.get("state") == "needs_configuration" and executor != "hermes":
            errors.append(f"{executor} has no usable declared model")
    return {"ok": not errors, "agent_id": agent_id, "errors": errors, "executors": status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "status", "verify", "uninstall"):
        command = commands.add_parser(name)
        command.add_argument("agent_id")
    start = commands.add_parser("run-start")
    start.add_argument("--agent-id", default="material-manager")
    start.add_argument("--executor", required=True)
    start.add_argument("--model", required=True)
    start.add_argument("--mode", required=True)
    start.add_argument("--task-id", default="")
    start.add_argument("--fallback-from", default="")
    start.add_argument("--fallback-reason", default="")
    finish = commands.add_parser("run-finish")
    finish.add_argument("--run-id", required=True)
    finish.add_argument("--state", required=True)
    finish.add_argument("--result-ref", action="append", default=[])
    finish.add_argument("--error", default="")
    require = commands.add_parser("run-require")
    require.add_argument("--run-id", required=True)
    require.add_argument("--mode", required=True)
    require.add_argument("--task-id", default="")
    commands.add_parser("expire-runs")
    commands.add_parser("runs")
    args = parser.parse_args()
    try:
        if args.command == "install":
            result = install_agent(args.agent_id)
        elif args.command == "uninstall":
            result = uninstall_agent(args.agent_id)
        elif args.command == "status":
            values, _ = agent_definition(args.agent_id)
            result = {"agent": values, "executors": executor_status(args.agent_id), "ledger": read_ledger()}
        elif args.command == "verify":
            result = verify_agent(args.agent_id)
        elif args.command == "run-start":
            result = start_run(
                agent_id=args.agent_id, executor=args.executor, model=args.model,
                mode=args.mode, task_id=args.task_id, fallback_from=args.fallback_from,
                fallback_reason=args.fallback_reason,
            )
        elif args.command == "run-finish":
            result = finish_run(run_id=args.run_id, state=args.state, result_refs=args.result_ref, error=args.error)
        elif args.command == "run-require":
            result = require_run(run_id=args.run_id, mode=args.mode, task_id=args.task_id)
        elif args.command == "expire-runs":
            result = expire_stale_runs()
        else:
            result = read_ledger()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok", True) else 1
    except (AgentError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
