#!/usr/bin/env python3
"""Copy the full workbench stylesheet into the open-source web assets.

The public interface is derived from the full workbench used in practice:
its stylesheet is copied here verbatim except for the embedded display font,
which points at the bundled OFL font instead. The source is read as inert
constants; no workbench service, data or configuration is loaded.

    python tools/sync_workbench_styles.py --source <workbench checkout>          # update
    python tools/sync_workbench_styles.py --source <workbench checkout> --check  # report drift only

Some workbench pages carry their own <style> blocks. Those are read from the locally running
workbench (--workbench-url); only the <style> elements are kept, never page content.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import runpy
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src/gaiora/web"
STYLESHEET = WEB / "assets/workbench.css"
RECORD = ROOT / "docs/workbench-source.json"
SOURCE_FILE = "scripts/gstudio_workbench_assets.py"
FONT = "url('../fonts/gstudio-display.woff2')"
# Machine paths and addresses must never reach the public package. Names that are private to the
# maintainer (people, machines, internal systems) live in a local file outside the repository.
FORBIDDEN = ("/Users/", "/Volumes/", "/home/", "192.168.", "10.0.", "file://", "http://", "https://")
PRIVATE_MARKERS = Path("~/.config/gaiora/style-sync-private-markers.txt").expanduser()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def private_markers(path: Path = PRIVATE_MARKERS) -> tuple[str, ...]:
    if not path.exists():
        return ()
    return tuple(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#"))


def sensitive(text: str, extra: tuple[str, ...] = ()) -> list[str]:
    return [word for word in FORBIDDEN + extra if word.lower() in text.lower()]


PAGE_STYLES = (("project view", "/projects"), ("project detail", "project"), ("task detail", "task"), ("settings", "/settings"))


def fetch(base: str, path: str) -> str:
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=20) as response:
        return response.read().decode("utf-8")


def page_styles(base: str) -> str:
    """Return the page-specific <style> blocks, deduplicated, in a stable order."""
    projects = fetch(base, "/projects")
    project = re.search(r'href="(/projects/[a-z0-9][a-z0-9_-]*)"', projects)
    task_page = None
    for match in re.finditer(r'href="(/tasks/[A-Za-z0-9_.-]+)"', projects):
        html = fetch(base, match.group(1))
        if "has-materials" in html:
            task_page = html
            break
    if not project or task_page is None:
        raise SystemExit("could not find a project and a task with materials on the running workbench")
    pages = {"/projects": projects, "project": fetch(base, project.group(1)), "task": task_page, "/settings": fetch(base, "/settings")}
    blocks, seen = [], set()
    for label, key in PAGE_STYLES:
        for block in re.findall(r"<style[^>]*>(.*?)</style>", pages[key], re.S):
            block = block.strip()
            if block and block not in seen:
                seen.add(block)
                blocks.append(f"/* {label} */\n{block}")
    return "\n".join(blocks)


def extract(source: Path, base: str) -> tuple[str, str]:
    module = source / SOURCE_FILE
    if not module.is_file():
        raise SystemExit(f"not a workbench checkout: {module} is missing")
    css = runpy.run_path(str(module))["CSS"]
    font = re.search(r"url\(data:font/woff2;base64,([^)]+)\)", css)
    if font and sha256(base64.b64decode(font.group(1))) != sha256((WEB / "fonts/gstudio-display.woff2").read_bytes()):
        raise SystemExit("the workbench display font differs from the bundled OFL font; review licensing before syncing")
    css = re.sub(r"url\(data:font/woff2;base64,[^)]+\)", FONT, css) + "\n" + page_styles(base)
    if found := sensitive(css, private_markers()):
        raise SystemExit(f"stylesheet contains {len(found)} private marker(s), nothing written; check against {PRIVATE_MARKERS}")
    revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    header = "/* Copied from the GStudio workbench by tools/sync_workbench_styles.py; edit upstream, then resync. */\n"
    return header + css.strip() + "\n", revision


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, type=Path, help="local checkout of the full workbench")
    parser.add_argument("--workbench-url", default="http://127.0.0.1:8765", help="running workbench for page styles")
    parser.add_argument("--check", action="store_true", help="exit 1 when the copy differs; write nothing")
    args = parser.parse_args(argv)
    css, revision = extract(args.source.expanduser().resolve(), args.workbench_url)
    current = STYLESHEET.read_text(encoding="utf-8") if STYLESHEET.exists() else ""
    if args.check:
        if current == css:
            print("workbench stylesheet is current")
            return 0
        print("workbench stylesheet has drifted; review the pages, then run without --check")
        return 1
    STYLESHEET.write_text(css, encoding="utf-8")
    RECORD.write_text(json.dumps({"schema": 1, "source_commit": revision, "source_file": SOURCE_FILE,
                                  "stylesheet_sha256": sha256(css.encode())}, indent=2) + "\n", encoding="utf-8")
    print(f"copied {len(css)} characters from {revision[:12] or 'unknown revision'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
