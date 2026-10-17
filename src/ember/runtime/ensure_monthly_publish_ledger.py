#!/usr/bin/env python3
"""Ensure monthly publish archive ledger exists for GStudio projects.

The ledger is prepared in a local archive-index mirror, then uploaded through
project-intake to the matching `bypy:/100项目` target. The local file is not the
archive of record.
"""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import calendar
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = _deployment_root()
from .path_config import project_archive_root, project_archive_uri

PROJECTS = {
    "yoga-platform": {
        "name": "瑜伽平台",
        "root": project_archive_root("yoga-platform"),
        "remote_uri": project_archive_uri("yoga-platform"),
    },
    "personal-blogger": {
        "name": "个人博主",
        "root": project_archive_root("personal-blogger"),
        "remote_uri": project_archive_uri("personal-blogger"),
    },
    "kesun-new-energy": {
        "name": "科隼新能源",
        "root": project_archive_root("kesun-new-energy"),
        "remote_uri": project_archive_uri("kesun-new-energy"),
    },
}

DIR_RE = re.compile(r"^(20\d{4})_(\d{2})_(.+)$")
INDEX_ROW_RE = re.compile(r"^\|\s*(20\d{6})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|.*?`([^`]+)`\s*\|")


def month_dir(project: str, year: int, month: int) -> Path:
    root = PROJECTS[project]["root"]
    return root / "发布归档"


def parse_existing_rows(root: Path, year: int, month: int) -> list[dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    ym = f"{year}{month:02d}"

    # Prefer the richer sorting index if it exists.
    legacy_root = root / str(year) / f"{month:02d}月"
    candidates = [
        root / f"{year}{month:02d}_发布记录表.md",
        legacy_root / f"{year}年{month:02d}月发布归档排序总表.md",
        legacy_root / f"{year}年{month:02d}月发布记录表.md",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        in_table = False
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if line.strip() == "## 发布记录":
                in_table = True
                continue
            if in_table and line.startswith("## "):
                break
            # The older sorting index has no "## 发布记录" heading; parse its
            # top table until the first blank after rows. For the newer ledger,
            # this guard prevents parsing the fenced "新条目模板" row as real data.
            if not in_table and candidate.name.endswith("发布记录表.md"):
                continue
            m = INDEX_ROW_RE.match(line)
            if not m:
                continue
            seq, account, title, path = m.groups()
            if not seq.startswith(ym):
                continue
            rows[seq] = {
                "seq": seq,
                "status": "已归档" if Path(path).exists() else "已登记",
                "publish_date": "待补",
                "account": account.strip(),
                "platform": "待补",
                "format": "待补",
                "title": title.strip(),
                "copy_path": "待补",
                "archive_path": path.strip(),
                "publish_link": "不收集",
                "metrics": "待补",
                "notes": "从既有排序总表导入",
            }

    if root.exists():
        for d in sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name):
            m = DIR_RE.match(d.name)
            if not m:
                continue
            prefix, number, title = m.groups()
            seq = prefix + number
            if prefix != ym or seq in rows:
                continue
            rows[seq] = {
                "seq": seq,
                "status": "已归档",
                "publish_date": "待补",
                "account": "待补",
                "platform": "待补",
                "format": "待补",
                "title": title,
                "copy_path": "待补",
                "archive_path": str(d),
                "publish_link": "不收集",
                "metrics": "待补",
                "notes": "从扁平实体目录扫描导入",
            }
    return [rows[k] for k in sorted(rows)]


def next_seq(rows: list[dict[str, str]], year: int, month: int) -> str:
    ym = f"{year}{month:02d}"
    nums = []
    for r in rows:
        seq = r.get("seq", "")
        if seq.startswith(ym):
            try:
                nums.append(int(seq[-2:]))
            except ValueError:
                pass
    return f"{ym}{(max(nums) + 1 if nums else 1):02d}"


def render(project: str, year: int, month: int, rows: list[dict[str, str]], root: Path) -> str:
    pname = PROJECTS[project]["name"]
    last_day = calendar.monthrange(year, month)[1]
    nxt = next_seq(rows, year, month)
    lines = [
        f"# {pname} {year}年{month:02d}月发布记录表",
        "",
        f"生成/更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 使用规则",
        "",
        "1. 每次收到发布文案、发布内容或最终素材时，先登记到本表。",
        "2. `序号` 是当月第几条内容，不是日期；下一条默认使用 `" + nxt + "`。",
        "3. 状态流转：`草稿登记 → 待发布 → 已发布待归档 → 已归档 → 已复盘`。",
        "4. 执行实体归档时，目录名必须沿用本表序号并使用：`YYYYMM_NN_内容`。",
        "5. 发布链接不作为本环节必填项，默认写 `不收集`；数据反馈可以后补，但不得跳过本表直接归档。",
        "",
        "## 月度信息",
        "",
        f"- 项目：{pname}",
        f"- 月份：{year}-{month:02d}-01 至 {year}-{month:02d}-{last_day:02d}",
        f"- 发布归档目录：`{root}`",
        f"- 当前已登记：{len(rows)} 条",
        f"- 下一条建议序号：`{nxt}`",
        "",
        "## 发布记录",
        "",
        "| 序号 | 状态 | 发布日期 | 账号 | 平台 | 形式 | 主题 | 文案/记录路径 | 归档路径 | 发布链接 | 数据反馈 | 备注 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| {seq} | {status} | {publish_date} | {account} | {platform} | {format} | {title} | `{copy_path}` | `{archive_path}` | {publish_link} | {metrics} | {notes} |".format(**r)
        )
    lines += [
        "",
        "## 新条目模板",
        "",
        "```markdown",
        f"| {nxt} | 草稿登记 | 待补 | 待补 | 待补 | 待补 | 主题待补 | `待补` | `待归档` | 不收集 | 待补 | 新发布先登记 |",
        "```",
        "",
        "## 待补清单",
        "",
        "- [ ] 如后续确实需要发布链接，再单独补充",
        "- [ ] 补齐数据反馈",
        "- [ ] 已发布待归档条目完成实体归档与 checksum",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="yoga-platform", choices=PROJECTS.keys())
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--month", type=int, default=datetime.now().month)
    args = parser.parse_args()

    root = month_dir(args.project, args.year, args.month)
    root.mkdir(parents=True, exist_ok=True)
    rows = parse_existing_rows(root, args.year, args.month)
    ledger = root / f"{args.year}{args.month:02d}_发布记录表.md"
    remote_root = "/".join((str(PROJECTS[args.project]["remote_uri"]), "发布归档"))
    ledger.write_text(render(args.project, args.year, args.month, rows, remote_root), encoding="utf-8")
    print(ledger)
    print(f"remote_target={remote_root}/{ledger.name}")
    print(f"rows={len(rows)} next={next_seq(rows, args.year, args.month)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
