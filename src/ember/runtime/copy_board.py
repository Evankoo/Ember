#!/usr/bin/env python3
"""Add or version full-text copy inside a project's single Markdown board."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import datetime as dt
import json
import re
from pathlib import Path

from .time_format import now_iso_string
from .workspace_paths import shared_workspace_root

ROOT = _deployment_root()
SHARED_ROOT = shared_workspace_root()
CONFIG = ROOT / "config" / "projects.json"


def projects() -> dict[str, dict[str, object]]:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    return {str(item["slug"]): item for item in data["projects"]}


def board_path(project: str) -> Path:
    item = projects().get(project)
    if not item or not item.get("copy_board"):
        raise SystemExit(f"project has no copy board: {project}")
    return SHARED_ROOT / str(item["copy_board"])


def entry_block(
    copy_id: str,
    title: str,
    channel: str,
    status: str,
    source: str,
    content: str,
    date: str,
    subproject: str,
    version: int = 1,
    history: str = "_无_",
    replaces: str = "",
) -> str:
    sub = f"- subproject：{subproject}\n" if subproject else ""
    replace_line = f"- 替代：{replaces}\n" if replaces else ""
    return (
        f"<!-- COPY:{copy_id} START -->\n"
        f"## {copy_id}｜{title}\n\n"
        f"{sub}- 渠道/场景：{channel}\n- 状态：{status}\n"
        f"- 当前版本：v{version}\n- 更新时间：{date}\n- 来源：{source}\n{replace_line}\n"
        f"### 当前版本\n\n{content.strip()}\n\n"
        f"### 版本历史\n\n{history.strip()}\n"
        f"<!-- COPY:{copy_id} END -->"
    )


def add_or_version(args: argparse.Namespace) -> Path:
    path = board_path(args.project)
    text = path.read_text(encoding="utf-8")
    content = Path(args.content_file).read_text(encoding="utf-8")
    date = args.date or dt.date.today().isoformat()
    if args.project == "small-project-pool" and not args.subproject:
        raise SystemExit("small-project-pool requires --subproject")

    pattern = re.compile(
        rf"<!-- COPY:{re.escape(args.copy_id)} START -->\n(.*?)\n<!-- COPY:{re.escape(args.copy_id)} END -->",
        re.S,
    )
    match = pattern.search(text)
    if match:
        old = match.group(1)
        version_match = re.search(r"^- 当前版本：v(\d+)\s*$", old, re.M)
        old_version = int(version_match.group(1)) if version_match else 1
        current_match = re.search(r"### 当前版本\n\n(.*?)\n\n### 版本历史\n\n(.*)\Z", old, re.S)
        old_current = current_match.group(1).strip() if current_match else ""
        old_history = current_match.group(2).strip() if current_match else "_无_"
        history_piece = f"#### v{old_version}｜被 v{old_version + 1} 替代于 {date}\n\n{old_current}"
        history = history_piece if old_history == "_无_" else f"{history_piece}\n\n{old_history}"
        new_block = entry_block(
            args.copy_id, args.title, args.channel, args.status, args.source,
            content, date, args.subproject or "", old_version + 1, history,
            args.replaces or "",
        )
        text = text[: match.start()] + new_block + text[match.end() :]
    else:
        new_block = entry_block(
            args.copy_id, args.title, args.channel, args.status, args.source,
            content, date, args.subproject or "", 1, "_无_", args.replaces or "",
        )
        text = text.rstrip() + "\n\n" + new_block + "\n"
        if args.project == "small-project-pool":
            row = f"| {args.copy_id} | {args.subproject} | {args.title} | {args.channel} | {args.status} | v1 | {date} |\n"
        else:
            row = f"| {args.copy_id} | {args.title} | {args.channel} | {args.status} | v1 | {date} |\n"
        text = text.replace("\n## 文案正文\n", "\n" + row + "\n## 文案正文\n", 1)

    board_updated_at = now_iso_string()
    text = re.sub(r"^updated_at:\s*.*$", f"updated_at: {board_updated_at}", text, count=1, flags=re.M)
    if match:
        text = re.sub(
            rf"^(\| {re.escape(args.copy_id)} \|.*?\|) v\d+ \| [^|]+ \|$",
            lambda m: re.sub(r"\| v\d+ \| [^|]+ \|$", f"| v{old_version + 1} | {date} |", m.group(0)),
            text,
            count=1,
            flags=re.M,
        )
    path.write_text(text, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("--project", required=True)
    add.add_argument("--copy-id", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--channel", required=True)
    add.add_argument("--status", choices=["draft", "current", "superseded", "archived"], required=True)
    add.add_argument("--source", required=True)
    add.add_argument("--content-file", required=True)
    add.add_argument("--date")
    add.add_argument("--subproject")
    add.add_argument("--replaces")
    args = parser.parse_args()
    path = add_or_version(args)
    print(json.dumps({"updated": str(path), "copy_id": args.copy_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
