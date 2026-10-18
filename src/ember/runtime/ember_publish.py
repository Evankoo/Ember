#!/usr/bin/env python3
"""Shared, human-readable publish records for the Ember workbench."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .workspace_paths import shared_workspace_root, workspace_inbox_root


RELEASE_ROOT = shared_workspace_root() / "管理中心" / "归档管理" / "发布记录"
PROCESSING_ROOT = workspace_inbox_root()
PROJECTS = ("yoga-platform", "personal-blogger", "kesun-new-energy", "small-project-pool")
PROJECT_TITLES = {
    "yoga-platform": "瑜伽平台",
    "personal-blogger": "个人博主",
    "kesun-new-energy": "科隼新能源",
    "small-project-pool": "小项目池",
}
STATUS_LABELS = {
    "copy_review": "文案待确认",
    "ready": "待发布",
    "published": "已发布·待归档",
    "archived": "已归档",
    "rejected": "不采用",
}
COPY_SOURCE_LABELS = {
    "gstudio": "余烬 · Ember 生成",
    "evan_direct": "Evan 自行发布",
    "not_recorded": "不记录文案",
}
RECORD_RE = re.compile(r"^<!-- EMBER_RELEASE (\{.*\}) -->$", re.MULTILINE)


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _year_path(project: str, year: int) -> Path:
    if project not in PROJECTS:
        raise ValueError("不支持的发布项目。")
    return RELEASE_ROOT / project / f"{year}.md"


def _read_path(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for match in RECORD_RE.finditer(path.read_text(encoding="utf-8", errors="replace")):
        try:
            item = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("release_id"):
            item["ledger_path"] = str(path)
            records.append(item)
    return records


def list_records(project: str = "", year: int | None = None) -> list[dict[str, object]]:
    projects = (project,) if project else PROJECTS
    records: list[dict[str, object]] = []
    for slug in projects:
        folder = RELEASE_ROOT / slug
        paths = [folder / f"{year}.md"] if year else sorted(folder.glob("20[0-9][0-9].md")) if folder.exists() else []
        for path in paths:
            records.extend(_read_path(path))
    records.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return records


def find_record(project: str, release_id: str) -> dict[str, object] | None:
    if project not in PROJECTS:
        return None
    match = re.fullmatch(r"(20\d{2})\d{4}", release_id)
    if not match:
        return None
    year = int(match.group(1))
    for record in _read_path(_year_path(project, year)):
        if record.get("release_id") == release_id:
            return record
    return None


def _next_id(records: list[dict[str, object]], published_at: str = "") -> str:
    try:
        date = datetime.strptime(published_at[:10], "%Y-%m-%d") if published_at else datetime.now()
    except ValueError as exc:
        raise ValueError("发布日期必须使用 YYYY-MM-DD。") from exc
    prefix = date.strftime("%Y%m")
    used = []
    for item in records:
        value = str(item.get("release_id") or "")
        if value.startswith(prefix) and value[-2:].isdigit():
            used.append(int(value[-2:]))
    return f"{prefix}{max(used, default=0) + 1:02d}"


def _clean(value: object, limit: int = 1000) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _safe_material_path(value: str) -> str:
    if not value:
        return ""
    root = PROCESSING_ROOT.resolve()
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("发布资料必须位于工作台目录。") from exc
    if path == root or not path.exists():
        raise ValueError("请选择工作台内实际存在的资料包。")
    return str(path)


@contextmanager
def _locked(project: str, year: int) -> Iterator[Path]:
    path = _year_path(project, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield path


def create_record(
    *, project: str, topic: str, platform: str, account: str,
    status: str = "copy_review", copy_source: str = "not_recorded", copy_text: str = "",
    published_at: str = "", source_task_id: str = "", material_path: str = "",
) -> dict[str, object]:
    if project not in PROJECTS:
        raise ValueError("不支持的发布项目。")
    if status not in STATUS_LABELS:
        raise ValueError("不支持的发布状态。")
    if copy_source not in COPY_SOURCE_LABELS:
        raise ValueError("不支持的文案来源。")
    topic = _clean(topic, 80)
    if not topic:
        raise ValueError("请输入发布主题。")
    year = int((published_at[:4] if published_at else datetime.now().strftime("%Y")))
    with _locked(project, year) as path:
        records = _read_path(path)
        release_id = _next_id(records, published_at)
        stamp = now_text()
        item: dict[str, object] = {
            "release_id": release_id,
            "project": project,
            "topic": topic,
            "status": status,
            "platform": _clean(platform, 40),
            "account": _clean(account, 80),
            "published_at": _clean(published_at, 10),
            "copy_source": copy_source,
            "copy_text": _clean(copy_text, 12000),
            "source_task_id": _clean(source_task_id, 120),
            "material_path": _safe_material_path(material_path),
            "archive_uri": "",
            "archive_receipt": "",
            "created_at": stamp,
            "updated_at": stamp,
        }
        records.append(item)
        _write(path, records)
        return item


def update_record(project: str, release_id: str, **changes: object) -> dict[str, object]:
    existing = find_record(project, release_id)
    if not existing:
        raise ValueError("发布记录不存在。")
    year = int(release_id[:4])
    allowed = {"status", "topic", "platform", "account", "published_at", "material_path", "archive_uri", "archive_receipt", "copy_text"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError("包含不允许修改的发布字段。")
    with _locked(project, year) as path:
        records = _read_path(path)
        target = next((item for item in records if item.get("release_id") == release_id), None)
        if not target:
            raise ValueError("发布记录不存在。")
        if "status" in changes:
            status = _clean(changes["status"], 40)
            if status not in STATUS_LABELS:
                raise ValueError("不支持的发布状态。")
            target["status"] = status
        for key in allowed - {"status", "material_path"}:
            if key in changes:
                target[key] = _clean(changes[key], 12000 if key == "copy_text" else 1000)
        if "material_path" in changes:
            target["material_path"] = _safe_material_path(_clean(changes["material_path"], 2000))
        target["updated_at"] = now_text()
        _write(path, records)
        return dict(target)


def processing_packages() -> list[dict[str, object]]:
    if not PROCESSING_ROOT.is_dir():
        return []
    linked = {str(item.get("material_path") or "") for item in list_records()}
    packages = []
    try:
        children = sorted(PROCESSING_ROOT.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    for path in children:
        if path.name.startswith("."):
            continue
        try:
            count = sum(1 for _ in path.iterdir()) if path.is_dir() else 1
            updated = datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="minutes")
        except OSError:
            continue
        packages.append({"name": path.name, "path": str(path), "is_dir": path.is_dir(), "item_count": count, "updated_at": updated, "linked": str(path.resolve()) in linked})
    return packages


def archive_prompt(record: dict[str, object]) -> str:
    material = str(record.get("material_path") or "")
    if not material:
        raise ValueError("请先关联发布资料。")
    return "\n".join([
        "## 余烬 · Ember 发布归档", "",
        f"- 发布编号：{record.get('release_id')}",
        f"- 项目：{PROJECT_TITLES.get(str(record.get('project')), record.get('project'))}",
        f"- 主题：{record.get('topic')}",
        f"- 平台 / 账号：{record.get('platform') or '未记录'} / {record.get('account') or '未记录'}",
        f"- 当前状态：{STATUS_LABELS.get(str(record.get('status')), record.get('status'))}",
        f"- 来源资料包：{material}", "",
        "请使用 project-intake 的普通单条发布归档流程，不创建重复任务卡。先确认项目、来源资料包、NAS 目标路径和来源处理方式；目标目录使用发布编号对应的 YYYYMM_NN_主题。复制到 NAS 并完成本地验证后，追加现有资料归档操作回执，并把本发布记录更新为已归档，写入 archive_uri 与 archive_receipt。未完成 NAS 验证时不得标记已归档，也不得删除来源资料。",
    ])


def _write(path: Path, records: list[dict[str, object]]) -> None:
    records.sort(key=lambda item: str(item.get("release_id") or ""))
    project = path.parent.name
    title = PROJECT_TITLES.get(project, project)
    lines = [
        f"# {title} {path.stem} 发布记录", "",
        "> 本文件是 余烬 · Ember 发布工作台的业务正本。简单发布文案不另建任务卡、交付目录或独立文档。", "",
        "## 发布索引", "",
        "| 发布编号 | 状态 | 发布日期 | 平台 | 账号 | 主题 | 来源任务 | 归档 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in records:
        lines.append("| {release_id} | {status} | {published_at} | {platform} | {account} | {topic} | {source_task_id} | {archive} |".format(
            release_id=item.get("release_id", ""), status=STATUS_LABELS.get(str(item.get("status")), item.get("status", "")),
            published_at=item.get("published_at") or "—", platform=item.get("platform") or "—", account=item.get("account") or "—",
            topic=str(item.get("topic") or "").replace("|", "｜"), source_task_id=item.get("source_task_id") or "—",
            archive="已归档" if item.get("archive_uri") else "待归档",
        ))
    lines += ["", "## 发布详情", ""]
    for item in records:
        payload = {key: value for key, value in item.items() if key != "ledger_path"}
        lines += [
            f"### {item.get('release_id')}｜{item.get('topic')}", "",
            f"<!-- EMBER_RELEASE {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))} -->", "",
            f"- 状态：{STATUS_LABELS.get(str(item.get('status')), item.get('status'))}",
            f"- 平台 / 账号：{item.get('platform') or '—'} / {item.get('account') or '—'}",
            f"- 发布日期：{item.get('published_at') or '—'}",
            f"- 文案来源：{COPY_SOURCE_LABELS.get(str(item.get('copy_source')), item.get('copy_source'))}",
            f"- 来源任务：{item.get('source_task_id') or '—'}",
            f"- 关联资料：`{item.get('material_path') or '未关联'}`",
            f"- 归档位置：`{item.get('archive_uri') or '待归档'}`", "",
        ]
        if item.get("copy_text"):
            lines += ["#### 最终发布文案", "", str(item["copy_text"]), ""]
    payload = "\n".join(lines).rstrip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
