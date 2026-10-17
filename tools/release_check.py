#!/usr/bin/env python3
"""Release gate: nothing is tagged or uploaded unless every check below passes.

    python tools/release_check.py --source <workbench checkout>

1. unit and browser tests;
2. the shared interface files are still the full workbench's (sync_workbench_styles.py --check);
3. every page still matches the full workbench, apart from the differences listed in
   docs/workbench-parity.json (check_workbench_parity.py, which refreshes the record);
4. the version is named consistently and the changelog has a section for it.

It changes nothing except docs/workbench-parity-record.json and prints what to commit.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def step(title: str, argv: list[str]) -> bool:
    print(f"\n== {title}", flush=True)
    return subprocess.run(argv, cwd=ROOT).returncode == 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="发布前门禁：测试、样式表同步与逐页界面对照")
    parser.add_argument("--source", required=True, type=Path, help="完整版工作台的本地仓库")
    parser.add_argument("--workbench-url", default="http://127.0.0.1:8765")
    args = parser.parse_args(argv)
    python = sys.executable
    sys.path.insert(0, str(ROOT / "src"))
    from ember import __version__
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    results = {
        "测试": step("测试（含浏览器）", [python, "-m", "unittest", "discover", "-s", "tests"]),
        "样式表": step("公共界面文件与完整版一致", [python, "tools/sync_workbench_styles.py", "--source", str(args.source), "--workbench-url", args.workbench_url, "--check"]),
        "界面对照": step("逐页界面对照", [python, "tools/check_workbench_parity.py", "--source", str(args.source), "--workbench-url", args.workbench_url, "--write-record"]),
        "版本说明": bool(re.search(rf"(?m)^## {re.escape(__version__)}[：:]", changelog)) and "## 未发布" not in changelog,
    }
    print("\n== 结果")
    for name, ok in results.items():
        print(f"{'通过' if ok else '未通过'}  {name}")
    if not all(results.values()):
        if not results["版本说明"]:
            print(f"CHANGELOG 需要有 “## {__version__}：” 一节，且不再保留“未发布”。")
        print("门禁未通过：不要打标签或上传发行版。")
        return 1
    print("门禁通过。提交 docs/workbench-parity-record.json 后再打标签发布。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
