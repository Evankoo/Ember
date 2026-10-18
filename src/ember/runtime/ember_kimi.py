#!/usr/bin/env python3
"""Safe Kimi Code launcher and material-archive prompt builder for Ember."""
from __future__ import annotations
from .ember_compat import env as ember_env
from ..deployment import runtime_root as _deployment_root

import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from . import ember_archive_index as archive_index
from . import workspace_paths

ROOT = _deployment_root()
EXAMPLE_CONFIG_PATH = ROOT / "config" / "ember-executors.example.json"
USER_CONFIG_PATH = workspace_paths.local_config_root() / "executors.json"


class KimiIntegrationError(RuntimeError):
    pass


def config() -> dict[str, object]:
    configured = ember_env("EMBER_EXECUTOR_CONFIG")
    path = Path(configured).expanduser() if configured else USER_CONFIG_PATH
    if not path.exists():
        path = EXAMPLE_CONFIG_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    settings = payload.get("kimi")
    if not isinstance(settings, dict):
        raise KimiIntegrationError("Kimi 执行器配置缺失。")
    return settings


def kimi_command() -> Path:
    configured = ember_env("EMBER_KIMI_COMMAND")
    candidates = [configured] if configured else []
    found = shutil.which("kimi")
    if found:
        candidates.append(found)
    configured_candidates = config().get("command_candidates")
    if isinstance(configured_candidates, list):
        candidates.extend(str(value) for value in configured_candidates)
    for value in candidates:
        if not value:
            continue
        path = Path(value).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return path.resolve()
    raise KimiIntegrationError("当前机器没有找到可执行的 Kimi Code。")


def archive_prompt(project_name: str = "") -> str:
    index = archive_index.load_index()
    projects = index.get("projects") if isinstance(index.get("projects"), list) else []
    selected = [item for item in projects if isinstance(item, dict) and (not project_name or item.get("name") == project_name)]
    if project_name and not selected:
        raise KimiIntegrationError("归档索引中没有找到指定项目。")
    if not selected:
        raise KimiIntegrationError("归档索引为空，请先刷新百度归档索引。")
    scope = project_name or "全部 余烬 · Ember 项目资料"
    remote_paths = [str(item.get("remote_path") or "") for item in selected if item.get("remote_path")]
    remote_scope = "、".join(remote_paths) or str(index.get("remote_root") or "/apps/bypy/100项目")
    lines = [
        "## 余烬 · Ember 项目两级目录整理",
        "",
        f"- 整理项目：{scope}",
        f"- 项目远程根目录：{remote_scope}",
        f"- 本地只读索引：{archive_index.CACHE_PATH}",
        f"- 索引时间：{index.get('generated_at') or '未知'}",
        "- 整理深度：项目根目录 + 根目录下的一级分类目录（项目两级目录）",
        "",
        "### 必须先读取",
        "",
        f"1. `{ROOT / 'AGENTS.md'}`",
        f"2. `{ROOT / 'skills/project-intake/SKILL.md'}`",
        f"3. `{ROOT / 'skills/bypy/SKILL.md'}`",
        "",
        "### 整理目标",
        "",
        "1. 先解析或创建本次目录整理任务卡并通过 preflight；这是批量目录治理，不使用 ledger_only。",
        "2. 使用 bypy 只读列出项目根目录，以及根目录下每个一级分类目录的直接内容；本轮不递归整理更深层级。",
        "3. 按 project-intake 的项目分类路径表检查项目根目录：只保留当前项目实际启用的标准分类，找出散落文件、重复分类、非标准命名和明显放错位置的内容。",
        "4. 检查每个一级分类目录的直接内容，找出命名不规范、重复、分类错误和应合并的二级条目；发布归档、活动素材等目录分别遵守其命名规则。",
        "5. 先输出整理方案表，至少包含：当前路径、建议目标路径、动作、理由、冲突或风险。",
        "6. 完成 project-intake 要求的项目/分类确认与来源/目标/动作确认；未经 Evan 明确确认，不执行移动、改名、合并、覆盖或删除。",
        "7. 确认后只执行方案中获批的动作；遇到重名或内容冲突立即停下，不自动覆盖，不用删除来代替整理。",
        "8. 执行后重新列目录验证结果，刷新两级索引，并把真实变更追加到共享 `管理中心/归档管理/归档记录/资料归档记录.md`；同时更新任务卡。",
        "",
        "### 安全边界",
        "",
        "- bypy 仅能访问 `/apps/bypy` 应用目录，不把它当作百度网盘完整根目录。",
        "- 任何移动、改名、合并、覆盖或删除都必须以 Evan 确认的路径清单为准。",
        "- 不整理项目两级目录以下的内容；发现深层问题只记录为后续建议。",
        "- 没有执行并复核的动作不得写成已完成。",
    ]
    return "\n".join(lines)


def _apple_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _copy_to_clipboard(text: str, runner=subprocess.run) -> None:
    """Copy text to the system clipboard using macOS pbcopy."""
    if not text:
        return
    result = runner(
        ["/usr/bin/pbcopy"],
        input=text,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "pbcopy failed").strip()
        raise KimiIntegrationError(f"无法复制提示词到剪贴板：{detail}")


def _otty_is_running(runner=subprocess.run) -> bool:
    try:
        result = runner(
            ["/usr/bin/pgrep", "-x", "Otty"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def otty_cli(settings: dict[str, object] | None = None) -> Path | None:
    candidates = (settings or config()).get("terminal_cli_candidates")
    values = list(candidates) if isinstance(candidates, list) else []
    values.append("/Applications/Otty.app/Contents/MacOS/otty-cli")
    for value in values:
        path = Path(str(value)).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return path.resolve()
    return None


def _build_shell_command(*, cwd: Path, executable: Path, mode: str, prompt: str = "") -> str:
    """Build the shell command that opens an executor in Otty.

    The prompt argument is accepted for API compatibility but is intentionally
    not embedded in the shell command. Prompt text is copied to the system
    clipboard separately so the user can paste it into the new executor session;
    this function must not paste text or submit a command.
    """
    del prompt
    del mode
    return f"cd {shlex.quote(str(cwd))} && {shlex.quote(str(executable))}"


def launch_in_otty(*, title: str = "", prompt: str = "", runner=subprocess.run) -> None:
    """Launch Kimi Code in Otty.

    When a prompt is provided, it is first copied to the system clipboard via
    ``pbcopy`` so the user can paste it into the new Kimi session. Then Kimi is
    started in a fresh Otty tab: the running-tab path uses the official CLI to
    create an isolated tab and sends only the Kimi executable path to that new
    pane; the cold-launch path falls back to AppleScript ``do script`` without
    ``in front window``. AppleScript is deliberately never used to write into an
    existing pane.
    """
    launch_command_in_otty(
        executable=kimi_command(),
        settings=config(),
        executor_label="Kimi Code",
        title=title,
        prompt=prompt,
        runner=runner,
    )


def launch_command_in_otty(
    *,
    executable: Path,
    settings: dict[str, object],
    executor_label: str,
    title: str = "",
    prompt: str = "",
    cwd: Path = ROOT,
    runner=subprocess.run,
) -> None:
    """Launch one configured command in a new Otty tab or window."""
    del title
    bundle_id = str(settings.get("terminal_bundle_id") or "io.appmakes.otty")
    mode = str(settings.get("mode") or "normal")
    command = _build_shell_command(
        cwd=cwd, executable=executable, mode=mode, prompt=prompt
    )
    _copy_to_clipboard(prompt, runner=runner)
    is_running = _otty_is_running(runner=runner)
    if is_running:
        cli = otty_cli(settings)
        if not cli:
            raise KimiIntegrationError("Otty 已打开，但找不到 otty-cli，无法安全新建标签页。")
        listed = runner(
            [str(cli), "tab", "list", "--json"], capture_output=True, text=True,
            timeout=5, check=False,
        )
        try:
            tabs = json.loads(listed.stdout).get("data", []) if listed.returncode == 0 else []
        except (json.JSONDecodeError, AttributeError):
            tabs = []
        active = next(
            (item for item in tabs if isinstance(item, dict) and item.get("active") and item.get("window_id")),
            None,
        )
        if not active:
            raise KimiIntegrationError(f"Otty 已打开，但无法识别当前窗口；为避免写入现有 {executor_label} 会话，已停止启动。")
        previous_tab_ids = {
            str(item.get("id")) for item in tabs if isinstance(item, dict) and item.get("id")
        }
        created = runner(
             [str(cli), "tab", "new", "--window", str(active["window_id"]),
             "--cwd", str(cwd)],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if created.returncode != 0:
            detail = (created.stderr or created.stdout or "otty-cli tab new failed").strip()
            raise KimiIntegrationError(f"无法在 Otty 新建 {executor_label} 标签页：{detail}")
        new_tab = None
        for _ in range(20):
            current = runner(
                [str(cli), "tab", "list", "--json"], capture_output=True, text=True,
                timeout=5, check=False,
            )
            try:
                current_tabs = json.loads(current.stdout).get("data", []) if current.returncode == 0 else []
            except (json.JSONDecodeError, AttributeError):
                current_tabs = []
            new_tab = next(
                (item for item in current_tabs if isinstance(item, dict)
                 and str(item.get("id")) not in previous_tab_ids and item.get("id")),
                None,
            )
            if new_tab:
                break
            time.sleep(0.1)
        if not new_tab:
            raise KimiIntegrationError(f"Otty 已创建标签页，但无法识别新标签页；未发送 {executor_label} 启动命令。")
        new_pane = None
        for _ in range(20):
            panes = runner(
                [str(cli), "pane", "list", "--json"], capture_output=True, text=True,
                timeout=5, check=False,
            )
            try:
                pane_items = json.loads(panes.stdout).get("data", []) if panes.returncode == 0 else []
            except (json.JSONDecodeError, AttributeError):
                pane_items = []
            new_pane = next(
                (item for item in pane_items if isinstance(item, dict)
                 and item.get("tab_id") == new_tab.get("id") and item.get("id")),
                None,
            )
            if new_pane:
                break
            time.sleep(0.1)
        if not new_pane:
            raise KimiIntegrationError(f"Otty 已创建标签页，但无法识别新终端；未发送 {executor_label} 启动命令。")
        started = runner(
            [str(cli), "pane", "send-keys", "--pane", str(new_pane["id"]),
             shlex.quote(str(executable)), "key:Enter"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if started.returncode != 0:
            detail = (started.stderr or started.stdout or "otty-cli pane send-keys failed").strip()
            if "send-keys is disabled" in detail or "ipc-allow-send-keys" in detail:
                detail += (
                    "\n\n请在 Otty 配置中启用 IPC send-keys："
                    "\n1. 打开 ~/.config/otty/config.toml"
                    "\n2. 添加 ipc-allow-send-keys = true"
                    "\n3. 完全退出并重新启动 Otty，然后重试。"
                )
            raise KimiIntegrationError(f"{executor_label} 新标签页已创建，但启动失败：{detail}")
        return
    apple_bundle = _apple_string(bundle_id)
    apple_cmd = _apple_string(command)
    lines = [f'tell application id "{apple_bundle}"']
    lines.append('  activate')
    lines.append(f'  do script "{apple_cmd}"')
    lines.extend([
        '  return "ok"',
        'end tell',
    ])
    script = "\n".join(lines)
    log_path = Path("/tmp/ember_kimi_launch.log")
    try:
        result = runner(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        log_path.write_text(
            f"osascript exit: {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}\n"
            f"script:\n{script}\n",
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(f"osascript timeout\nscript:\n{script}\n", encoding="utf-8")
        raise KimiIntegrationError(f"打开 Otty 中的 {executor_label} 超时。") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Otty launch failed").strip()
        raise KimiIntegrationError(f"无法在 Otty 中启动 {executor_label}：{detail}")
