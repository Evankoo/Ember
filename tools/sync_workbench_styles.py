#!/usr/bin/env python3
"""Copy the full workbench's shared interface layer into the open-source package.

The public interface is derived from the full workbench used in practice. Its shared
interface layer (`ui/ember_ui/`: page templates, Markdown rendering, and the stylesheets and
scripts in `static/`) is copied here verbatim into `src/ember/ember_ui/`; nothing in that folder
is edited in this repository. The source files are read as inert text; no workbench service,
data or configuration is loaded or imported.

    python tools/sync_workbench_styles.py --source <workbench checkout>          # update
    python tools/sync_workbench_styles.py --source <workbench checkout> --check  # report drift only

Some workbench pages still carry their own <style> blocks. Those are read from the locally
running workbench (--workbench-url) into assets/workbench-pages.css; only the <style>
elements are kept, never page content. Blocks already shipped in the shared layer are skipped.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src/ember/web"
SHARED = ROOT / "src/ember/ember_ui"
PAGE_STYLESHEET = WEB / "assets/workbench-pages.css"
RECORD = ROOT / "docs/workbench-source.json"
SOURCE_DIR = "ui/ember_ui"
COPIED = (".py", ".css", ".js", ".md")
FONT = WEB / "fonts/gstudio-display.woff2"
# Machine paths and addresses must never reach the public package. Names that are private to the
# maintainer (people, machines, internal systems) live in a local file outside the repository.
FORBIDDEN = ("/Users/", "/Volumes/", "/home/", "192.168.", "10.0.", "file://", "http://", "https://")
PRIVATE_MARKERS = Path("~/.config/ember/style-sync-private-markers.txt").expanduser()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def private_markers(path: Path = PRIVATE_MARKERS) -> tuple[str, ...]:
    if not path.exists():
        return ()
    return tuple(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#"))


# A machine home path, not an endpoint such as /api/home/search.
HOME_PATH = re.compile(r"(?<![\w/])/home/")


def sensitive(text: str, extra: tuple[str, ...] = ()) -> list[str]:
    # Embedded font data is base64 and the SVG namespace is a fixed identifier, not text that could
    # carry a private name or address.
    text = re.sub(r"url\(data:[^)]*\)", "url(data:)", text).replace('xmlns="http://www.w3.org/2000/svg"', "")
    found = [word for word in FORBIDDEN + extra if word != "/home/" and word.lower() in text.lower()]
    return found + (["/home/"] if "/home/" in FORBIDDEN + extra and HOME_PATH.search(text) else [])


PAGE_STYLES = (("project view", "/projects"), ("project detail", "project"), ("task detail", "task"), ("settings", "/settings"))


def fetch(base: str, path: str) -> str:
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=20) as response:
        return response.read().decode("utf-8")


def page_styles(base: str, shipped: set[str]) -> str:
    """Return the page-specific <style> blocks not already in the shared layer, in a stable order."""
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
    blocks, seen = [], set(shipped)
    for label, key in PAGE_STYLES:
        for block in re.findall(r"<style[^>]*>(.*?)</style>", pages[key], re.S):
            block = block.strip()
            if block and block not in seen:
                seen.add(block)
                blocks.append(f"/* {label} */\n{block}")
    return "\n".join(blocks)


def extract(source: Path, base: str) -> tuple[dict[str, bytes], str, str]:
    """Shared files (name -> bytes), the page stylesheet and the source revision."""
    folder = source / SOURCE_DIR
    if not (folder / "static").is_dir():
        raise SystemExit(f"not a workbench checkout: {folder}/static is missing")
    files = {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*"))
             if path.is_file() and path.suffix in COPIED and "__pycache__" not in path.parts and not path.name.startswith(".")}
    if "static/workbench.css" not in files:
        raise SystemExit(f"unexpected layout in {folder}: static/workbench.css is missing")
    for font in re.findall(r"url\(data:font/woff2;base64,([^)]+)\)", files["static/workbench.css"].decode("utf-8")):
        if sha256(base64.b64decode(font)) != sha256(FONT.read_bytes()):
            raise SystemExit("the workbench display font differs from the bundled OFL font; review licensing before syncing")
    shipped = {data.decode("utf-8").strip() for name, data in files.items() if name.endswith(".css")}
    header = "/* Page-level styles read from the running workbench by tools/sync_workbench_styles.py; edit upstream, then resync. */\n"
    pages = header + page_styles(base, shipped).strip() + "\n"
    found = []
    for name, data in {**files, PAGE_STYLESHEET.name: pages.encode()}.items():
        found += [f"{name}: {word}" for word in sensitive(data.decode("utf-8"), private_markers())]
    if found:
        raise SystemExit(f"shared interface contains {len(found)} private marker(s), nothing written; check against {PRIVATE_MARKERS}")
    revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return files, pages, revision


def current_copy() -> dict[str, bytes]:
    if not SHARED.is_dir():
        return {}
    return {path.relative_to(SHARED).as_posix(): path.read_bytes() for path in sorted(SHARED.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, type=Path, help="local checkout of the full workbench")
    parser.add_argument("--workbench-url", default="http://127.0.0.1:8765", help="running workbench for page styles")
    parser.add_argument("--check", action="store_true", help="exit 1 when the copy differs; write nothing")
    args = parser.parse_args(argv)
    files, pages, revision = extract(args.source.expanduser().resolve(), args.workbench_url)
    current_pages = PAGE_STYLESHEET.read_text(encoding="utf-8") if PAGE_STYLESHEET.exists() else ""
    if args.check:
        if current_copy() == files and current_pages == pages:
            print("workbench interface files are current")
            return 0
        print("workbench interface files have drifted; review the pages, then run without --check")
        return 1
    for name in set(current_copy()) - set(files):
        (SHARED / name).unlink()
    for name, data in files.items():
        (SHARED / name).parent.mkdir(parents=True, exist_ok=True)
        (SHARED / name).write_bytes(data)
    PAGE_STYLESHEET.write_text(pages, encoding="utf-8")
    RECORD.write_text(json.dumps({
        "schema": 2, "source_commit": revision, "source_dir": SOURCE_DIR,
        "files": {name: sha256(data) for name, data in files.items()},
        "page_styles_sha256": sha256(pages.encode()),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"copied {len(files)} shared files and page styles from {revision[:12] or 'unknown revision'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
