#!/usr/bin/env python3
"""Register task inputs without mixing source material into delivery folders."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from . import gstudio_task

from .workspace_paths import (
    current_environment_name,
    shared_task_root,
    shared_workspace_root,
    task_input_snapshot_max_bytes,
    task_inputs_root,
)

ROOT = _deployment_root()
LOCAL_TASK_ROOT = ROOT / "tasks"
ITEM_FIELDS = (
    "id",
    "name",
    "purpose",
    "storage",
    "source_locator",
    "source_environment",
    "path",
    "sha256",
    "size",
    "required",
    "added_at",
)


def now_beijing() -> str:
    zone = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.now(zone).strftime("%Y-%m-%d %H:%M:%S+08:00")


def find_task(task_id: str) -> Path:
    for root in (shared_task_root(), LOCAL_TASK_ROOT):
        for state in ("active", "completed"):
            path = root / state / f"{task_id}.md"
            if path.is_file():
                return path
    raise ValueError(f"task card not found: {task_id}")


def frontmatter_bounds(text: str) -> tuple[int, int]:
    if not text.startswith("---\n"):
        raise ValueError("task card must start with YAML frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("task card frontmatter is not closed")
    return 4, end


def scalar(raw: str) -> object:
    value = raw.strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        if value in {"true", "false"}:
            return value == "true"
        if re.fullmatch(r"-?\d+", value):
            return int(value)
        return value.strip("\"'")


def inputs_block(text: str) -> tuple[str, int, int] | None:
    start_fm, end_fm = frontmatter_bounds(text)
    fm = text[start_fm:end_fm]
    match = re.search(r"^inputs:\s*$", fm, re.MULTILINE)
    if not match:
        return None
    start = start_fm + match.start()
    following = re.search(r"^[A-Za-z_][A-Za-z0-9_-]*:\s*", fm[match.end():], re.MULTILINE)
    stop = start_fm + (match.end() + following.start() if following else len(fm))
    return text[start:stop].rstrip(), start, stop


def parse_inputs(text: str) -> dict[str, object]:
    located = inputs_block(text)
    if not located:
        return {"folder": "", "items": []}
    block = located[0]
    if not re.search(r"^  items:\s*$", block, re.MULTILINE):
        raise ValueError("existing inputs block uses a legacy shape; migrate it before using this tool")
    folder_match = re.search(r"^  folder:\s*(.+?)\s*$", block, re.MULTILINE)
    folder = str(scalar(folder_match.group(1))) if folder_match else ""
    items: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in block.splitlines():
        first = re.match(r"^    - ([A-Za-z_][A-Za-z0-9_-]*):\s*(.+?)\s*$", line)
        if first:
            current = {first.group(1): scalar(first.group(2))}
            items.append(current)
            continue
        field = re.match(r"^      ([A-Za-z_][A-Za-z0-9_-]*):\s*(.+?)\s*$", line)
        if field and current is not None:
            current[field.group(1)] = scalar(field.group(2))
    return {"folder": folder, "items": items}


def yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def render_inputs(task_id: str, items: list[dict[str, object]]) -> str:
    lines = ["inputs:"]
    if any(item.get("storage") == "snapshot" for item in items):
        lines.append(f"  folder: {yaml_scalar(f'任务资料/{task_id}/')}")
    lines.append("  items:")
    for item in items:
        lines.append(f"    - id: {yaml_scalar(item['id'])}")
        for key in ITEM_FIELDS[1:]:
            value = item.get(key)
            if value not in (None, ""):
                lines.append(f"      {key}: {yaml_scalar(value)}")
    return "\n".join(lines)


def atomic_write(path: Path, text: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def update_card(path: Path, task_id: str, items: list[dict[str, object]], log: str) -> None:
    text = path.read_text(encoding="utf-8")
    block = render_inputs(task_id, items)
    located = inputs_block(text)
    if located:
        text = text[:located[1]] + block + "\n" + text[located[2]:].lstrip("\n")
    else:
        _, end = frontmatter_bounds(text)
        text = text[:end].rstrip() + "\n" + block + text[end:]
    timestamp = now_beijing()
    text = re.sub(r"^updated_at:\s*.*$", f"updated_at: {timestamp}", text, count=1, flags=re.MULTILINE)
    text = gstudio_task.prepend_execution_log_entry(text, f"{timestamp}｜{log}")
    atomic_write(path, text)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_name(value: str) -> str:
    name = value.strip()
    if not name or name in {".", ".."} or Path(name).name != name or "/" in name:
        raise ValueError("input name must be one plain filename")
    if name.startswith("."):
        raise ValueError("input name must not be hidden")
    return name


def item_id(storage: str, name: str, fingerprint: str) -> str:
    seed = f"{storage}\0{name}\0{fingerprint}".encode("utf-8")
    return f"input-{hashlib.sha256(seed).hexdigest()[:12]}"


def command_snapshot(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"snapshot source is not a file: {source}")
    size = source.stat().st_size
    limit = task_input_snapshot_max_bytes()
    if size > limit:
        raise ValueError(
            f"source is {size} bytes, above the {limit} byte snapshot limit; "
            "use add-reference or archive it through project-intake"
        )
    name = validate_name(args.name or source.name)
    source_suffix = source.suffix
    if source_suffix and Path(name).suffix.lower() != source_suffix.lower():
        raise ValueError(
            f"snapshot name must preserve the source extension {source_suffix}: {name}"
        )
    task_path = find_task(args.task_id)
    text = task_path.read_text(encoding="utf-8")
    parsed = parse_inputs(text)
    items = list(parsed["items"])
    fingerprint = sha256(source)
    identifier = item_id("snapshot", name, fingerprint)
    for item in items:
        if item.get("id") == identifier:
            print(f"GStudio task inputs: snapshot already registered\n- id: {identifier}")
            return 0
    folder = task_inputs_root() / args.task_id
    destination = folder / name
    if destination.exists():
        raise ValueError(f"snapshot destination already exists; inputs are immutable: {destination}")
    folder.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=f".{name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
        shutil.copy2(source, temporary)
        copied_hash = sha256(temporary)
        if copied_hash != fingerprint or temporary.stat().st_size != size:
            raise ValueError("snapshot verification failed before atomic publish")
        os.replace(temporary, destination)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    relative = destination.relative_to(shared_workspace_root()).as_posix()
    item = {
        "id": identifier,
        "name": name,
        "purpose": args.purpose,
        "storage": "snapshot",
        "source_locator": str(source),
        "source_environment": current_environment_name(),
        "path": relative,
        "sha256": fingerprint,
        "size": size,
        "required": bool(args.required),
        "added_at": now_beijing(),
    }
    items.append(item)
    update_card(task_path, args.task_id, items, f"登记任务输入快照 `{name}`；保留来源、大小与 SHA-256，输入资料与交付物分离。")
    print(f"GStudio task inputs: SNAPSHOT ADDED\n- task: {task_path}\n- input: {destination}\n- sha256: {fingerprint}")
    return 0


def command_reference(args: argparse.Namespace) -> int:
    task_path = find_task(args.task_id)
    text = task_path.read_text(encoding="utf-8")
    parsed = parse_inputs(text)
    items = list(parsed["items"])
    locator = args.locator.strip()
    if not locator:
        raise ValueError("reference locator is required")
    local = Path(locator).expanduser()
    exists = local.is_file() if local.is_absolute() else False
    size = local.stat().st_size if exists else 0
    fingerprint = sha256(local) if exists else hashlib.sha256(locator.encode("utf-8")).hexdigest()
    name = args.name or (local.name if exists else locator.rstrip("/").rsplit("/", 1)[-1]) or "reference"
    identifier = item_id(args.storage, name, fingerprint)
    if any(item.get("id") == identifier for item in items):
        print(f"GStudio task inputs: reference already registered\n- id: {identifier}")
        return 0
    item = {
        "id": identifier,
        "name": name,
        "purpose": args.purpose,
        "storage": args.storage,
        "source_locator": locator,
        "source_environment": args.source_environment or current_environment_name(),
        "sha256": fingerprint if exists else "",
        "size": size if exists else 0,
        "required": bool(args.required),
        "added_at": now_beijing(),
    }
    items.append(item)
    update_card(task_path, args.task_id, items, f"登记任务输入引用 `{name}`（{args.storage}）；未复制到任务资料或交付目录。")
    print(f"GStudio task inputs: REFERENCE ADDED\n- task: {task_path}\n- locator: {locator}\n- storage: {args.storage}")
    return 0


def command_verify(args: argparse.Namespace) -> int:
    task_path = find_task(args.task_id)
    parsed = parse_inputs(task_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    checked = 0
    for item in parsed["items"]:
        if item.get("storage") != "snapshot":
            continue
        checked += 1
        relative = str(item.get("path") or "")
        candidate = (shared_workspace_root() / relative).resolve()
        expected_root = (task_inputs_root() / args.task_id).resolve()
        try:
            candidate.relative_to(expected_root)
        except ValueError:
            errors.append(f"snapshot outside task input root: {relative}")
            continue
        if not candidate.is_file():
            errors.append(f"snapshot missing: {relative}")
            continue
        if int(item.get("size") or 0) != candidate.stat().st_size:
            errors.append(f"snapshot size mismatch: {relative}")
        if str(item.get("sha256") or "") != sha256(candidate):
            errors.append(f"snapshot sha256 mismatch: {relative}")
    if errors:
        print("GStudio task inputs: VERIFY FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"GStudio task inputs: VERIFY PASS\n- task: {task_path}\n- snapshots: {checked}\n- references: {len(parsed['items']) - checked}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("add-snapshot", help="Copy a small immutable input into the shared task input root")
    snapshot.add_argument("--task-id", required=True)
    snapshot.add_argument("--source", required=True)
    snapshot.add_argument("--name")
    snapshot.add_argument("--purpose", required=True)
    snapshot.add_argument("--required", action="store_true")
    snapshot.set_defaults(handler=command_snapshot)
    reference = subparsers.add_parser("add-reference", help="Register a stable, archived, or oversized source without copying it")
    reference.add_argument("--task-id", required=True)
    reference.add_argument("--locator", required=True)
    reference.add_argument("--name")
    reference.add_argument("--purpose", required=True)
    reference.add_argument("--storage", choices=("reference", "archive"), default="reference")
    reference.add_argument("--source-environment")
    reference.add_argument("--required", action="store_true")
    reference.set_defaults(handler=command_reference)
    verify = subparsers.add_parser("verify", help="Verify every immutable snapshot registered to a task")
    verify.add_argument("--task-id", required=True)
    verify.set_defaults(handler=command_verify)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError) as exc:
        print(f"GStudio task inputs: ERROR\n- {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
