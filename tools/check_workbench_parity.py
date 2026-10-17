#!/usr/bin/env python3
"""Compare the open-source pages with the full workbench the maintainer actually uses.

The shared interface layer (stylesheets and scripts) is copied verbatim by
sync_workbench_styles.py, but most page markup is still rebuilt here by hand, so it can drift
without anyone noticing. This
check opens the running full workbench and a fresh fictional example of this package
side by side, page by page and at several widths, and compares:

- structure: which element kinds (tag + classes, within their parent) each page renders;
- appearance: background, text and border colors, font family, size and weight of the
  element kinds both sides render.

Every difference must be listed in docs/workbench-parity.json, either as intentional
(an open-source-only control, or a full-workbench module that is not shipped) or as
pending alignment. An unlisted difference fails the check. Only class names and computed
styles are compared; private page content, task names and paths are never written to the
repository. Screenshots of both sides go to a report folder outside the repository.

    python tools/check_workbench_parity.py --source <workbench checkout>
    python tools/check_workbench_parity.py --source <workbench checkout> --write-record

Requires Playwright with Chromium and the full workbench running (default 127.0.0.1:8765).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src/ember/web"
CONFIG = ROOT / "docs/workbench-parity.json"
RECORD = ROOT / "docs/workbench-parity-record.json"
UI_FILES = ("app.js", "app.css", "assets/workbench-pages.css")


SHARED = ROOT / "src/ember/ember_ui"


def ui_files() -> list[Path]:
    """Every file that shapes the pages: this package's web files, the page builder and the shared layer."""
    shared = sorted(path for path in SHARED.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    return [*(WEB / name for name in UI_FILES), ROOT / "src/ember/pages.py", *shared]

COLLECT = r"""([ignored, transparent, within]) => {
  // Shapes use class names only: a <form class="action-form"> that posts in the workbench and a
  // plain button here are the same control, so tags and pure wrapper classes are left out.
  const ignore = new RegExp(ignored), skip = new RegExp(transparent);
  const clean = node => [...node.classList].filter(name => !ignore.test(name)).sort().join(".");
  const wrapper = node => [...node.classList].some(name => skip.test(name));
  const out = {};
  const root = within ? document.querySelector(within) : document.body;
  for (const node of root ? root.querySelectorAll("*") : []) {
    if (!node.getClientRects().length || node.closest("[hidden]") || wrapper(node)) continue;
    const own = clean(node);
    if (!own) continue;
    let parent = node.parentElement;
    while (parent && parent !== document.body && (!clean(parent) || wrapper(parent))) parent = parent.parentElement;
    const shape = `${parent && parent !== document.body ? "." + clean(parent) + " > " : ""}.${own}`;
    const style = getComputedStyle(node);
    const look = [style.backgroundColor, style.color, style.borderTopColor, style.fontFamily.split(",")[0].trim(), style.fontSize, style.fontWeight].join(" | ");
    const full = `${shape} [${[...node.classList].sort().join(".")}]`;
    (out[shape] ||= { looks: {} });
    (out[shape].looks[full] ||= []).includes(look) || out[shape].looks[full].push(look);
  }
  return out;
}"""


def ui_sha256() -> str:
    digest = hashlib.sha256()
    for path in ui_files():
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def start_example() -> tuple[object, str, tempfile.TemporaryDirectory]:
    """A fresh fictional workspace of this package, served on a free loopback port."""
    sys.path.insert(0, str(ROOT / "src"))
    from ember.executors import ExecutorRegistry
    from ember.server import LocalServer
    from ember.store import Workspace
    temp = tempfile.TemporaryDirectory(prefix="ember-parity-")
    workspace = Workspace(Path(temp.name) / "Ember")
    workspace.initialize(example=True)
    workspace.create_project({"id": "ember", "name": "余烬", "kind": "system", "description": "本机余烬的安装与维护。"})
    registry = ExecutorRegistry(Path(temp.name) / "home")
    # Show the configured state, as on the maintainer's machine; nothing is ever launched.
    registry.save({"executors": [{"id": "example-cli", "label": "示例命令行工具", "kind": "command", "path": "/bin/echo"}],
                   "default_executor": "example-cli", "expected_revision": registry.snapshot()["revision"]})
    server = LocalServer(workspace, 0, executor_registry=registry)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}", temp


def private_pages(page, base: str, config: dict) -> dict[str, str]:
    """Pick real pages that match each fictional example page; their names are never stored."""
    base = base.rstrip("/")
    page.goto(base + "/projects")
    projects = page.evaluate("() => [...document.querySelectorAll('.project-view-card h2 a[href^=\"/projects/\"]')].map(a => a.getAttribute('href'))")
    tasks = page.evaluate("() => [...new Set([...document.querySelectorAll('a.project-view-task[href^=\"/tasks/\"]')].map(a => a.getAttribute('href')))]")
    found = {}
    for item in config["pages"]:
        if "pick" not in item:
            continue
        for href in projects if item["pick"]["from"] == "projects" else tasks:
            page.goto(base + href)
            page.wait_for_load_state("networkidle")  # Delivery lists load after the page itself.
            if page.evaluate(item["pick"]["when"]):
                found[item["name"]] = href
                break
        else:
            raise SystemExit(f"完整版工作台里没有可与「{item['name']}」对照的页面（条件：{item['pick']['when']}）。")
    return found


def compare(local: dict, core: dict, page: str) -> list[dict]:
    findings = []
    for shape in sorted(set(local) - set(core)):
        findings.append({"id": f"{page}:only-local:{shape}"})
    for shape in sorted(set(core) - set(local)):
        findings.append({"id": f"{page}:only-core:{shape}"})
    for shape in sorted(set(local) & set(core)):
        for full, looks in core[shape]["looks"].items():
            expected = local[shape]["looks"].get(full)
            if expected is None:
                continue  # A state or data variant only one side happens to show.
            extra = [look for look in looks if look not in expected]
            if extra:
                findings.append({"id": f"{page}:style:{shape}", "local": expected[:2], "core": extra[:2]})
    return findings


def classify(findings: list[dict], allowed: list[dict]) -> tuple[list, list, list, list]:
    unlisted, pending, intentional, used = [], [], [], set()
    for finding in findings:
        match = next((index for index, entry in enumerate(allowed) if fnmatch.fnmatchcase(finding["id"], entry["id"])), None)
        if match is None:
            unlisted.append(finding)
            continue
        used.add(match)
        (pending if allowed[match].get("status") == "pending" else intentional).append({**finding, "reason": allowed[match]["reason"]})
    stale = [entry for index, entry in enumerate(allowed) if index not in used]
    return unlisted, pending, intentional, stale


def run(args) -> int:
    from playwright.sync_api import sync_playwright
    config = load_config()
    sync = runpy.run_path(str(ROOT / "tools/sync_workbench_styles.py"))
    if sync["main"](["--source", str(args.source), "--workbench-url", args.workbench_url, "--check"]):
        print("样式表与完整版不一致：先运行 sync_workbench_styles.py 同步，再做页面对照。", file=sys.stderr)
        return 1
    report = Path(args.report or tempfile.mkdtemp(prefix="ember-parity-report-"))
    report.mkdir(parents=True, exist_ok=True)
    server, core_base, temp = start_example()
    findings: dict[str, dict] = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            dynamic = private_pages(page, args.workbench_url, config)
            for item in config["pages"]:
                local_path = dynamic.get(item["name"], item.get("local"))
                for width in config["widths"]:
                    page.set_viewport_size({"width": width, "height": 900})
                    sides = {}
                    for side, url in (("local", args.workbench_url.rstrip("/") + local_path), ("core", core_base + "/" + item["core"])):
                        page.goto(url)
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(400)
                        if item.get("fill"):  # Some dialogs open only once a request is typed.
                            page.locator(item["fill"][0]).fill(item["fill"][1])
                        if item.get("open"):  # A dialog or drawer the page opens on request; nothing is executed.
                            page.locator(item["open"]).first.click()
                            page.wait_for_load_state("networkidle")
                            page.wait_for_timeout(600)
                        sides[side] = page.evaluate(COLLECT, [config["ignore_classes"], config["transparent_classes"], item.get("within", "")])
                        page.screenshot(path=str(report / f"{item['name']}-{width}-{side}.png"), full_page=False)
                    for finding in compare(sides["local"], sides["core"], item["name"]):
                        known = findings.setdefault(finding["id"], {**finding, "widths": []})
                        known["widths"].append(width)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        temp.cleanup()
    unlisted, pending, intentional, stale = classify(list(findings.values()), config["allowed"])
    lines = [f"# 界面对照报告", "", f"- 时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
             f"- 页面 {len(config['pages'])} 个 × 宽度 {', '.join(map(str, config['widths']))}",
             f"- 未登记差异 {len(unlisted)} · 待对齐 {len(pending)} · 有意保留 {len(intentional)} · 白名单中已不存在 {len(stale)}", ""]
    for title, items in (("未登记差异（需修正或登记）", unlisted), ("待对齐", pending)):
        lines += [f"## {title}", ""] + [f"- `{item['id']}`（宽 {', '.join(map(str, item['widths']))}）"
                                        + (f"：本地 {item['local'][0]} → 开源 {item['core'][0]}" if "core" in item else "")
                                        + (f" — {item['reason']}" if "reason" in item else "") for item in items] + [""]
    lines += ["## 白名单中已不存在", ""] + [f"- `{entry['id']}` — {entry['reason']}" for entry in stale] + [""]
    (report / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:5]))
    for item in unlisted:
        print(f"未登记：{item['id']}" + (f"  本地 {item['local'][0]}  →  开源 {item['core'][0]}" if "core" in item else ""))
    print(f"报告与两侧截图：{report}")
    if unlisted:
        return 1
    if args.write_record:
        source = subprocess.run(["git", "-C", str(args.source), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        RECORD.write_text(json.dumps({
            "schema": 1, "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_commit": source, "ui_sha256": ui_sha256(),
            "pages": [item["name"] for item in config["pages"]], "widths": config["widths"],
            "pending": len(pending), "intentional": len(intentional),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已写入 {RECORD.relative_to(ROOT)}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="逐页对照开源版与完整版工作台的结构、颜色与字体")
    parser.add_argument("--source", required=True, type=Path, help="完整版工作台的本地仓库")
    parser.add_argument("--workbench-url", default="http://127.0.0.1:8765", help="正在运行的完整版工作台")
    parser.add_argument("--report", help="报告与截图目录；默认临时目录，不放进仓库")
    parser.add_argument("--write-record", action="store_true", help="通过后更新 docs/workbench-parity-record.json")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
