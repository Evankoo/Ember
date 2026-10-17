#!/usr/bin/env python3
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root
from ..process import module_command

import json
import re
import subprocess
import sys
import argparse
from dataclasses import dataclass
from pathlib import Path

ROOT = _deployment_root()
from .path_config import archive_root, map_archive_path
from .workspace_paths import shared_workspace_root

ICLOUD_GSTUDIO_ROOT = shared_workspace_root()
SHARED_TASK_ROOT = ICLOUD_GSTUDIO_ROOT / "tasks"
EVAN4T_ROOT = archive_root()


@dataclass
class Finding:
    level: str
    check: str
    message: str
    suggestion: str = ""


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def frontmatter_block(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return "", False
    collected: list[str] = []
    for line in lines[1:]:
        if line == "---":
            return "\n".join(collected), True
        collected.append(line)
    return "\n".join(collected), False


def top_keys(frontmatter: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if line and not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            keys[key.strip()] = value.strip().strip('"')
    return keys


def extract_abs_paths(text: str) -> list[Path]:
    matches = re.findall(r'(?:"|`|^|\s)(/(?:Users|Volumes)/[^"`\n\s，。；：、）\)\]\}]+)', text)
    paths: list[Path] = []
    for match in matches:
        cleaned = match.strip().rstrip(",.;:]，。；：、）)")
        if cleaned.endswith("."):
            cleaned = cleaned[:-1]
        paths.append(Path(cleaned))
    return paths


def in_scope(check: str, scope: str) -> bool:
    if scope == "all":
        return True
    groups = {
        "tasks": {"tasks", "task-location", "task-frontmatter", "handoff"},
        "paths": {"storage", "task-path", "handoff"},
        "writeback": {"ebrain-writeback"},
        "cleanliness": {"workspace-cleanliness", "tmp", "git"},
    }
    return check in groups.get(scope, set())


def run_check_conformance() -> tuple[bool, str]:
    result = subprocess.run(
        module_command("ember.runtime.check_conformance"),
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return result.returncode == 0, result.stdout.strip()


def is_git_repo() -> bool:
    return (ROOT / ".git").exists()


def git_remote_count() -> int:
    if not is_git_repo():
        return 0
    result = subprocess.run(
        ["git", "remote"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        return 0
    return len([line for line in result.stdout.splitlines() if line.strip()])


def task_files() -> list[Path]:
    seen: dict[tuple[str, str], Path] = {}
    for root in (SHARED_TASK_ROOT, ROOT / "tasks"):
        if not root.exists():
            continue
        for path in sorted(root.glob("*/*.md")):
            key = (path.name,)
            # iCloud Documents is canonical and is scanned first; local cards are fallback only.
            seen.setdefault(key, path)
    return list(seen.values())


def display_task_path(path: Path) -> str:
    for root, label in ((SHARED_TASK_ROOT, "icloud-tasks"), (ROOT / "tasks", "tasks")):
        try:
            return f"{label}/{path.relative_to(root)}"
        except ValueError:
            pass
    return str(path)


def is_active_task(path: Path) -> bool:
    return path.parent.name == "active"


def main() -> int:
    parser = argparse.ArgumentParser(description="GStudio workspace health check")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON only")
    parser.add_argument(
        "--scope",
        choices=["tasks", "paths", "writeback", "cleanliness", "all"],
        default="all",
        help="Limit checks to one diagnostic area",
    )
    parser.add_argument(
        "--fix-suggestions",
        action="store_true",
        help="Include suggested non-mutating fixes in text output",
    )
    args = parser.parse_args()
    findings: list[Finding] = []

    if args.scope == "all":
        ok, output = run_check_conformance()
        if ok:
            findings.append(Finding("PASS", "conformance", "static conformance passed"))
        else:
            findings.append(Finding("FAIL", "conformance", output or "static conformance failed"))

    if args.scope in {"all", "paths"}:
        for name, path in [("iCloud GStudio root", ICLOUD_GSTUDIO_ROOT), ("Evan4T archive root", EVAN4T_ROOT)]:
            if path.exists() and path.is_dir():
                findings.append(Finding("PASS", "storage", f"{name} is accessible: {path}"))
            else:
                findings.append(Finding("WARN", "storage", f"{name} is not accessible: {path}", "Mount the volume before production, delivery, or archive work."))

    tasks = task_files()
    if args.scope in {"all", "tasks"}:
        shared_active = len(list((SHARED_TASK_ROOT / "active").glob("*.md"))) if SHARED_TASK_ROOT.exists() else 0
        shared_completed = len(list((SHARED_TASK_ROOT / "completed").glob("*.md"))) if SHARED_TASK_ROOT.exists() else 0
        local_active = len(list((ROOT / "tasks/active").glob("*.md")))
        local_completed = len(list((ROOT / "tasks/completed").glob("*.md")))
        findings.append(Finding("PASS", "tasks", f"{shared_active} iCloud active, {shared_completed} iCloud completed, {local_active} local active, {local_completed} local completed task(s)"))

    if args.scope in {"all", "tasks", "paths"}:
      for task in tasks:
        text = read(task)
        fm, closed = frontmatter_block(text)
        rel = display_task_path(task)
        if not closed:
            findings.append(Finding("FAIL", "task-frontmatter", f"frontmatter is not closed: {rel}"))
            continue
        keys = top_keys(fm)
        finished_looking = keys.get("current_stage") in {"archived", "completed", "done"}
        if args.scope in {"all", "tasks"}:
            if finished_looking and "/active/" in str(task):
                findings.append(Finding("WARN", "task-location", f"finished-looking task remains active: {rel}", "Review and move to the completed task root when no action remains."))
            if keys.get("system_boundary") in {"llm", "ebrain"} or "EBrain skill extracted from GStudio" in text or "LLM_WIKI skill extracted from GStudio" in text:
                findings.append(Finding("WARN", "task-location", f"migrated EBrain task can be closed or ignored by GStudio doctor: {rel}", "Move to completed after verifying the EBrain runtime owns follow-up work."))
        if args.scope in {"all", "paths"} and is_active_task(task) and not finished_looking:
            for path in sorted(set(extract_abs_paths(fm)), key=str):
                if str(path).startswith(str(ROOT)):
                    if not path.exists():
                        findings.append(Finding("WARN", "task-path", f"task references missing local path: {rel} -> {path}", "If this is historical migration text, mark the task completed or update stale paths to the new system boundary."))
                elif str(path).startswith("/Volumes/"):
                    mapped = map_archive_path(path)
                    if not path.exists() and not mapped.exists():
                        suggestion = "Mount the volume or update/remove stale historical path references."
                        if mapped != path:
                            suggestion = f"Archive root is mapped to {EVAN4T_ROOT}; expected mapped path: {mapped}"
                        findings.append(Finding("WARN", "task-path", f"task references missing volume path: {rel} -> {path}", suggestion))

    if args.scope in {"all", "tasks", "paths"}:
        handoff_paths = set((ROOT / "handoffs").glob("*"))
        handoff_names = {str(path) for path in handoff_paths}
        for task in tasks:
            text = read(task)
            rel = display_task_path(task)
            for path in re.findall(r"/Users/(?:buttercup|evan)/GStudio/handoffs/[^\"`\n\s]+", text):
                cleaned = path.strip().rstrip(",.]，。；：、)")
                if cleaned not in handoff_names and not Path(cleaned).exists():
                    findings.append(Finding("WARN", "handoff", f"task references missing handoff: {rel} -> {cleaned}"))

    if args.scope in {"all", "writeback"}:
        pending_writebacks = []
        unknown_writebacks = []
        for patch in sorted((ROOT / "ebrain-writeback").glob("*.md")):
            if patch.name == "README.md":
                continue
            text = read(patch)
            fm, _ = frontmatter_block(text)
            keys = top_keys(fm)
            status = keys.get("writeback_status", "").lower()
            if status in {"pending", "deferred", "needs_review"}:
                pending_writebacks.append(str(patch.relative_to(ROOT)))
            elif not status:
                unknown_writebacks.append(str(patch.relative_to(ROOT)))
        if pending_writebacks:
            findings.append(Finding("WARN", "ebrain-writeback", f"possible pending writeback patch(es): {', '.join(pending_writebacks)}", "Write to EBrain when available or mark the patch done/failed/deferred with provenance."))
        elif unknown_writebacks:
            findings.append(Finding("WARN", "ebrain-writeback", f"writeback patch(es) missing writeback_status: {', '.join(unknown_writebacks)}", "Add writeback_status frontmatter so deferred work is explicit."))
        else:
            findings.append(Finding("PASS", "ebrain-writeback", "all writeback patches have non-pending status"))

    if args.scope in {"all", "cleanliness"}:
        ds_store = sorted(ROOT.glob("**/.DS_Store"))
        if ds_store:
            findings.append(Finding("WARN", "workspace-cleanliness", f"{len(ds_store)} .DS_Store file(s) present", "Clean in a separate maintenance task if they become noisy."))
        else:
            findings.append(Finding("PASS", "workspace-cleanliness", "no .DS_Store files found"))

        tmp_files = [path for path in (ROOT / "tmp").glob("**/*") if path.is_file() and path.name != "README.md"]
        if tmp_files:
            findings.append(Finding("WARN", "tmp", f"{len(tmp_files)} tmp file(s) present", "Clean in a separate maintenance task after confirming no active task needs them."))
        else:
            findings.append(Finding("PASS", "tmp", "tmp has no scratch files"))

        if is_git_repo():
            remotes = git_remote_count()
            if remotes:
                findings.append(Finding("PASS", "git", f"git repo initialized with {remotes} remote(s)"))
            else:
                findings.append(Finding("WARN", "git", "git repo initialized but no remote is configured"))
        else:
            findings.append(Finding("PASS", "git", "git sync is not enabled; this is optional for the current NAS-centered setup"))

    findings = [finding for finding in findings if in_scope(finding.check, args.scope) or args.scope == "all"]

    fail_count = sum(1 for finding in findings if finding.level == "FAIL")
    warn_count = sum(1 for finding in findings if finding.level == "WARN")
    pass_count = sum(1 for finding in findings if finding.level == "PASS")

    status = "FAIL" if fail_count else "WARN" if warn_count else "PASS"
    summary = {
        "status": status,
        "pass": pass_count,
        "warn": warn_count,
        "fail": fail_count,
        "scope": args.scope,
        "findings": [
            {
                "level": finding.level,
                "check": finding.check,
                "message": finding.message,
                "suggestion": finding.suggestion,
            }
            for finding in findings
        ],
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"GStudio doctor: {status} ({pass_count} pass, {warn_count} warn, {fail_count} fail)")
        for finding in findings:
            print(f"[{finding.level}] {finding.check}: {finding.message}")
            if args.fix_suggestions and finding.suggestion:
                print(f"  suggestion: {finding.suggestion}")
        print(json.dumps({k: v for k, v in summary.items() if k != "findings"}, ensure_ascii=False))
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
